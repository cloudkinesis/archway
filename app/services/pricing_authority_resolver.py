from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import re
import select
import shutil
import subprocess
from decimal import Decimal
from typing import Any
from uuid import uuid4

from app.core.config import get_settings
from app.domain.pricing_evidence import PriceDimensionEvidence, PriceListParseResult
from app.domain.source_of_truth import AwsRateBinding, ServiceUsageDimension
from app.services.aws_price_list_parser import parse_price_list_offer, parse_price_list_query_response


TermGroups = tuple[frozenset[str], ...]


@dataclass(frozen=True)
class RateFilterRule:
    service_code: str
    canonical_unit: str
    filters: dict[str, str]
    required_term_groups: TermGroups = field(default_factory=tuple)


@dataclass(frozen=True)
class UnitCompatibilityRule:
    service_code: str
    attribute_contains: dict[str, tuple[str, ...]]
    required_term_groups: TermGroups


SERVICE_CODE_ALIASES = {
    "AWSStates": "AmazonStates",
}


RATE_FILTER_RULES: tuple[RateFilterRule, ...] = (
    RateFilterRule("AmazonKinesis", "requests", {"productFamily": "Kinesis Streams"}),
    RateFilterRule("AmazonS3", "gb", {"productFamily": "Storage"}),
    RateFilterRule("AWSLambda", "requests", {"group": "AWS-Lambda-Requests"}),
    RateFilterRule(
        "AmazonStates",
        "requests",
        {"group": "SFN-StateTransitions"},
        required_term_groups=(
            frozenset({"state", "statetransition", "statetransitions"}),
            frozenset({"transition", "transitions", "statetransition", "statetransitions"}),
        ),
    ),
    RateFilterRule(
        "AmazonStates",
        "requests",
        {"group": "SFN-ExpressWorkflows-Requests"},
        required_term_groups=(frozenset({"express"}), frozenset({"request", "requests", "execution", "executions"})),
    ),
    RateFilterRule("AWSEvents", "requests", {"productFamily": "EventBridge"}),
    RateFilterRule("AWSQueueService", "requests", {"queueType": "Standard"}),
    RateFilterRule("AmazonSNS", "requests", {"group": "Requests-Tier1"}),
    RateFilterRule(
        "AmazonCloudWatch",
        "requests",
        {"productFamily": "Data Ingestion"},
        required_term_groups=(frozenset({"log", "logs", "record", "records"}),),
    ),
)


UNIT_COMPATIBILITY_RULES: tuple[UnitCompatibilityRule, ...] = (
    UnitCompatibilityRule(
        "AmazonStates",
        {"usage_type": ("statetransition",)},
        (
            frozenset({"state", "statetransition", "statetransitions"}),
            frozenset({"transition", "transitions", "statetransition", "statetransitions"}),
        ),
    ),
    UnitCompatibilityRule(
        "AmazonStates",
        {"usage_type": ("stepfunctions-request",)},
        (frozenset({"express"}), frozenset({"request", "requests", "execution", "executions"})),
    ),
    UnitCompatibilityRule(
        "AmazonStates",
        {"usage_type": ("gb-second",)},
        (frozenset({"duration", "gbsecond", "gbseconds", "second", "seconds"}),),
    ),
    UnitCompatibilityRule(
        "AWSEvents",
        {"unit": ("chunk",), "usage_type": ("chunk",)},
        (frozenset({"chunk", "chunks", "64k", "kb", "kilobyte", "kilobytes"}),),
    ),
    UnitCompatibilityRule(
        "AWSEvents",
        {"usage_type": ("scheduledinvocation",), "operation": ("invocation",)},
        (frozenset({"schedule", "scheduled", "scheduler", "invocation", "invocations"}),),
    ),
    UnitCompatibilityRule(
        "AWSEvents",
        {"operation": ("piperequest",), "usage_type": ("pipe",)},
        (frozenset({"pipe", "pipes"}),),
    ),
)


class PricingAuthorityResolver:
    """Bind a service usage dimension to an authoritative AWS rate.

    Procurement readiness is deliberately fail-closed: only a single exact
    OnDemand rate candidate with a concrete quantity can become ``bound``.
    MCP text summaries, ambiguous matches, missing quantities, and unknown
    service codes remain non-procurement signals.
    """

    def resolve(self, dimension: ServiceUsageDimension, *, region_code: str) -> AwsRateBinding:
        dimension = _normalize_dimension_aliases(dimension)
        preflight = _preflight_unbound(dimension)
        if preflight:
            return preflight

        failures: list[str] = []
        mcp_result = _resolve_via_pricing_mcp(dimension, region_code)
        if mcp_result.dimensions:
            return _binding_from_candidates(
                dimension,
                mcp_result,
                source_label="AWS Pricing MCP",
                extra_notes=failures,
            )
        failures.extend(mcp_result.failures)

        query_result = _resolve_via_price_list_query_api(dimension, region_code)
        if query_result.dimensions:
            return _binding_from_candidates(
                dimension,
                query_result,
                source_label="AWS Price List Query API",
                extra_notes=failures,
            )
        failures.extend(query_result.failures)

        return AwsRateBinding(
            service_name=dimension.service_name,
            aws_service_code=dimension.aws_service_code,
            unit=dimension.unit,
            binding_status="not_found",
            source="unbound",
            confidence="low",
            notes=_dedupe_notes([
                *failures,
                f"No authoritative OnDemand price dimension matched usage '{dimension.usage_name}' with unit '{dimension.unit}'.",
            ]),
        )


def _preflight_unbound(dimension: ServiceUsageDimension) -> AwsRateBinding | None:
    if dimension.aws_service_code == "unknown":
        return AwsRateBinding(
            service_name=dimension.service_name,
            aws_service_code=dimension.aws_service_code,
            binding_status="unsupported",
            notes=["No supported AWS service code is available for this service usage dimension."],
        )
    if dimension.quantity is None:
        return AwsRateBinding(
            service_name=dimension.service_name,
            aws_service_code=dimension.aws_service_code,
            unit=dimension.unit,
            binding_status="not_found",
            notes=["No concrete usage quantity was available, so exact rate binding was skipped."],
        )
    return None


def _normalize_dimension_aliases(dimension: ServiceUsageDimension) -> ServiceUsageDimension:
    normalized = SERVICE_CODE_ALIASES.get(dimension.aws_service_code)
    if normalized:
        return dimension.model_copy(update={"aws_service_code": normalized})
    return dimension


def _resolve_via_pricing_mcp(dimension: ServiceUsageDimension, region_code: str) -> PriceListParseResult:
    settings = get_settings()
    if not (settings.enable_aws_pricing_mcp and settings.aws_pricing_mcp_command):
        return PriceListParseResult(
            service_code=dimension.aws_service_code,
            dimensions=[],
            failures=["AWS Pricing MCP stdio command is not configured."],
        )
    command = _resolved_mcp_command(settings.aws_pricing_mcp_command)
    if not command:
        return PriceListParseResult(
            service_code=dimension.aws_service_code,
            dimensions=[],
            failures=[f"AWS Pricing MCP command is configured but not executable: {settings.aws_pricing_mcp_command}."],
        )
    try:
        result = _call_aws_labs_pricing_mcp(dimension, region_code, command=command)
        payload = _structured_payload_from_mcp_result(result)
        if not payload:
            return PriceListParseResult(
                service_code=dimension.aws_service_code,
                dimensions=[],
                failures=["AWS Pricing MCP returned no structured Price List payload; text summaries are not rate authority."],
            )
        parsed = _parse_structured_price_payload(
            payload,
            service_code=dimension.aws_service_code,
            source_reference=f"pricing_mcp:get_pricing:{dimension.aws_service_code}",
            source="pricing_mcp",
        )
        return _filter_for_dimension(dimension, parsed)
    except Exception as exc:
        return PriceListParseResult(
            service_code=dimension.aws_service_code,
            dimensions=[],
            failures=[f"AWS Pricing MCP lookup failed: {type(exc).__name__}: {str(exc)[:220]}"],
        )


def _resolve_via_price_list_query_api(dimension: ServiceUsageDimension, region_code: str) -> PriceListParseResult:
    if not get_settings().enable_aws_price_list_query_api:
        return PriceListParseResult(
            service_code=dimension.aws_service_code,
            dimensions=[],
            failures=["AWS Price List Query API fallback is disabled. Set ARCHWAY_ENABLE_AWS_PRICE_LIST_QUERY_API=true for live boto3 pricing authority lookup."],
        )
    try:
        response = _get_products(dimension, region_code)
        parsed = parse_price_list_query_response(
            response,
            service_code=dimension.aws_service_code,
            source_reference=f"pricing:GetProducts:{dimension.aws_service_code}",
        )
        return _filter_for_dimension(dimension, parsed)
    except Exception as exc:
        return PriceListParseResult(
            service_code=dimension.aws_service_code,
            dimensions=[],
            failures=[f"AWS Price List Query API lookup failed: {type(exc).__name__}: {str(exc)[:220]}"],
        )


def _resolved_mcp_command(command: str | None) -> str | None:
    if not command:
        return None
    if os.path.sep in command:
        if os.path.isfile(command) and os.access(command, os.X_OK):
            return command
        return shutil.which(os.path.basename(command))
    return shutil.which(command)


def _call_aws_labs_pricing_mcp(dimension: ServiceUsageDimension, region_code: str, *, command: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    env = {
        **os.environ,
        "FASTMCP_LOG_LEVEL": "ERROR",
        "AWS_PROFILE": settings.aws_pricing_mcp_aws_profile,
        "AWS_REGION": settings.aws_pricing_mcp_aws_region,
    }
    process = subprocess.Popen(
        [command or settings.aws_pricing_mcp_command or "", *settings.aws_pricing_mcp_args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        _stdio_rpc(process, "initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "archway", "version": "0.1"},
        })
        _stdio_notify(process, "notifications/initialized", {})
        return _stdio_rpc(process, "tools/call", {
            "name": "get_pricing",
            "arguments": _mcp_pricing_arguments(dimension, region_code),
        })
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _stdio_rpc(process: subprocess.Popen[str], method: str, params: dict[str, Any]) -> dict[str, Any]:
    timeout = float(get_settings().pricing_authority_timeout_seconds)
    request_id = uuid4().hex
    _stdio_write(process, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    while True:
        if process.stdout is None:
            raise RuntimeError("MCP process stdout is unavailable.")
        ready, _, _ = select.select([process.stdout], [], [], timeout)
        if not ready:
            raise TimeoutError(f"MCP request timed out waiting for {method}.")
        line = process.stdout.readline()
        if not line:
            stderr = process.stderr.read(1000) if process.stderr is not None else ""
            raise RuntimeError(f"MCP process ended before responding. {stderr}".strip())
        payload = json.loads(line)
        if payload.get("id") != request_id:
            continue
        if "error" in payload:
            error = payload["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise RuntimeError(message or f"MCP request failed: {method}")
        result = payload.get("result")
        return result if isinstance(result, dict) else {"result": result}


def _stdio_notify(process: subprocess.Popen[str], method: str, params: dict[str, Any]) -> None:
    _stdio_write(process, {"jsonrpc": "2.0", "method": method, "params": params})


def _stdio_write(process: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    if process.stdin is None:
        raise RuntimeError("MCP process stdin is unavailable.")
    process.stdin.write(json.dumps(payload) + "\n")
    process.stdin.flush()


def _mcp_pricing_arguments(dimension: ServiceUsageDimension, region_code: str) -> dict[str, Any]:
    filters = [
        {"Field": item["Field"], "Type": "EQUALS", "Value": item["Value"]}
        for item in _filters_for_dimension(dimension, region_code)
    ]
    return {
        "service_code": dimension.aws_service_code,
        "region": region_code,
        "filters": filters,
        "max_results": 12,
        "max_allowed_characters": 24000,
        "output_options": {
            "pricing_terms": ["OnDemand", "FlatRate"],
            "exclude_free_products": True,
        },
    }


def _structured_payload_from_mcp_result(result: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[Any] = [result]
    content = result.get("content")
    if isinstance(content, list):
        candidates.extend(item.get("text") for item in content if isinstance(item, dict))
    for candidate in candidates:
        payload = _json_payload(candidate)
        if isinstance(payload, dict) and (_looks_like_query_response(payload) or _looks_like_offer(payload)):
            return payload
    return None


def _json_payload(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    for candidate in (text, _extract_json_object(text)):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _extract_json_object(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    return text[start:end + 1]


def _parse_structured_price_payload(
    payload: dict[str, Any],
    *,
    service_code: str,
    source_reference: str,
    source: str,
) -> PriceListParseResult:
    if _looks_like_query_response(payload):
        return parse_price_list_query_response(
            payload,
            service_code=service_code,
            source_reference=source_reference,
            source=source,
        )
    if _looks_like_offer(payload):
        return parse_price_list_offer(
            payload,
            service_code=service_code,
            source_reference=source_reference,
            source=source,
        )
    return PriceListParseResult(service_code=service_code, dimensions=[], failures=["Unsupported structured pricing payload shape."])


def _looks_like_query_response(payload: dict[str, Any]) -> bool:
    return isinstance(payload.get("PriceList"), list)


def _looks_like_offer(payload: dict[str, Any]) -> bool:
    return isinstance(payload.get("products"), dict) and isinstance(payload.get("terms"), dict)


def _filter_for_dimension(dimension: ServiceUsageDimension, parsed: PriceListParseResult) -> PriceListParseResult:
    matches = _matching_dimensions(dimension, parsed.dimensions)
    return PriceListParseResult(
        service_code=parsed.service_code,
        dimensions=matches,
        ambiguous_skus=parsed.ambiguous_skus,
        failures=parsed.failures,
    )


def _binding_from_candidates(
    dimension: ServiceUsageDimension,
    parsed: PriceListParseResult,
    *,
    source_label: str,
    extra_notes: list[str],
) -> AwsRateBinding:
    candidates = parsed.dimensions
    if len(candidates) > 1:
        return _binding_from_dimension(
            dimension,
            candidates[0],
            status="ambiguous",
            confidence="medium",
            notes=_dedupe_notes([
                *extra_notes,
                *parsed.failures,
                f"{len(candidates)} plausible {source_label} rates matched; Archway did not silently choose one.",
                "Confirm usage type, operation, region/edge location, tier, and product attributes before procurement use.",
            ]),
        )
    return _binding_from_dimension(
        dimension,
        candidates[0],
        status="bound",
        confidence="high",
        notes=_dedupe_notes([
            *extra_notes,
            *parsed.failures,
            f"Exact single OnDemand price dimension matched through {source_label}.",
        ]),
    )


def _get_products(dimension: ServiceUsageDimension, region_code: str) -> dict[str, Any]:
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "pricing",
        region_name="us-east-1",
        config=Config(connect_timeout=5, read_timeout=12, retries={"max_attempts": 2}),
    )
    filters = _filters_for_dimension(dimension, region_code)
    price_list: list[Any] = []
    token: str | None = None
    for _ in range(3):
        kwargs: dict[str, Any] = {
            "ServiceCode": dimension.aws_service_code,
            "Filters": filters,
            "MaxResults": 100,
        }
        if token:
            kwargs["NextToken"] = token
        response = client.get_products(**kwargs)
        price_list.extend(response.get("PriceList") or [])
        token = response.get("NextToken")
        if not token:
            break
    return {"PriceList": price_list}


def _filters_for_dimension(dimension: ServiceUsageDimension, region_code: str) -> list[dict[str, str]]:
    filters: list[dict[str, str]] = []
    if dimension.aws_service_code != "AmazonCloudFront":
        filters.append({"Type": "TERM_MATCH", "Field": "regionCode", "Value": region_code})
    required = {**dimension.required_rate_dimensions, **_inferred_rate_dimensions(dimension)}
    for key, value in required.items():
        if value:
            filters.append({"Type": "TERM_MATCH", "Field": key, "Value": value})
    return _dedupe_filters(filters)


def _matching_dimensions(dimension: ServiceUsageDimension, dimensions: list[PriceDimensionEvidence]) -> list[PriceDimensionEvidence]:
    expected_unit = _canonical_unit(dimension.unit)
    usage_terms = _tokens(f"{dimension.usage_name} {dimension.formula}")
    scored: list[tuple[int, PriceDimensionEvidence]] = []
    for item in dimensions:
        if Decimal(item.price_per_unit) <= 0:
            continue
        item_unit = _canonical_unit(item.unit)
        if expected_unit and item_unit and expected_unit != item_unit:
            continue
        if not _service_specific_unit_compatible(dimension, item):
            continue
        if not _required_dimensions_match(dimension, item):
            continue
        score = _candidate_score(dimension, usage_terms, item)
        if score <= 0:
            continue
        scored.append((score, item))
    if not scored:
        return []
    scored.sort(key=lambda pair: (-pair[0], pair[1].sku, pair[1].rate_code or ""))
    best_score = scored[0][0]
    return [item for score, item in scored if score == best_score][:8]


def _required_dimensions_match(dimension: ServiceUsageDimension, item: PriceDimensionEvidence) -> bool:
    required = {**dimension.required_rate_dimensions, **_inferred_rate_dimensions(dimension)}
    if not required:
        return True
    fields = {
        "usagetype": item.usage_type,
        "usageType": item.usage_type,
        "operation": item.operation,
        "productFamily": item.product_family,
        "regionCode": item.region_code,
        "location": item.location,
    }
    for key, expected in required.items():
        if key not in fields:
            continue
        if expected and str(fields.get(key) or "").lower() != str(expected).lower():
            return False
    return True


def _candidate_score(dimension: ServiceUsageDimension, usage_terms: set[str], item: PriceDimensionEvidence) -> int:
    text = _tokens(" ".join(str(value or "") for value in (
        item.usage_type,
        item.operation,
        item.product_family,
        item.unit,
    )))
    if not text:
        return 0
    shared = usage_terms & text
    score = len(shared) * 4
    expected_unit = _canonical_unit(dimension.unit)
    item_unit = _canonical_unit(item.unit)
    if expected_unit and expected_unit == item_unit:
        score += 5
    if _generic_billable_intent_matches(dimension, item):
        score += 6
    if item.begin_range in {None, "0", "0.0", "0.0000000000"}:
        score += 1
    if shared or _generic_billable_intent_matches(dimension, item):
        return score
    return 1 if not _meaningful_pricing_terms(usage_terms) else 0


def _generic_billable_intent_matches(dimension: ServiceUsageDimension, item: PriceDimensionEvidence) -> bool:
    expected = _canonical_unit(dimension.unit)
    if not expected or expected != _canonical_unit(item.unit):
        return False
    item_terms = _tokens(" ".join(str(value or "") for value in (
        item.usage_type,
        item.operation,
        item.product_family,
        item.unit,
    )))
    usage_terms = _tokens(f"{dimension.usage_name} {dimension.formula} {dimension.service_name}")
    if expected == "requests":
        intent_terms = {"request", "requests", "event", "events", "execution", "executions", "transition", "transitions", "invoke", "invocation", "invocations"}
        return bool((usage_terms & intent_terms) and (item_terms & intent_terms))
    if expected == "gb":
        intent_terms = {"storage", "stored", "timed", "byte", "bytes", "gb", "month"}
        return bool((usage_terms & {"storage", "retention", "archive", "evidence", "object", "objects", "gb", "month"}) and (item_terms & intent_terms))
    if expected == "hours":
        intent_terms = {"hour", "hours", "node", "instance", "kpu", "capacity"}
        return bool((usage_terms & intent_terms) and (item_terms & intent_terms))
    return False


def _service_specific_unit_compatible(dimension: ServiceUsageDimension, item: PriceDimensionEvidence) -> bool:
    """Prevent near-match bindings where AWS bills a narrower service dimension.

    This is intentionally keyed by AWS billing semantics, not customer scenario
    vocabulary. It blocks procurement claims when the source-truth usage
    dimension lacks the exact billable unit shape that the Price List exposes.
    """
    terms = _tokens(f"{dimension.usage_name} {dimension.formula} {dimension.unit}")
    for rule in UNIT_COMPATIBILITY_RULES:
        if rule.service_code != dimension.aws_service_code:
            continue
        if _rule_matches_price_dimension(rule, item):
            return _term_groups_satisfied(terms, rule.required_term_groups)
    return True


def _usage_text_matches(usage_terms: set[str], item: PriceDimensionEvidence) -> bool:
    text = _tokens(" ".join(str(value or "") for value in (
        item.usage_type,
        item.operation,
        item.product_family,
    )))
    if not text:
        return bool(usage_terms)
    shared = usage_terms & text
    if shared:
        return True
    return not _meaningful_pricing_terms(usage_terms)


def _tokens(value: str) -> set[str]:
    spaced = _split_compound_pricing_tokens(value)
    return {
        token
        for token in "".join(char.lower() if char.isalnum() else " " for char in spaced).split()
        if len(token) > 2 and token not in _STOPWORDS
    }


def _split_compound_pricing_tokens(value: str) -> str:
    # AWS Price List fields often use compact/camel-case labels such as
    # PutRequestPayloadUnits. Split them for matching without introducing
    # service-specific vocabulary.
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    value = re.sub(r"([A-Za-z])(\d)", r"\1 \2", value)
    value = re.sub(r"(\d)([A-Za-z])", r"\1 \2", value)
    return value


def _meaningful_pricing_terms(tokens: set[str]) -> set[str]:
    return tokens - {"usage", "month", "monthly", "formula", "derived", "assumed", "service"}


_STOPWORDS = {
    "and", "the", "for", "with", "per", "from", "into", "not", "estimated",
    "usage", "month", "monthly", "formula", "derived", "assumed",
}


def _canonical_unit(unit: str | None) -> str:
    value = str(unit or "").lower().strip()
    compact = value.replace(" ", "").replace("-", "").lower()
    if value in {"gb", "gbs", "gigabyte", "gigabytes", "gb-month", "gb-months", "gb month", "gb months", "gb-mo", "gb-mo."} or compact in {"gbmo", "gbmonth", "gbmonths", "gbmonthmo"}:
        return "gb"
    if value in {"tb", "tbs", "terabyte", "terabytes", "tb-month", "tb-months", "tb month", "tb months", "tb-mo", "tb-mo."} or compact in {"tbmo", "tbmonth", "tbmonths"}:
        return "tb"
    if value in {"request", "requests", "invocation", "invocations", "events", "event", "runs", "executions", "state transition", "state transitions"}:
        return "requests"
    if any(term in compact for term in ("request", "requests", "event", "events", "execution", "executions", "invocation", "invocations", "statetransition", "statetransitions")):
        return "requests"
    if compact in {"putrequest", "putrequests", "putrequestpayloadunit", "putrequestpayloadunits", "request", "requests", "statetransition", "statetransitions"}:
        return "requests"
    if "chunk" in compact:
        return "chunks"
    if value in {"hour", "hours", "hrs", "channel-hours", "channel hours", "node-hours", "node hours"}:
        return "hours"
    if value in {"read/write units proxy", "read write units proxy", "wcu", "rcu"}:
        return "requests"
    return value


def _inferred_rate_dimensions(dimension: ServiceUsageDimension) -> dict[str, str]:
    """Infer safe AWS Price List filters from billable-unit intent.

    These are AWS service/unit mappings, not scenario mappings. They only add a
    filter when the Archway usage dimension has already committed to a concrete
    billable unit shape; ambiguous products remain ambiguous downstream.
    """
    filters: dict[str, str] = {}
    unit = _canonical_unit(dimension.unit)
    usage = _tokens(f"{dimension.usage_name} {dimension.formula} {dimension.service_name}")
    for rule in RATE_FILTER_RULES:
        if rule.service_code != dimension.aws_service_code or rule.canonical_unit != unit:
            continue
        if not _term_groups_satisfied(usage, rule.required_term_groups):
            continue
        filters.update(rule.filters)
    return {key: value for key, value in filters.items() if key not in dimension.required_rate_dimensions}


def _rule_matches_price_dimension(rule: UnitCompatibilityRule, item: PriceDimensionEvidence) -> bool:
    values = {
        "unit": str(item.unit or "").lower(),
        "usage_type": str(item.usage_type or "").lower(),
        "operation": str(item.operation or "").lower(),
        "product_family": str(item.product_family or "").lower(),
    }
    return any(
        any(token in values.get(attribute, "") for token in tokens)
        for attribute, tokens in rule.attribute_contains.items()
    )


def _term_groups_satisfied(terms: set[str], groups: TermGroups) -> bool:
    return all(bool(terms & group) for group in groups)


def _dedupe_filters(filters: list[dict[str, str]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in filters:
        key = (item.get("Type", ""), item.get("Field", ""), item.get("Value", ""))
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _binding_from_dimension(
    dimension: ServiceUsageDimension,
    price: PriceDimensionEvidence,
    *,
    status: str,
    confidence: str,
    notes: list[str],
) -> AwsRateBinding:
    return AwsRateBinding(
        service_name=dimension.service_name,
        aws_service_code=dimension.aws_service_code,
        sku=price.sku,
        usage_type=price.usage_type,
        operation=price.operation,
        product_family=price.product_family,
        rate_code=price.rate_code,
        unit=price.unit,
        begin_range=price.begin_range,
        end_range=price.end_range,
        price_per_unit=Decimal(price.price_per_unit),
        currency=price.currency,
        effective_date=price.effective_date,
        source=price.source,
        confidence=confidence,  # type: ignore[arg-type]
        binding_status=status,  # type: ignore[arg-type]
        notes=notes,
    )


def _dedupe_notes(notes: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in notes:
        clean = str(item).strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        output.append(clean)
    return output
