from __future__ import annotations

from decimal import Decimal
import re
from typing import Any

from app.core.config import get_settings
from app.domain.quality_findings import finding
from app.domain.source_of_truth import (
    AssumptionLedger,
    AssumptionRecord,
    AwsRateBinding,
    CanonicalFact,
    CanonicalFactsLedger,
    PricingDriverBinding,
    PricingLedger,
    PricingLedgerLineItem,
    PricingLedgerSummary,
    ServiceUsageDimension,
)
from app.models.domain import PricingAnalysis
from app.services.aws_rate_binding_engine import AwsRateBindingEngine
from app.services.pricing_driver_closure import build_pricing_driver_closure
from app.services.pricing_driver_selector import PricingDriverFamily
from app.services.pricing_filter_mapper import pricing_filter_plan_for_service
from app.services.pricing_scenario_profiles import scenario_profile
from app.services.use_case_profile import ExtractedMetric, UseCaseProfile


SUPPORTED_FAMILIES = {
    PricingDriverFamily.HEALTHCARE_OPERATIONS_SCHEDULING.value,
    PricingDriverFamily.PAYMENT_FRAUD_SCORING.value,
    PricingDriverFamily.CAPITAL_MARKETS_RISK_ENGINE.value,
    PricingDriverFamily.LIVE_MEDIA_STREAMING.value,
}

_PER_ITEM_UNIT_PATTERN = re.compile(r"(?:\bper\s+|_per_)(?!year\b|month\b|week\b|day\b|hour\b|minute\b|second\b)[a-z][a-z0-9_-]*")
_SECONDS_PER_MONTH = 30 * 24 * 60 * 60
_PEOPLE_UNITS = {
    "resident", "residents", "user", "users", "people", "person", "persons",
    "customer", "customers", "patient", "patients", "viewer", "viewers",
    "employee", "employees", "operator", "operators",
}


class SourceTruthPricingCompiler:
    def compile(self, *, profile: UseCaseProfile, drivers: Any, pricing: PricingAnalysis) -> PricingAnalysis:
        family = str(getattr(drivers, "pricing_driver_family", "generic_directional"))
        if family not in SUPPORTED_FAMILIES:
            return _compile_generic_not_estimated(profile=profile, drivers=drivers, pricing=pricing, family=family)

        facts = _canonical_facts(profile, drivers)
        assumptions = _assumptions(profile, drivers)
        driver_bindings = _driver_bindings(family, facts, assumptions, drivers)
        _assign_assumption_driver_usage(assumptions, driver_bindings)
        usage_dimensions = _usage_dimensions(family, pricing, driver_bindings, assumptions, drivers)
        _assign_assumption_line_usage(assumptions, usage_dimensions)
        rate_bindings = [AwsRateBindingEngine().bind(dimension, region_code=pricing.region) for dimension in usage_dimensions]
        ledger = _pricing_ledger(pricing, usage_dimensions, rate_bindings, assumptions)
        _apply_ledger_totals_to_pricing(pricing, ledger)
        sanity = _sanity_findings(family, facts, driver_bindings, usage_dimensions, ledger, pricing)

        known_fact_names = {fact.name for fact in facts.facts}
        pricing.unknown_variables = [
            item for item in pricing.unknown_variables
            if item not in known_fact_names and item.replace("_target", "") not in known_fact_names
        ]
        if any(item.severity == "critical" for item in sanity):
            pricing.metadata = {
                **pricing.metadata,
                "pricing_can_be_displayed_as_headline": False,
                "headline_display": "Directional placeholder only - not headline-safe.",
            }
        scenario_profile_used = getattr(drivers, "scenario_profile_id", None)
        pricing.metadata = {
            **pricing.metadata,
            "source_truth_pricing_compiler": {
                "enabled": True,
                "workload_family": family,
                "headline_safe": ledger.summary.headline_safe,
                "procurement_ready": ledger.summary.procurement_ready,
            },
            "canonical_facts": facts.model_dump(mode="json"),
            "assumption_ledger": assumptions.model_dump(mode="json"),
            "pricing_driver_bindings": [item.model_dump(mode="json") for item in driver_bindings],
            "service_usage_dimensions": [item.model_dump(mode="json") for item in usage_dimensions],
            "aws_rate_bindings": [item.model_dump(mode="json") for item in rate_bindings],
            "pricing_ledger": ledger.model_dump(mode="json"),
            "pricing_sanity_findings": [item.model_dump(mode="json") for item in sanity],
        }
        _annotate_line_items(pricing, usage_dimensions, ledger, rate_bindings)
        closure = build_pricing_driver_closure(pricing, scenario_profile_used=scenario_profile_used)
        pricing.metadata = {
            **pricing.metadata,
            "pricing_driver_closure": closure.model_dump(mode="json"),
            "pricing_maturity": closure.pricing_maturity,
            "scenario_profile_used": scenario_profile_used,
            "directional_scenario_allowed": closure.directional_scenario_allowed,
            "pricing_can_be_displayed_as_headline": closure.headline_pricing_allowed,
            "headline_display": "Directional scenario estimate - not procurement-ready." if closure.directional_scenario_allowed and not closure.procurement_ready else pricing.metadata.get("headline_display"),
        }
        return pricing


def _canonical_facts(profile: UseCaseProfile, drivers: Any) -> CanonicalFactsLedger:
    facts: list[CanonicalFact] = []
    for metric in profile.metrics:
        facts.append(_fact_from_metric(metric))
    structured = profile.structured_metrics or {}
    for section in ("asset_counts", "business_targets"):
        for name, payload in (structured.get(section) or {}).items():
            if not isinstance(payload, dict) or payload.get("value") is None:
                continue
            if any(fact.name == name for fact in facts):
                continue
            facts.append(CanonicalFact(
                name=name,
                value=payload.get("value"),
                unit=payload.get("unit"),
                source="user_input",
                source_text=payload.get("source_text") or payload.get("raw"),
                confidence="high",
                used_by=["pricing", "architecture", "research"],
                validation_status="confirmed",
            ))
    derived = _derived_facts(drivers)
    for name, value, unit, formula in derived:
        if value in (None, 0) or any(fact.name == name for fact in facts):
            continue
        facts.append(CanonicalFact(
            name=name,
            value=value,
            unit=unit,
            source="derived",
            source_text=None,
            confidence="medium",
            derived_formula=formula,
            used_by=["pricing"],
            validation_status="assumed" if "assumed" in formula.lower() else "confirmed",
        ))
    return CanonicalFactsLedger(facts=facts, missing_explicit_metrics=[])


def _compile_generic_not_estimated(
    *,
    profile: UseCaseProfile,
    drivers: Any,
    pricing: PricingAnalysis,
    family: str,
) -> PricingAnalysis:
    facts = _canonical_facts(profile, drivers)
    generic_context = _generic_quantity_context(facts)
    assumptions = AssumptionLedger(assumptions=[])
    driver_bindings: list[PricingDriverBinding] = [
        PricingDriverBinding(
            driver_name=fact.name,
            value=fact.value,
            source_fact_id=fact.id,
            status="confirmed" if fact.validation_status == "confirmed" else "derived",
            required_for_headline_pricing=False,
        )
        for fact in facts.facts
    ]
    usage_dimensions = [
        _generic_usage_dimension(line.service, line.unit_basis, pricing.region, facts=facts, bindings=driver_bindings)
        for line in pricing.line_items
    ]
    rate_bindings = [_generic_rate_binding(dimension, region_code=pricing.region) for dimension in usage_dimensions]
    ledger = PricingLedger(
        line_items=[
            PricingLedgerLineItem(
                service_name=dimension.service_name,
                usage_name=dimension.usage_name,
                quantity=None,
                quantity_unit=dimension.unit,
                formula=dimension.formula,
                rate_binding_id=rate_bindings[index].id if index < len(rate_bindings) else None,
                unit_price=None,
                monthly_total=None,
                evidence_class="not_estimated",
                procurement_ready=False,
                confidence="low",
                assumptions=[],
                limitations=[
                    "Directional local range exists, but source-truth usage and AWS rate binding are not yet available for this workload family.",
                ],
            )
            for index, dimension in enumerate(usage_dimensions)
        ],
        summary=PricingLedgerSummary(
            sku_tier_backed_subtotal=Decimal("0"),
            pricing_page_or_mcp_backed_subtotal=Decimal("0"),
            heuristic_subtotal=Decimal("0"),
            not_estimated_items=[dimension.service_name for dimension in usage_dimensions],
            headline_safe=False,
            procurement_ready=False,
        ),
    )
    sanity = [
        finding(
            code="pricing.unsupported_family_not_estimated",
            severity="warning",
            category="pricing",
            title="Pricing Family Needs Usage Binding",
            description=(
                "Archway captured workload facts, but this workload family does not yet have a source-truth "
                "pricing formula and exact AWS rate binding. Treat any directional range as a planning placeholder."
            ),
            evidence=["pricing.metadata.source_truth_pricing_compiler.enabled=true"],
            auto_repairable=True,
            repair_strategy="Use the pricing-dimension lane to bind service-specific units, quantities, and AWS rates before showing a headline.",
            customer_readiness_impact="cap_to_directional",
        )
    ]
    for item in generic_context.get("plausibility_findings") or []:
        sanity.append(finding(
            code=str(item.get("code") or "pricing.quantity_implausible"),
            severity="critical" if item.get("severity") == "critical" else "warning",
            category="pricing",
            title="Derived Quantity Needs Review",
            description=str(item.get("message") or "A derived generic pricing quantity failed the plausibility gate."),
            evidence=["pricing.metadata.generic_quantity_context"],
            auto_repairable=True,
            repair_strategy="Drop the affected dimension to not_estimated or collect a more specific typed driver before client presentation.",
            customer_readiness_impact="cap_to_internal_only" if item.get("severity") == "critical" else "cap_to_directional",
        ))
    pricing.metadata = {
        **pricing.metadata,
        "source_truth_pricing_compiler": {
            "enabled": True,
            "workload_family": family,
            "headline_safe": False,
            "procurement_ready": False,
            "mode": "generic_not_estimated",
            "reason": "No source-truth pricing formula is bound for this workload family yet.",
        },
        "canonical_facts": facts.model_dump(mode="json"),
        "assumption_ledger": assumptions.model_dump(mode="json"),
        "pricing_driver_bindings": [item.model_dump(mode="json") for item in driver_bindings],
        "service_usage_dimensions": [item.model_dump(mode="json") for item in usage_dimensions],
        "aws_rate_bindings": [item.model_dump(mode="json") for item in rate_bindings],
        "pricing_ledger": ledger.model_dump(mode="json"),
        "pricing_sanity_findings": [item.model_dump(mode="json") for item in sanity],
        "generic_quantity_context": _export_quantity_context(generic_context),
        "pricing_can_be_displayed_as_headline": False,
        "headline_display": "Pricing withheld from executive headline because exact usage and AWS rate bindings are not available for this workload family.",
    }
    closure = build_pricing_driver_closure(pricing, scenario_profile_used=getattr(drivers, "scenario_profile_id", None))
    pricing.metadata = {
        **pricing.metadata,
        "pricing_driver_closure": closure.model_dump(mode="json"),
        "pricing_maturity": closure.pricing_maturity,
        "scenario_profile_used": getattr(drivers, "scenario_profile_id", None),
        "directional_scenario_allowed": closure.directional_scenario_allowed,
    }
    for line in pricing.line_items:
        line.pricing_trace = {
            **(line.pricing_trace or {}),
            "calculation_source": "generic_not_estimated_source_truth_trace",
            "procurement_ready": False,
            "headline_safe": False,
            "pricing_validity": "not_estimated",
            "reason": "No source-truth usage dimension and AWS rate binding are available for this service/workload family yet.",
        }
    return pricing


def _generic_usage_dimension(
    service_name: str,
    unit_basis: str | None,
    region_code: str | None,
    *,
    facts: CanonicalFactsLedger | None = None,
    bindings: list[PricingDriverBinding] | None = None,
) -> ServiceUsageDimension:
    plan = pricing_filter_plan_for_service(service_name, region_code=region_code or "us-east-1")
    service_code = plan.service_code if plan else "unknown"
    required_rate_dimensions = {
        key: value for key, value in ((plan.filters if plan else {}) or {}).items()
        if key != "regionCode"
    }
    generic = _generic_quantity_context(facts or CanonicalFactsLedger())
    binding_ids = _generic_binding_ids(generic["driver_names"], bindings or [])
    key = _normalized_service(service_name)
    quantity = None
    unit = unit_basis or "usage unit to confirm"
    usage_name = "workload-specific usage not yet bound"
    formula = "No exact quantity formula is bound; confirm workload driver, AWS usage unit, SKU/tier, and region."

    if "kinesis" in key and generic["monthly_events"]:
        quantity = Decimal(str(round(generic["monthly_events"], 4)))
        unit = "requests"
        usage_name = "PUT request payload units for telemetry events"
        formula = (
            generic["event_formula"]
            + " Kinesis Data Streams binding uses PutRequest payload units; confirm payload chunking before procurement."
        )
    elif any(term in key for term in ("eventbridge", "sqs", "iot", "flink", "msk")) and generic["monthly_events"]:
        quantity = Decimal(str(round(generic["monthly_events"], 4)))
        unit = "events/month"
        usage_name = "derived telemetry or workload events"
        formula = generic["event_formula"]
    elif "sagemaker" in key and (generic["ml_inferences"] or generic["monthly_events"]):
        quantity = Decimal(str(round(generic["ml_inferences"] or generic["monthly_events"], 4)))
        unit = "inferences/month"
        usage_name = "derived model scoring requests"
        formula = generic["ml_inference_formula"]
    elif any(term in key for term in ("rekognition", "textract", "bedrock", "comprehend")) and generic["monthly_inferences"]:
        quantity = Decimal(str(round(generic["monthly_inferences"], 4)))
        unit = "inferences/month"
        usage_name = "derived model or extraction requests"
        formula = generic["inference_formula"]
    elif any(term in key for term in ("step_functions", "lambda", "api_gateway")) and generic["monthly_actions"]:
        quantity = Decimal(str(round(generic["monthly_actions"], 4)))
        unit = "requests/month"
        usage_name = "derived workflow/API executions"
        formula = generic["action_formula"]
    elif "s3" in key:
        if generic["storage_gb_month"]:
            quantity = Decimal(str(round(generic["storage_gb_month"], 4)))
            unit = "GB-month"
            usage_name = "derived object/evidence retention"
            formula = generic["storage_formula"]
        elif generic["monthly_events"]:
            quantity = Decimal(str(round(generic["monthly_events"], 4)))
            unit = "records/month"
            usage_name = "derived retained records"
            formula = generic["event_formula"]
    elif "dynamodb" in key:
        if generic["monthly_actions"] or generic["monthly_events"]:
            quantity = Decimal(str(round(generic["monthly_actions"] or generic["monthly_events"], 4)))
            unit = "state records/month"
            usage_name = "derived workflow/state records"
            formula = generic["action_formula"]
    elif any(term in key for term in ("cloudwatch", "cloudtrail", "opensearch")):
        if generic["monthly_events"]:
            quantity = Decimal(str(round(generic["monthly_events"], 4)))
            unit = "records/month"
            usage_name = "derived logs/indexed records"
            formula = generic["event_formula"]
    return ServiceUsageDimension(
        service_name=service_name,
        usage_name=usage_name,
        aws_service_code=service_code,
        quantity=quantity,
        unit=unit,
        formula=formula,
        driver_binding_ids=binding_ids,
        assumption_ids=[],
        required_rate_dimensions=required_rate_dimensions,
    )


def _generic_rate_binding(dimension: ServiceUsageDimension, *, region_code: str) -> AwsRateBinding:
    settings = get_settings()
    live_authority_enabled = bool(
        settings.enable_aws_pricing_mcp
        or settings.aws_pricing_mcp_command
        or settings.aws_pricing_mcp_url
    )
    if live_authority_enabled:
        return AwsRateBindingEngine().bind(dimension, region_code=region_code)
    return AwsRateBinding(
        service_name=dimension.service_name,
        aws_service_code=dimension.aws_service_code,
        unit=dimension.unit,
        source="unbound",
        confidence="none",
        binding_status="unsupported",
        notes=[
            "Live pricing authority is disabled for this run, so generic open-world usage dimensions were not bound to AWS SKU/rate data.",
            "Enable the AWS Pricing MCP or live pricing authority path before using this line for budget or procurement.",
        ],
    )


def _generic_quantity_context(facts: CanonicalFactsLedger) -> dict[str, Any]:
    values: dict[str, float] = {}
    direct_values: dict[str, float] = {}
    names_by_key: dict[str, str] = {}
    for fact in facts.facts:
        try:
            value = float(fact.value)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        name = str(fact.name)
        unit = str(fact.unit or "").lower()
        source = str(fact.source_text or "").lower()
        text = f"{name} {unit} {source}"
        if "aws pricing estimate" in text or "for_initial_aws_pricing_estimates" in text:
            continue
        key = _generic_fact_key(name, unit, source)
        values[key] = max(values.get(key, 0), value)
        names_by_key[key] = name

    annual_base = _first_value(values, "annual_base", "items_per_year", "records_per_year", "transactions_per_year", "requests_per_year")
    monthly_base = _first_value(values, "monthly_base", "items_per_month", "records_per_month", "transactions_per_month", "requests_per_month")
    daily_base = _first_value(values, "events_per_day", "items_per_day", "records_per_day", "transactions_per_day", "requests_per_day")
    if not monthly_base and annual_base:
        monthly_base = annual_base / 12
    if not monthly_base and daily_base:
        monthly_base = daily_base * 30
    per_item = sum(value for key, value in values.items() if key.endswith("_per_item"))
    monthly_direct = sum(value for key, value in values.items() if key.endswith("_per_month"))
    hourly_direct = sum(value for key, value in values.items() if key.endswith("_per_hour"))
    monthly_events = monthly_direct
    if monthly_base:
        monthly_events += monthly_base
        if per_item:
            monthly_events += monthly_base * per_item
    if hourly_direct:
        monthly_events += hourly_direct * 24 * 30

    image_per_item = values.get("images_per_item", 0)
    mb_per_image = values.get("mb_per_image", 0)
    monthly_images = (monthly_base or 0) * image_per_item if image_per_item else values.get("images_per_month", 0)
    monthly_documents = values.get("documents_per_month", 0)
    monthly_notes = values.get("notes_per_month", 0)
    monthly_inferences = monthly_images + monthly_documents + monthly_notes or monthly_events
    monthly_actions = monthly_base or monthly_events
    retention_years = values.get("retention_years", 1)
    storage_gb_month = 0.0
    if monthly_images and mb_per_image:
        storage_gb_month = monthly_images * mb_per_image / 1024 * max(1, retention_years * 12)

    driver_names = [names_by_key[key] for key in values if key in names_by_key]
    return {
        "monthly_events": monthly_events,
        "monthly_inferences": monthly_inferences,
        "monthly_actions": monthly_actions,
        "storage_gb_month": storage_gb_month,
        "driver_names": driver_names,
        "event_formula": "Derived from user-confirmed annual/monthly/daily volume plus per-item and hourly event counts; keep non-headline until service rate binding is exact.",
        "inference_formula": "Derived from user-confirmed image/document/note quantities and annual/monthly workload volume; keep non-headline until model/service unit and rate binding are exact.",
        "action_formula": "Derived from user-confirmed workload volume; keep non-headline until workflow/API unit and rate binding are exact.",
        "storage_formula": "monthly_base_volume * images_per_item * mb_per_image / 1024 * retention_months",
    }


def _generic_quantity_context(facts: CanonicalFactsLedger) -> dict[str, Any]:
    values: dict[str, float] = {}
    direct_values: dict[str, float] = {}
    names_by_key: dict[str, str] = {}
    asset_count = 0.0
    asset_count_candidates: list[tuple[float, str]] = []
    cadence_seconds = 0.0
    telemetry_payload_kb = 0.0
    media_payload_mb = 0.0
    media_per_asset = 0.0
    media_per_base_item = 0.0
    base_items_per_asset_month = 0.0
    media_period_months = 1.0
    retention_months_by_class: dict[str, float] = {}
    text_items_monthly = 0.0
    direct_monthly_events = 0.0
    direct_daily_events = 0.0
    direct_hourly_events = 0.0
    direct_annual_events = 0.0
    derived_monthly_events = 0.0

    for fact in facts.facts:
        try:
            value = float(fact.value)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        name = str(fact.name)
        unit = str(fact.unit or "").lower()
        source = str(fact.source_text or "").lower()
        text = f"{name} {unit} {source}"
        if "aws pricing estimate" in text or "for_initial_aws_pricing_estimates" in text:
            continue
        key = _generic_fact_key(name, unit, source)
        values[key] = max(values.get(key, 0), value)
        names_by_key[key] = name
        if fact.source != "derived":
            direct_values[key] = max(direct_values.get(key, 0), value)

        if _looks_like_asset_count(name, unit, source):
            asset_count_candidates.append((value, f"{name} {unit} {source}"))
        if _looks_like_cadence_seconds(name, unit, source):
            cadence_seconds = min(cadence_seconds or value, value)
        if _looks_like_payload_kb(name, unit, source):
            telemetry_payload_kb = max(telemetry_payload_kb, value)
        if _looks_like_media_payload_mb(name, unit, source):
            media_payload_mb = max(media_payload_mb, value)
        if _looks_like_base_item_rate_per_asset(name, unit, source):
            base_items_per_asset_month = max(base_items_per_asset_month, _quantity_per_month(value, text))
        if _looks_like_media_per_base_item(name, unit, source):
            media_per_base_item = max(media_per_base_item, value)
        if _looks_like_media_per_asset(name, unit, source):
            media_per_asset = max(media_per_asset, value)
            media_period_months = max(media_period_months, _period_months(text))
        retention_class = _retention_class(text)
        if retention_class:
            retention_months_by_class[retention_class] = max(
                retention_months_by_class.get(retention_class, 0),
                _retention_months(value, name=name, unit=unit, source=source),
            )
        if _looks_like_text_items_per_month(name, unit, source):
            text_items_monthly += value
        if fact.source == "derived":
            if key == "monthly_base":
                derived_monthly_events = max(derived_monthly_events, value)
            elif key == "events_per_day":
                derived_monthly_events = max(derived_monthly_events, value * 30)
            elif key == "annual_base":
                derived_monthly_events = max(derived_monthly_events, value / 12)
        else:
            if key == "annual_base":
                direct_annual_events = max(direct_annual_events, value)
            elif key == "monthly_base":
                direct_monthly_events += value
            elif key == "events_per_day":
                direct_daily_events += value
            elif key.endswith("_per_hour"):
                direct_hourly_events += value

    asset_count = _compose_asset_count(asset_count_candidates)
    annual_base = _first_value(direct_values, "annual_base", "items_per_year", "records_per_year", "transactions_per_year", "requests_per_year")
    monthly_base = _first_value(direct_values, "monthly_base", "items_per_month", "records_per_month", "transactions_per_month", "requests_per_month")
    daily_base = _first_value(direct_values, "events_per_day", "items_per_day", "records_per_day", "transactions_per_day", "requests_per_day")
    if not monthly_base and annual_base:
        monthly_base = annual_base / 12
    if not monthly_base and daily_base:
        monthly_base = daily_base * 30
    if media_per_asset and not media_payload_mb:
        media_payload_mb = values.get("mb_per_image", 0)

    telemetry_monthly = asset_count * (_SECONDS_PER_MONTH / cadence_seconds) if asset_count and cadence_seconds else 0.0
    direct_event_monthly = max(
        direct_monthly_events,
        direct_daily_events * 30,
        direct_hourly_events * 24 * 30,
        direct_annual_events / 12 if direct_annual_events else 0,
        monthly_base,
    )
    monthly_events = max(telemetry_monthly, direct_event_monthly, derived_monthly_events)

    media_base = asset_count or monthly_base
    if media_per_base_item and base_items_per_asset_month and asset_count:
        monthly_media_items = asset_count * base_items_per_asset_month * media_per_base_item
    elif media_per_asset and media_base:
        monthly_media_items = media_base * media_per_asset / max(1, media_period_months)
    elif media_payload_mb and direct_event_monthly:
        monthly_media_items = direct_event_monthly
    else:
        monthly_media_items = values.get("images_per_month", 0)
    monthly_documents = values.get("documents_per_month", 0)
    monthly_notes = values.get("notes_per_month", 0) + text_items_monthly
    monthly_inferences = monthly_media_items + monthly_documents + monthly_notes
    ml_inferences = monthly_events or monthly_inferences
    monthly_actions = monthly_events or monthly_base or monthly_inferences

    retention_default = max(retention_months_by_class.values() or [12])
    telemetry_retention = retention_months_by_class.get("telemetry", retention_default)
    media_retention = retention_months_by_class.get("media", retention_default)
    evidence_retention = retention_months_by_class.get("evidence", retention_default)
    storage_by_class: dict[str, float] = {}
    if monthly_events and telemetry_payload_kb:
        storage_by_class["telemetry"] = monthly_events * telemetry_payload_kb / (1024 * 1024) * max(1, telemetry_retention)
    if monthly_media_items and media_payload_mb:
        storage_by_class["media"] = monthly_media_items * media_payload_mb / 1024 * max(1, media_retention)
    if monthly_documents or monthly_notes:
        storage_by_class["evidence"] = (monthly_documents + monthly_notes) * 0.05 / 1024 * max(1, evidence_retention)
    storage_gb_month = sum(storage_by_class.values())
    plausibility_findings = _quantity_plausibility_findings(
        asset_count=asset_count,
        cadence_seconds=cadence_seconds,
        monthly_events=monthly_events,
        monthly_media_items=monthly_media_items,
        storage_gb_month=storage_gb_month,
    )

    driver_names = [names_by_key[key] for key in values if key in names_by_key]
    return {
        "monthly_events": monthly_events,
        "monthly_inferences": monthly_inferences,
        "ml_inferences": ml_inferences,
        "monthly_actions": monthly_actions,
        "monthly_media_items": monthly_media_items,
        "asset_count": asset_count,
        "cadence_seconds": cadence_seconds,
        "telemetry_payload_kb": telemetry_payload_kb,
        "media_payload_mb": media_payload_mb,
        "media_per_asset": media_per_asset,
        "media_per_base_item": media_per_base_item,
        "base_items_per_asset_month": base_items_per_asset_month,
        "media_period_months": media_period_months,
        "storage_gb_month_by_class": storage_by_class,
        "storage_gb_month": storage_gb_month,
        "plausibility_findings": plausibility_findings,
        "driver_names": driver_names,
        "event_formula": "Derived from typed workload streams; telemetry uses asset_count * seconds_per_month / cadence_seconds, while direct annual/monthly/daily volumes stay separate.",
        "inference_formula": "Derived from typed media/document/note streams; per-asset media uses asset_count * per_asset_multiplier / period_in_months.",
        "ml_inference_formula": "Derived from the selected scoring stream; telemetry scoring uses monthly telemetry events unless a narrower scoring-window driver is confirmed.",
        "action_formula": "Derived from typed workload events or workflow action counts; keep non-headline until workflow/API unit and rate binding is exact.",
        "storage_formula": "Sum per data class: item_count * normalized_payload_size * retention_months, converted to GB-month.",
    }


def _generic_fact_key(name: str, unit: str, source: str) -> str:
    text = f"{name} {unit} {source}".lower()
    if any(term in text for term in ("retention", "retain", "years")) and "year" in text:
        return "retention_years"
    if any(term in text for term in ("mb per image", "mb_each", "mb each", "mb_per_image")):
        return "mb_per_image"
    has_open_ended_per_item_unit = bool(_PER_ITEM_UNIT_PATTERN.search(text))
    if any(term in text for term in ("image", "photo", "video", "scan")) and has_open_ended_per_item_unit:
        return "images_per_item"
    if any(term in text for term in ("reading", "event", "scan")) and has_open_ended_per_item_unit:
        return f"{name}_per_item"
    if any(term in text for term in ("document", "pdf", "contract", "record")) and any(term in text for term in ("per month", "_per_month", "monthly")):
        return "documents_per_month"
    if any(term in text for term in ("note", "text")) and any(term in text for term in ("per month", "_per_month", "monthly")):
        return "notes_per_month"
    if any(term in text for term in ("image", "photo", "video")) and any(term in text for term in ("per month", "_per_month", "monthly")):
        return "images_per_month"
    if any(term in text for term in ("per hour", "_per_hour", "hourly")):
        return f"{name}_per_hour"
    if any(term in text for term in ("per year", "_per_year", "yearly", "annual")):
        return "annual_base"
    if any(term in text for term in ("per day", "_per_day", "daily")):
        return "events_per_day"
    if any(term in text for term in ("per month", "_per_month", "monthly")):
        return "monthly_base"
    return name


def _looks_like_asset_count(name: str, unit: str, source: str) -> bool:
    text = f"{name} {unit} {source}".lower()
    if any(term in text for term in ("per_", " per ", "second", "minute", "hour", "day", "month", "year", "kb", "mb", "gb", "tb", "percent", "retention", "retain")):
        return False
    if any(term in text for term in _PEOPLE_UNITS):
        return False
    if any(term in text for term in ("asset", "assets", "device", "devices", "site", "sites", "facility", "facilities")):
        return True
    unit_tokens = set(re.findall(r"[a-z]+", unit))
    return bool(unit_tokens) and not unit_tokens.intersection(_PEOPLE_UNITS)


def _compose_asset_count(candidates: list[tuple[float, str]]) -> float:
    if not candidates:
        return 0.0
    largest = max(value for value, _text in candidates)
    other_sum = sum(value for value, _text in candidates if value != largest)
    aggregate_markers = ("total", "overall", "monitored", "sources", "assets", "devices")
    has_aggregate = any(
        value == largest and any(marker in text for marker in aggregate_markers)
        for value, text in candidates
    )
    if has_aggregate:
        return largest
    return sum(value for value, _text in candidates)


def _looks_like_cadence_seconds(name: str, unit: str, source: str) -> bool:
    text = f"{name} {unit} {source}".lower()
    return ("second" in text or re.search(r"\bevery\s+\d+(?:\.\d+)?\s*s\b", text)) and not any(term in text for term in ("retention", "retain"))


def _looks_like_payload_kb(name: str, unit: str, source: str) -> bool:
    text = f"{name} {unit} {source}".lower()
    return ("kb" in text and any(term in text for term in ("event", "reading", "sensor", "telemetry", "payload", "message", "update", "record"))) or "payload_kb" in text


def _looks_like_media_payload_mb(name: str, unit: str, source: str) -> bool:
    text = f"{name} {unit} {source}".lower()
    return "mb" in text and (
        any(term in text for term in ("image", "photo", "video", "scan", "clip", "media", "thermal"))
        or "mb_each" in text
        or "mb each" in text
    )


def _looks_like_media_per_asset(name: str, unit: str, source: str) -> bool:
    text = f"{name} {unit} {source}".lower()
    if any(term in text for term in ("kb", "mb", "gb", "tb", "payload", "size", "each")):
        return False
    if _looks_like_media_per_base_item(name, unit, source):
        return False
    return bool(_PER_ITEM_UNIT_PATTERN.search(text)) and any(term in text for term in ("image", "photo", "video", "scan", "clip", "media", "thermal"))


def _looks_like_media_per_base_item(name: str, unit: str, source: str) -> bool:
    text = f"{name} {unit} {source}".lower()
    if any(term in text for term in ("kb", "mb", "gb", "tb", "payload", "size", "each")):
        return False
    return bool(_PER_ITEM_UNIT_PATTERN.search(text)) and any(term in text for term in ("image", "photo", "video", "scan", "clip", "media", "thermal")) and "batch" in text


def _looks_like_base_item_rate_per_asset(name: str, unit: str, source: str) -> bool:
    text = f"{name} {unit} {source}".lower()
    if any(term in text for term in ("kb", "mb", "gb", "tb", "payload", "size")):
        return False
    return bool(_PER_ITEM_UNIT_PATTERN.search(text)) and any(term in text for term in ("batch", "batches"))


def _looks_like_text_items_per_month(name: str, unit: str, source: str) -> bool:
    text = f"{name} {unit} {source}".lower()
    return any(term in text for term in ("note", "notes", "summary", "summaries")) and any(term in text for term in ("per month", "_per_month", "monthly"))


def _period_months(text: str) -> float:
    if any(term in text for term in ("quarter", "quarterly", "per_qtr", "per_quarter")):
        return 3.0
    if any(term in text for term in ("year", "annual", "yearly")):
        return 12.0
    if any(term in text for term in ("week", "weekly")):
        return 0.25
    if any(term in text for term in ("day", "daily")):
        return 1 / 30
    return 1.0


def _quantity_per_month(value: float, text: str) -> float:
    period = _period_months(text)
    if period < 1:
        return value * 30
    if period > 1:
        return value / period
    if text.rstrip().endswith(("_per", " per")):
        return value * 30
    return value


def _retention_class(text: str) -> str | None:
    if not any(term in text for term in ("retain", "retention", "hot for", "archive", "stored")):
        return None
    if any(term in text for term in ("image", "photo", "video", "scan", "clip", "media", "thermal")):
        return "media"
    if any(term in text for term in ("evidence", "summary", "summaries", "note", "document")):
        return "evidence"
    if any(term in text for term in ("raw", "sensor", "telemetry", "event", "reading")):
        return "telemetry"
    return "all"


def _retention_months(value: float, *, name: str, unit: str, source: str) -> float:
    unit_text = f"{name} {unit}".lower()
    text = f"{unit_text} {source}".lower()
    if "day" in unit_text:
        return max(1, value / 30)
    if "week" in unit_text:
        return max(1, value / 4)
    if "month" in unit_text:
        return value
    if "year" in unit_text:
        return value * 12
    if re.search(rf"\b{re.escape(str(int(value)) if value.is_integer() else str(value))}\s+days?\b", text):
        return max(1, value / 30)
    if re.search(rf"\b{re.escape(str(int(value)) if value.is_integer() else str(value))}\s+weeks?\b", text):
        return max(1, value / 4)
    if re.search(rf"\b{re.escape(str(int(value)) if value.is_integer() else str(value))}\s+months?\b", text):
        return value
    if re.search(rf"\b{re.escape(str(int(value)) if value.is_integer() else str(value))}\s+years?\b", text):
        return value * 12
    return value


def _quantity_plausibility_findings(
    *,
    asset_count: float,
    cadence_seconds: float,
    monthly_events: float,
    monthly_media_items: float,
    storage_gb_month: float,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if asset_count and cadence_seconds:
        max_events = asset_count * (_SECONDS_PER_MONTH / max(cadence_seconds, 1))
        if monthly_events > max_events * 1.05:
            findings.append({
                "code": "quantity.events_exceed_asset_cadence_bound",
                "severity": "critical",
                "message": "Derived monthly events exceed the asset-count and cadence bound.",
            })
    if asset_count and storage_gb_month / max(asset_count, 1) > 100_000:
        findings.append({
            "code": "quantity.storage_per_asset_implausible",
            "severity": "critical",
            "message": "Derived storage implies more than 100 TB-month per asset.",
        })
    elif asset_count and storage_gb_month / max(asset_count, 1) > 10_000:
        findings.append({
            "code": "quantity.storage_per_asset_high",
            "severity": "warning",
            "message": "Derived storage implies more than 10 TB-month per asset; keep non-headline until confirmed.",
        })
    if monthly_media_items and monthly_events and monthly_media_items > monthly_events * 10:
        findings.append({
            "code": "quantity.media_volume_exceeds_event_stream",
            "severity": "warning",
            "message": "Media item volume is unexpectedly larger than the primary event stream.",
        })
    return findings


def _export_quantity_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in context.items()
        if key not in {"driver_names"}
    }


def _first_value(values: dict[str, float], *keys: str) -> float:
    for key in keys:
        if values.get(key):
            return values[key]
    return 0.0


def _generic_binding_ids(driver_names: list[str], bindings: list[PricingDriverBinding]) -> list[str]:
    names = set(driver_names)
    return [binding.id for binding in bindings if binding.driver_name in names]


def _fact_from_metric(metric: ExtractedMetric) -> CanonicalFact:
    return CanonicalFact(
        name=metric.label,
        value=metric.value,
        unit=metric.unit,
        source="user_input",
        source_text=metric.raw,
        confidence="high",
        used_by=["pricing", "architecture", "research"],
        validation_status="confirmed",
    )


def _derived_facts(drivers: Any) -> list[tuple[str, Any, str | None, str]]:
    return [
        ("monthly_event_volume", getattr(drivers, "monthly_event_volume", 0), "events/month", "daily_event_volume * 30"),
        ("scoring_events_per_day", getattr(drivers, "inference_events_per_day", 0), "events/day", "derived from workload scoring strategy"),
        ("active_or_count_poc", getattr(drivers, "active_or_count_poc", 0), "active ORs", "bounded POC scope, not full enterprise operating_room_count"),
        ("recommendation_runs_per_day", getattr(drivers, "recommendation_runs_per_day", 0), "runs/day", "active_or_count_poc * operating_hours_per_day * 60 / refresh_cadence_minutes"),
        ("approval_workflow_executions_per_day", getattr(drivers, "approval_workflow_executions_per_day", 0), "executions/day", "assumed from scheduled_surgeries_per_day until measured"),
        ("ehr_writeback_attempts_per_day", getattr(drivers, "ehr_writeback_attempts_per_day", 0), "attempts/day", "assumed approved writeback attempts"),
        ("occupancy_readiness_events_per_day", getattr(drivers, "occupancy_readiness_events_per_day", 0), "events/day", "derived OR readiness and occupancy metadata event rate"),
        ("audit_retention_months", getattr(drivers, "cold_retention_months", 0), "months", "audit_retention_years * 12"),
        ("risk_compute_jobs_per_day", getattr(drivers, "risk_compute_jobs_per_day", 0), "jobs/day", "risk windows per day"),
        ("hpc_compute_hours_per_month", getattr(drivers, "hpc_compute_hours_per_month", 0), "node-hours/month", "assumed risk_grid_nodes * risk_jobs * runtime"),
        ("cdn_egress_gb_per_day", getattr(drivers, "market_data_ingest_gb_per_day", 0), "GB/day", "viewer_hours * assumed bitrate * seconds / 8 / 1024"),
        ("ad_decision_requests_per_day", getattr(drivers, "integration_api_calls_per_day", 0), "requests/day", "assumed ad decisions per viewer where ad workflow is enabled"),
    ]


def _assumptions(profile: UseCaseProfile, drivers: Any) -> AssumptionLedger:
    family = getattr(drivers, "pricing_driver_family", "generic_directional")
    records: list[AssumptionRecord] = []
    if family == PricingDriverFamily.LIVE_MEDIA_STREAMING.value:
        selected_profile = scenario_profile(getattr(drivers, "scenario_profile_id", "") or "")
        if selected_profile:
            for assumption in selected_profile.assumptions:
                records.append(AssumptionRecord(
                    statement=assumption.statement,
                    value=assumption.value,
                    unit=assumption.unit,
                    source="scenario_profile",
                    reason="The user selected a scenario profile to produce a transparent directional estimate.",
                    impact_areas=["pricing"],
                    confidence=assumption.confidence,
                    validation_method=assumption.validation_method,
                    if_wrong="Scenario-based pricing can be materially over- or under-estimated; replace with measured media traffic and event-plan data before budgeting.",
                    impacted_pricing_drivers=[assumption.driver_name],
                ))
        else:
            records.extend([
                AssumptionRecord(statement="Average bitrate is assumed until the stream ladder is confirmed.", value=round(getattr(drivers, "payload_kb", 0) / 125, 2), unit="Mbps", reason="CDN egress and origin traffic depend on delivered bitrate.", impact_areas=["pricing", "performance"], confidence="low", validation_method="Confirm encoding ladder and measured average bitrate from media engineering.", if_wrong="CloudFront, origin, logging, and storage costs can be materially over- or under-estimated.", impacted_pricing_drivers=["average_bitrate_mbps"]),
                AssumptionRecord(statement="Average viewer engagement is assumed at three viewer-hours per peak concurrent viewer per day.", value=getattr(drivers, "average_viewer_hours_per_month", 0), unit="viewer-hours/month", reason="Input gives peak concurrency but not viewing duration.", impact_areas=["pricing"], confidence="low", validation_method="Use traffic forecasts or historical event analytics.", if_wrong="CDN egress and request costs scale linearly with viewer-hours.", impacted_pricing_drivers=["average_viewer_hours_per_month"]),
                AssumptionRecord(statement="Regional egress mix and CDN cache-hit ratio are not confirmed.", value=getattr(drivers, "region_traffic_mix", None), unit=None, reason="AWS CDN pricing depends on geography and transfer tier.", impact_areas=["pricing"], confidence="low", validation_method="Confirm countries, traffic mix, cache behavior, and price class.", if_wrong="Headline pricing may be misleading; keep estimate directional.", impacted_pricing_drivers=["region_traffic_mix", "cdn_cache_hit_ratio"]),
                AssumptionRecord(statement="One live channel is assumed for the baseline MediaLive estimate.", value=getattr(drivers, "live_channel_count", 1), unit="channel", reason="The input did not specify simultaneous live channel count.", impact_areas=["pricing"], confidence="low", validation_method="Confirm simultaneous live event/channel count and channel class/profile.", if_wrong="MediaLive cost scales approximately linearly with live channel count.", impacted_pricing_drivers=["live_channel_count"]),
                AssumptionRecord(statement="Continuous monthly live event duration is assumed at 720 channel-hours for baseline pricing.", value=getattr(drivers, "event_hours_per_month", 720), unit="hours/month", reason="The input did not specify live event hours per month.", impact_areas=["pricing"], confidence="low", validation_method="Confirm event schedule and channel runtime.", if_wrong="MediaLive and origin costs scale with event hours.", impacted_pricing_drivers=["event_hours_per_month"]),
            ])
    elif family == PricingDriverFamily.PAYMENT_FRAUD_SCORING.value:
        records.extend([
            AssumptionRecord(statement="Analyst review rate is assumed until measured fraud queue rates are supplied.", value=getattr(drivers, "candidate_anomalies_per_day", 0), unit="cases/day", reason="The use case states analyst review but not review percentage.", impact_areas=["pricing", "operations"], confidence="medium", validation_method="Measure historical fraud queue and false-positive rates.", if_wrong="Workflow, queue, notification, and staffing integration costs may be materially wrong."),
            AssumptionRecord(statement="Feature reads and writes per transaction are assumed from the scoring path.", value=None, unit=None, reason="The input gives transaction volume and latency but not feature access shape.", impact_areas=["pricing", "performance"], confidence="medium", validation_method="Confirm feature count, cache hit ratio, and state-store read/write pattern.", if_wrong="DynamoDB/cache and feature processing cost can be under-estimated."),
        ])
    elif family == PricingDriverFamily.CAPITAL_MARKETS_RISK_ENGINE.value:
        records.extend([
            AssumptionRecord(statement="Risk-grid node count and node-hours are assumed until Monte Carlo paths and runtime are confirmed.", value=getattr(drivers, "hpc_compute_hours_per_month", 0), unit="node-hours/month", reason="Positions and Greeks cadence are known, but simulation runtime profile is not.", impact_areas=["pricing", "performance"], confidence="low", validation_method="Benchmark path count, model runtime, node type, and parallelism during POC.", if_wrong="AWS Batch/EC2/HPC costs may change by orders of magnitude."),
            AssumptionRecord(statement="Market data ingest is assumed per exchange/feed.", value=getattr(drivers, "market_data_ingest_gb_per_day", 0), unit="GB/day", reason="Exchange count is known but feed payload shape is not.", impact_areas=["pricing"], confidence="low", validation_method="Confirm feed protocols, normalized record size, and replay volume.", if_wrong="MSK/Kinesis, storage, and network costs may be materially wrong."),
        ])
    elif family == PricingDriverFamily.HEALTHCARE_OPERATIONS_SCHEDULING.value:
        records.extend([
            AssumptionRecord(statement="POC active OR count is bounded separately from enterprise operating room count.", value=getattr(drivers, "active_or_count_poc", 0), unit="active ORs", reason="POC pricing should not use the full enterprise OR estate unless the release scope says so.", impact_areas=["pricing"], confidence="medium", validation_method="Confirm first-release hospital, service line, and active OR count.", if_wrong="POC estimate may be overstated or understated.", impacted_pricing_drivers=["active_or_count_poc"]),
            AssumptionRecord(statement="Operating hours per active OR are assumed for recommendation volume.", value=12, unit="hours/day", reason="The input gives refresh cadence but not the daily active operating window.", impact_areas=["pricing", "performance"], confidence="medium", validation_method="Confirm OR operational hours and after-hours scheduling policy.", if_wrong="Prediction, logs, and workflow volumes scale with active operating window.", impacted_pricing_drivers=["recommendation_runs_per_day"]),
            AssumptionRecord(statement="Approval and EHR writeback rates are assumed from scheduled surgery volume.", value=getattr(drivers, "approval_workflow_executions_per_day", 0), unit="workflows/day", reason="The input requires approval but does not quantify schedule-change acceptance/writeback volume.", impact_areas=["pricing", "compliance", "operations"], confidence="low", validation_method="Measure recommendation acceptance, override, and approved writeback rates during POC.", if_wrong="Step Functions, Lambda, audit, and external integration costs may be materially wrong.", impacted_pricing_drivers=["approval_workflow_executions_per_day", "ehr_writeback_attempts_per_day"]),
        ])
    return AssumptionLedger(assumptions=records)


def _driver_bindings(family: str, facts: CanonicalFactsLedger, assumptions: AssumptionLedger, drivers: Any) -> list[PricingDriverBinding]:
    required = {
        PricingDriverFamily.PAYMENT_FRAUD_SCORING.value: [
            "transactions_per_day", "average_tps", "peak_tps", "latency_target_ms", "scoring_events_per_day",
            "feature_reads_per_transaction", "feature_writes_per_transaction", "analyst_review_rate_percent",
            "auto_block_rate_percent", "audit_payload_kb", "audit_retention_years",
        ],
        PricingDriverFamily.CAPITAL_MARKETS_RISK_ENGINE.value: [
            "open_positions", "exchange_count", "greeks_recalculation_seconds", "risk_runs_per_day",
            "monte_carlo_paths", "portfolio_count", "hpc_compute_node_hours_per_day", "low_latency_cache_gb",
            "shared_storage_tb", "market_data_gb_per_day", "audit_retention_years",
        ],
        PricingDriverFamily.LIVE_MEDIA_STREAMING.value: [
            "concurrent_viewers", "average_viewer_hours_per_month", "average_bitrate_mbps", "region_traffic_mix",
            "cdn_cache_hit_ratio", "live_channel_count", "event_hours_per_month", "drm_license_requests_per_month",
            "ad_decision_requests_per_month", "edge_function_invocations_per_month", "origin_request_count_per_month",
            "archive_storage_gb_month",
        ],
        PricingDriverFamily.HEALTHCARE_OPERATIONS_SCHEDULING.value: [
            "hospital_count", "operating_room_count", "active_or_count_poc", "scheduled_surgeries_per_day",
            "refresh_cadence_minutes", "recommendation_runs_per_day", "approval_workflow_executions_per_day",
            "ehr_writeback_attempts_per_day", "occupancy_readiness_events_per_day", "audit_retention_months",
            "active_coordinator_users",
        ],
    }[family]
    values = _driver_value_map(family, drivers)
    fact_by_name = {fact.name: fact for fact in facts.facts}
    assumptions_by_driver = _assumption_ids_by_driver(assumptions)
    confirmed_overrides = set((getattr(drivers, "pricing_driver_overrides", {}) or {}).get("confirmed_driver_names") or [])
    bindings: list[PricingDriverBinding] = []
    for name in required:
        value = values.get(name)
        fact = fact_by_name.get(name) or fact_by_name.get(_fact_alias(name))
        if fact is not None:
            value = fact.value
        status = "confirmed" if fact or (name in confirmed_overrides and value not in (None, 0, "")) else "derived" if value not in (None, 0, "") else "missing"
        assumption_id = None
        if status == "derived" and name in _assumed_core_driver_names():
            status = "assumed"
            assumption_id = (assumptions_by_driver.get(name) or [None])[0]
        if status == "missing" and name in {"live_channel_count", "event_hours_per_month"}:
            assumption_id = (assumptions_by_driver.get(name) or [None])[0]
            if assumption_id:
                status = "assumed"
                value = 1 if name == "live_channel_count" else 720
        bindings.append(PricingDriverBinding(
            driver_name=name,
            value=value,
            source_fact_id=fact.id if fact else None,
            assumption_id=assumption_id,
            status=status,
            required_for_headline_pricing=name in _core_driver_names(family),
        ))
    return bindings


def _driver_value_map(family: str, drivers: Any) -> dict[str, Any]:
    if family == PricingDriverFamily.PAYMENT_FRAUD_SCORING.value:
        return {
            "transactions_per_day": drivers.daily_event_volume,
            "average_tps": round(drivers.daily_event_volume / 86400, 2),
            "peak_tps": round(drivers.daily_event_volume / 86400 * 5, 2),
            "latency_target_ms": drivers.telemetry_frequency_seconds * 1000,
            "scoring_events_per_day": drivers.inference_events_per_day,
            "analyst_review_rate_percent": round(drivers.candidate_anomalies_per_day / max(1, drivers.daily_event_volume) * 100, 4),
            "auto_block_rate_percent": round(drivers.confirmed_incidents_per_day / max(1, drivers.daily_event_volume) * 100, 4),
            "audit_retention_years": drivers.cold_retention_months // 12,
        }
    if family == PricingDriverFamily.CAPITAL_MARKETS_RISK_ENGINE.value:
        return {
            "open_positions": drivers.positions_count,
            "exchange_count": drivers.exchange_count,
            "greeks_recalculation_seconds": drivers.telemetry_frequency_seconds,
            "risk_runs_per_day": drivers.risk_compute_jobs_per_day,
            "hpc_compute_node_hours_per_day": round(drivers.hpc_compute_hours_per_month / 30, 2),
            "market_data_gb_per_day": drivers.market_data_ingest_gb_per_day,
            "audit_retention_years": drivers.cold_retention_months // 12,
        }
    if family == PricingDriverFamily.HEALTHCARE_OPERATIONS_SCHEDULING.value:
        return {
            "hospital_count": drivers.hospital_count,
            "operating_room_count": drivers.operating_room_count,
            "active_or_count_poc": drivers.active_or_count_poc,
            "scheduled_surgeries_per_day": drivers.scheduled_surgeries_per_day,
            "refresh_cadence_minutes": drivers.refresh_cadence_minutes,
            "recommendation_runs_per_day": drivers.recommendation_runs_per_day,
            "approval_workflow_executions_per_day": drivers.approval_workflow_executions_per_day,
            "ehr_writeback_attempts_per_day": drivers.ehr_writeback_attempts_per_day,
            "occupancy_readiness_events_per_day": drivers.occupancy_readiness_events_per_day,
            "audit_retention_months": drivers.cold_retention_months,
            "active_coordinator_users": drivers.active_coordinator_users,
        }
    return {
        "concurrent_viewers": drivers.asset_count,
        "average_viewer_hours_per_month": drivers.average_viewer_hours_per_month,
        "average_bitrate_mbps": drivers.average_bitrate_mbps or round(drivers.payload_kb / 125, 2),
        "region_traffic_mix": drivers.region_traffic_mix,
        "cdn_cache_hit_ratio": drivers.cdn_cache_hit_ratio,
        "live_channel_count": drivers.live_channel_count,
        "event_hours_per_month": drivers.event_hours_per_month,
        "drm_license_requests_per_month": drivers.drm_license_requests_per_month,
        "ad_decision_requests_per_month": drivers.ad_decision_requests_per_month,
        "edge_function_invocations_per_month": drivers.edge_function_invocations_per_month,
        "origin_request_count_per_month": drivers.origin_request_count_per_month,
        "archive_storage_gb_month": drivers.archive_storage_gb_month,
    }


def _usage_dimensions(family: str, pricing: PricingAnalysis, bindings: list[PricingDriverBinding], assumptions: AssumptionLedger, drivers: Any) -> list[ServiceUsageDimension]:
    by_name = {binding.driver_name: binding for binding in bindings}
    assumption_ids = [item.id for item in assumptions.assumptions]
    output: list[ServiceUsageDimension] = []
    for line in pricing.line_items:
        plan = pricing_filter_plan_for_service(line.service, region_code=pricing.region)
        service_code = plan.service_code if plan else "unknown"
        key = _normalized_service(line.service)
        if family == PricingDriverFamily.LIVE_MEDIA_STREAMING.value:
            output.append(_media_usage_dimension(line.service, key, service_code, by_name, assumption_ids, drivers))
        elif family == PricingDriverFamily.PAYMENT_FRAUD_SCORING.value:
            output.append(_fraud_usage_dimension(line.service, key, service_code, by_name, assumption_ids, drivers))
        elif family == PricingDriverFamily.HEALTHCARE_OPERATIONS_SCHEDULING.value:
            output.append(_healthcare_usage_dimension(line.service, key, service_code, by_name, assumption_ids, drivers))
        else:
            output.append(_risk_usage_dimension(line.service, key, service_code, by_name, assumption_ids, drivers))
    return output


def _healthcare_usage_dimension(service: str, key: str, service_code: str, by_name: dict[str, PricingDriverBinding], assumption_ids: list[str], drivers: Any) -> ServiceUsageDimension:
    if "sagemaker" in key or "bedrock" in key:
        return ServiceUsageDimension(service_name=service, usage_name="OR recommendation runs", aws_service_code=service_code, quantity=Decimal(str(drivers.recommendation_runs_per_day * 30)), unit="runs/month", formula="active_or_count_poc * operating_hours_per_day * 60 / refresh_cadence_minutes * 30", driver_binding_ids=_ids(by_name, "active_or_count_poc", "refresh_cadence_minutes", "recommendation_runs_per_day"), assumption_ids=_assumptions_for_drivers(by_name, "active_or_count_poc", "recommendation_runs_per_day"))
    if "eventbridge" in key or "kinesis" in key or "flink" in key:
        return ServiceUsageDimension(service_name=service, usage_name="OR readiness and occupancy events", aws_service_code=service_code, quantity=Decimal(str(drivers.occupancy_readiness_events_per_day * 30)), unit="events/month", formula="occupancy_readiness_events_per_day * 30", driver_binding_ids=_ids(by_name, "occupancy_readiness_events_per_day"), assumption_ids=_assumptions_for_drivers(by_name, "occupancy_readiness_events_per_day"))
    if "step_functions" in key:
        return ServiceUsageDimension(service_name=service, usage_name="approval workflow executions", aws_service_code=service_code, quantity=Decimal(str(drivers.approval_workflow_executions_per_day * 30)), unit="executions/month", formula="approval_workflow_executions_per_day * 30", driver_binding_ids=_ids(by_name, "approval_workflow_executions_per_day"), assumption_ids=_assumptions_for_drivers(by_name, "approval_workflow_executions_per_day"))
    if "lambda" in key:
        return ServiceUsageDimension(service_name=service, usage_name="approved EHR writeback attempts", aws_service_code=service_code, quantity=Decimal(str(drivers.ehr_writeback_attempts_per_day * 30)), unit="requests/month", formula="ehr_writeback_attempts_per_day * 30", driver_binding_ids=_ids(by_name, "ehr_writeback_attempts_per_day"), assumption_ids=_assumptions_for_drivers(by_name, "ehr_writeback_attempts_per_day"))
    if "dynamodb" in key:
        return ServiceUsageDimension(service_name=service, usage_name="PHI-safe OR state operations", aws_service_code=service_code, quantity=Decimal(str((drivers.occupancy_readiness_events_per_day + drivers.recommendation_runs_per_day) * 30)), unit="read/write units proxy", formula="(occupancy_readiness_events_per_day + recommendation_runs_per_day) * 30", driver_binding_ids=_ids(by_name, "occupancy_readiness_events_per_day", "recommendation_runs_per_day"), assumption_ids=_assumptions_for_drivers(by_name, "recommendation_runs_per_day"))
    if "cloudwatch" in key or "cloudtrail" in key or "s3" in key:
        return ServiceUsageDimension(service_name=service, usage_name="audit/log/evidence retention", aws_service_code=service_code, quantity=Decimal(str(max(1, drivers.monthly_event_volume * drivers.payload_kb / 1024 / 1024))), unit="GB-month proxy", formula="monthly_event_volume * payload_kb / 1024 / 1024", driver_binding_ids=_ids(by_name, "occupancy_readiness_events_per_day", "audit_retention_months"), assumption_ids=assumption_ids)
    if "cognito" in key or "api_gateway" in key:
        return ServiceUsageDimension(service_name=service, usage_name="active coordinator usage", aws_service_code=service_code, quantity=Decimal(str(drivers.active_coordinator_users)), unit="users", formula="active_coordinator_users", driver_binding_ids=_ids(by_name, "active_coordinator_users"), assumption_ids=assumption_ids)
    return ServiceUsageDimension(service_name=service, usage_name="healthcare integration usage", aws_service_code=service_code, quantity=None, unit="varies", formula="No exact healthcare integration quantity was bound for this service.", assumption_ids=assumption_ids)


def _media_usage_dimension(service: str, key: str, service_code: str, by_name: dict[str, PricingDriverBinding], assumption_ids: list[str], drivers: Any) -> ServiceUsageDimension:
    if "cloudfront" in key and "function" not in key:
        qty = Decimal(str(round(drivers.market_data_ingest_gb_per_day * 30, 2)))
        return ServiceUsageDimension(service_name=service, usage_name="CDN data transfer out", aws_service_code=service_code, quantity=qty, unit="GB", formula="concurrent_viewers * average_viewer_hours_per_month * average_bitrate_mbps * 3600 / 8 / 1024", driver_binding_ids=_ids(by_name, "concurrent_viewers", "average_viewer_hours_per_month", "average_bitrate_mbps", "region_traffic_mix"), assumption_ids=_assumptions_for_drivers(by_name, "average_viewer_hours_per_month", "average_bitrate_mbps", "region_traffic_mix", "cdn_cache_hit_ratio"), required_rate_dimensions={})
    if "lambda" in key or "function" in key:
        return ServiceUsageDimension(service_name=service, usage_name="edge function invocations", aws_service_code=service_code, quantity=Decimal(str(drivers.edge_function_invocations_per_month or drivers.asset_count * 30)), unit="requests", formula="edge_function_invocations_per_month", driver_binding_ids=_ids(by_name, "edge_function_invocations_per_month"), assumption_ids=_assumptions_for_drivers(by_name, "edge_function_invocations_per_month"), required_rate_dimensions={})
    if "mediatailor" in key:
        return ServiceUsageDimension(service_name=service, usage_name="ad decision requests", aws_service_code=service_code, quantity=Decimal(str(drivers.ad_decision_requests_per_month or drivers.integration_api_calls_per_day * 30)), unit="requests", formula="ad_decision_requests_per_month", driver_binding_ids=_ids(by_name, "ad_decision_requests_per_month"), assumption_ids=_assumptions_for_drivers(by_name, "ad_decision_requests_per_month"), required_rate_dimensions={})
    if "medialive" in key:
        channel_hours = Decimal(str((drivers.live_channel_count or 1) * (drivers.event_hours_per_month or 720)))
        return ServiceUsageDimension(service_name=service, usage_name="live channel-hours", aws_service_code=service_code, quantity=channel_hours, unit="channel-hours", formula="live_channel_count * event_hours_per_month", driver_binding_ids=_ids(by_name, "live_channel_count", "event_hours_per_month"), assumption_ids=_assumptions_for_drivers(by_name, "live_channel_count", "event_hours_per_month"), required_rate_dimensions={})
    return ServiceUsageDimension(service_name=service, usage_name="not estimated in Pass 1B", aws_service_code=service_code, quantity=None, unit="varies", formula="not_estimated", assumption_ids=[])


def _fraud_usage_dimension(service: str, key: str, service_code: str, by_name: dict[str, PricingDriverBinding], assumption_ids: list[str], drivers: Any) -> ServiceUsageDimension:
    if "kinesis" in key or "flink" in key:
        return ServiceUsageDimension(service_name=service, usage_name="transaction stream events", aws_service_code=service_code, quantity=Decimal(str(drivers.monthly_event_volume)), unit="events", formula="transactions_per_day * 30", driver_binding_ids=_ids(by_name, "transactions_per_day"), assumption_ids=assumption_ids)
    if "sagemaker" in key:
        return ServiceUsageDimension(service_name=service, usage_name="fraud scoring invocations", aws_service_code=service_code, quantity=Decimal(str(drivers.inference_events_per_day * 30)), unit="inferences", formula="scoring_events_per_day * 30", driver_binding_ids=_ids(by_name, "scoring_events_per_day"), assumption_ids=assumption_ids)
    if "s3" in key:
        return ServiceUsageDimension(service_name=service, usage_name="audit evidence retention", aws_service_code=service_code, quantity=None, unit="GB-month", formula="audit_payload_kb * transactions_per_day * retention; audit payload size missing", driver_binding_ids=_ids(by_name, "transactions_per_day", "audit_retention_years", "audit_payload_kb"), assumption_ids=assumption_ids)
    return ServiceUsageDimension(service_name=service, usage_name="fraud workflow usage", aws_service_code=service_code, quantity=None, unit="varies", formula="Workload-specific quantity not bound in Pass 1.", assumption_ids=assumption_ids)


def _risk_usage_dimension(service: str, key: str, service_code: str, by_name: dict[str, PricingDriverBinding], assumption_ids: list[str], drivers: Any) -> ServiceUsageDimension:
    if "batch" in key:
        return ServiceUsageDimension(service_name=service, usage_name="risk compute node-hours", aws_service_code=service_code, quantity=Decimal(str(drivers.hpc_compute_hours_per_month)), unit="node-hours", formula="risk_runs_per_day * 30 * assumed risk_grid_nodes * assumed runtime", driver_binding_ids=_ids(by_name, "risk_runs_per_day", "hpc_compute_node_hours_per_day"), assumption_ids=assumption_ids)
    if "fsx" in key or "lustre" in key:
        return ServiceUsageDimension(service_name=service, usage_name="simulation scratch storage", aws_service_code=service_code, quantity=Decimal(str(drivers.result_storage_gb_per_month)), unit="GB-month", formula="derived result/scratch footprint from positions and risk windows", driver_binding_ids=_ids(by_name, "open_positions", "risk_runs_per_day", "shared_storage_tb"), assumption_ids=assumption_ids)
    if "elasticache" in key:
        return ServiceUsageDimension(service_name=service, usage_name="low-latency cache node-hours", aws_service_code=service_code, quantity=Decimal(str(drivers.cache_node_hours_monthly)), unit="node-hours", formula="assumed risk_grid_nodes * 720", driver_binding_ids=_ids(by_name, "low_latency_cache_gb"), assumption_ids=assumption_ids)
    return ServiceUsageDimension(service_name=service, usage_name="risk platform usage", aws_service_code=service_code, quantity=None, unit="varies", formula="Workload-specific quantity not fully bound in Pass 1.", assumption_ids=assumption_ids)


def _pricing_ledger(pricing: PricingAnalysis, usage_dimensions: list[ServiceUsageDimension], rate_bindings: list[AwsRateBinding], assumptions: AssumptionLedger) -> PricingLedger:
    dimensions_by_service = {item.service_name: item for item in usage_dimensions}
    bindings_by_service = {item.service_name: item for item in rate_bindings}
    line_items: list[PricingLedgerLineItem] = []
    sku_total = Decimal("0")
    reference_total = Decimal("0")
    heuristic_total = Decimal("0")
    not_estimated: list[str] = []
    for line in pricing.line_items:
        dimension = dimensions_by_service.get(line.service)
        rate = bindings_by_service.get(line.service)
        monthly = Decimal(str(line.expected_monthly_usd))
        evidence_class = "heuristic"
        procurement_ready = False
        if rate and rate.binding_status == "bound":
            evidence_class = "sku_tier_backed"
            procurement_ready = not bool(dimension and dimension.assumption_ids)
            if dimension and dimension.quantity is not None and rate.price_per_unit is not None:
                monthly = (Decimal(dimension.quantity) * Decimal(rate.price_per_unit)).quantize(Decimal("0.01"))
        elif rate and rate.binding_status == "ambiguous":
            evidence_class = "price_catalog_referenced"
        elif rate and rate.binding_status == "not_found":
            evidence_class = "heuristic"
        elif rate and rate.aws_service_code != "unknown":
            evidence_class = "heuristic"
        if dimension and dimension.quantity is None:
            evidence_class = "not_estimated" if _is_vague_formula(dimension.formula) else "heuristic"
            monthly = None if evidence_class == "not_estimated" else monthly
            not_estimated.append(line.service)
        if monthly is not None and evidence_class == "sku_tier_backed":
            sku_total += monthly
        elif monthly is not None and evidence_class in {"pricing_mcp_backed", "official_pricing_page_backed", "price_catalog_referenced"}:
            reference_total += monthly
        elif monthly is not None and evidence_class == "heuristic":
            heuristic_total += monthly
        line_items.append(PricingLedgerLineItem(
            service_name=line.service,
            usage_name=dimension.usage_name if dimension else "service usage",
            quantity=dimension.quantity if dimension else None,
            quantity_unit=dimension.unit if dimension else "varies",
            formula=dimension.formula if dimension else "No usage dimension binding produced.",
            rate_binding_id=rate.id if rate else None,
            unit_price=rate.price_per_unit if rate else None,
            monthly_total=monthly,
            evidence_class=evidence_class,
            procurement_ready=procurement_ready,
            confidence="low" if not procurement_ready else "high",
            assumptions=dimension.assumption_ids if dimension else [],
            limitations=_ledger_limitations(dimension, rate, procurement_ready, evidence_class),
        ))
    summary = PricingLedgerSummary(
        sku_tier_backed_subtotal=sku_total,
        pricing_page_or_mcp_backed_subtotal=reference_total,
        heuristic_subtotal=heuristic_total,
        not_estimated_items=not_estimated,
        headline_safe=not not_estimated and all(item.procurement_ready for item in line_items),
        procurement_ready=bool(line_items) and all(item.procurement_ready for item in line_items),
    )
    return PricingLedger(line_items=line_items, summary=summary)


def _sanity_findings(family: str, facts: CanonicalFactsLedger, bindings: list[PricingDriverBinding], usage_dimensions: list[ServiceUsageDimension], ledger: PricingLedger, pricing: PricingAnalysis):
    findings = []
    fact_names = {fact.name for fact in facts.facts}
    unknowns = set(pricing.unknown_variables)
    for name in sorted(fact_names & unknowns):
        findings.append(finding(code="pricing.confirmed_fact_listed_unknown", severity="critical", category="pricing", title="Confirmed Fact Listed As Unknown", description=f"Confirmed fact {name} appears in pricing unknown variables.", evidence=[name], auto_repairable=True, repair_strategy="Remove confirmed facts from unknown variables.", customer_readiness_impact="cap_to_directional"))
    missing_core = [binding.driver_name for binding in bindings if binding.required_for_headline_pricing and binding.status in {"missing", "assumed"}]
    if missing_core:
        findings.append(finding(code="pricing.core_driver_missing_or_assumed", severity="warning", category="pricing", title="Core Pricing Drivers Missing Or Assumed", description=f"Core drivers are not confirmed: {', '.join(missing_core)}.", evidence=missing_core, auto_repairable=False, customer_readiness_impact="cap_to_directional"))
    if family == PricingDriverFamily.LIVE_MEDIA_STREAMING.value:
        cloudfront = next((item for item in usage_dimensions if "CloudFront" in item.service_name and item.usage_name == "CDN data transfer out"), None)
        edge = next((item for item in usage_dimensions if item.usage_name == "edge function invocations"), None)
        if cloudfront and edge and cloudfront.quantity == edge.quantity:
            findings.append(finding(code="pricing.incompatible_quantity_reuse", severity="critical", category="pricing", title="Incompatible Quantity Reuse", description="CloudFront egress quantity was reused for edge function pricing.", evidence=[cloudfront.id, edge.id], auto_repairable=False, customer_readiness_impact="cap_to_internal_only"))
        if edge and edge.unit.lower() in {"gb", "tb"}:
            findings.append(finding(code="pricing.edge_compute_uses_egress_unit", severity="critical", category="pricing", title="Edge Compute Uses Egress Unit", description="Edge function pricing must use request/invocation units, not CDN egress units.", evidence=[edge.id], auto_repairable=False, customer_readiness_impact="cap_to_internal_only"))
        medialive = next((item for item in usage_dimensions if "MediaLive" in item.service_name), None)
        live_channel_binding = next((item for item in bindings if item.driver_name == "live_channel_count"), None)
        if medialive and (not live_channel_binding or live_channel_binding.status not in {"confirmed", "assumed"}):
            findings.append(finding(code="pricing.hidden_live_channel_assumption", severity="critical", category="pricing", title="Hidden MediaLive Channel Assumption", description="MediaLive channel-hours formula needs a confirmed or explicit assumed live_channel_count.", evidence=[medialive.id], auto_repairable=False, customer_readiness_impact="cap_to_directional"))
    for line in ledger.line_items:
        if line.quantity is None and _is_vague_formula(line.formula) and line.monthly_total is not None:
            findings.append(finding(code="pricing.vague_line_item_has_total", severity="critical", category="pricing", title="Vague Line Item Has Total", description=f"{line.service_name} has no concrete quantity/formula but still has a monthly total.", evidence=[line.id], auto_repairable=True, repair_strategy="Mark as not_estimated and remove monthly total.", customer_readiness_impact="cap_to_directional"))
    if not ledger.summary.procurement_ready:
        findings.append(finding(code="pricing.not_procurement_ready", severity="warning", category="pricing", title="Pricing Ledger Not Procurement Ready", description="At least one line item lacks exact SKU/tier rate binding.", evidence=[item.service_name for item in ledger.line_items if not item.procurement_ready], auto_repairable=False, customer_readiness_impact="cap_to_directional"))
    if pricing.expected_monthly_usd and not ledger.line_items:
        findings.append(finding(code="pricing.nonzero_total_without_pricing_ledger", severity="critical", category="pricing", title="Non-Zero Pricing Without Ledger", description="A non-zero estimate exists but the pricing ledger has no line items.", evidence=["pricing_ledger.line_items=[]"], auto_repairable=True, repair_strategy="Hide headline pricing until ledger lines are produced.", customer_readiness_impact="cap_to_directional"))
    return findings


def _annotate_line_items(pricing: PricingAnalysis, dimensions: list[ServiceUsageDimension], ledger: PricingLedger, rate_bindings: list[AwsRateBinding]) -> None:
    by_service = {item.service_name: item for item in dimensions}
    ledger_by_service = {item.service_name: item for item in ledger.line_items}
    rate_by_service = {item.service_name: item for item in rate_bindings}
    for line in pricing.line_items:
        dimension = by_service.get(line.service)
        ledger_line = ledger_by_service.get(line.service)
        rate = rate_by_service.get(line.service)
        candidate_rate_used = bool(ledger_line and ledger_line.evidence_class == "sku_tier_backed")
        line.pricing_trace = {
            **(line.pricing_trace or {}),
            "source_truth_usage_dimension_id": dimension.id if dimension else None,
            "source_truth_formula": dimension.formula if dimension else None,
            "source_truth_quantity": str(dimension.quantity) if dimension and dimension.quantity is not None else None,
            "source_truth_quantity_unit": dimension.unit if dimension else None,
            "evidence_class": ledger_line.evidence_class if ledger_line else "heuristic",
            "procurement_ready": ledger_line.procurement_ready if ledger_line else False,
            "not_estimated": bool(ledger_line and ledger_line.evidence_class == "not_estimated"),
            "rate_binding_status": rate.binding_status if rate else None,
            "candidate_sku": rate.sku if rate else None,
            "candidate_rate_code": rate.rate_code if rate else None,
            "candidate_usage_type": rate.usage_type if rate else None,
            "candidate_unit": rate.unit if rate else None,
            "candidate_price_per_unit": str(rate.price_per_unit) if rate and rate.price_per_unit is not None else None,
            "candidate_rate_source": rate.source if rate else None,
            "candidate_rate_used_for_total": candidate_rate_used,
            "candidate_rate_note": "Candidate rate was not used for monthly_total because AWS rate binding is ambiguous." if rate and rate.binding_status == "ambiguous" else None,
        }


def _ids(bindings: dict[str, PricingDriverBinding], *names: str) -> list[str]:
    return [bindings[name].id for name in names if name in bindings]


def _assumptions_for_drivers(bindings: dict[str, PricingDriverBinding], *names: str) -> list[str]:
    return list(dict.fromkeys(bindings[name].assumption_id for name in names if name in bindings and bindings[name].assumption_id))


def _assumption_ids_by_driver(assumptions: AssumptionLedger) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for item in assumptions.assumptions:
        for driver_name in item.impacted_pricing_drivers:
            mapping.setdefault(driver_name, []).append(item.id)
        statement = item.statement.lower()
        if "bitrate" in statement:
            mapping.setdefault("average_bitrate_mbps", []).append(item.id)
        if "viewer engagement" in statement or "viewer-hours" in statement:
            mapping.setdefault("average_viewer_hours_per_month", []).append(item.id)
        if "egress mix" in statement:
            mapping.setdefault("region_traffic_mix", []).append(item.id)
            mapping.setdefault("cdn_cache_hit_ratio", []).append(item.id)
        if "one live channel" in statement:
            mapping.setdefault("live_channel_count", []).append(item.id)
        if "event duration" in statement or "720 channel-hours" in statement:
            mapping.setdefault("event_hours_per_month", []).append(item.id)
        if "analyst review" in statement:
            mapping.setdefault("analyst_review_rate_percent", []).append(item.id)
        if "feature reads" in statement:
            mapping.setdefault("feature_reads_per_transaction", []).append(item.id)
            mapping.setdefault("feature_writes_per_transaction", []).append(item.id)
        if "risk-grid" in statement:
            mapping.setdefault("hpc_compute_node_hours_per_day", []).append(item.id)
            mapping.setdefault("monte_carlo_paths", []).append(item.id)
        if "market data ingest" in statement:
            mapping.setdefault("market_data_gb_per_day", []).append(item.id)
    return mapping


def _assign_assumption_driver_usage(assumptions: AssumptionLedger, bindings: list[PricingDriverBinding]) -> None:
    by_assumption: dict[str, list[str]] = {}
    for binding in bindings:
        if binding.assumption_id:
            by_assumption.setdefault(binding.assumption_id, []).append(binding.id)
    for item in assumptions.assumptions:
        item.used_by_driver_ids = by_assumption.get(item.id, [])


def _assign_assumption_line_usage(assumptions: AssumptionLedger, dimensions: list[ServiceUsageDimension]) -> None:
    by_assumption: dict[str, list[str]] = {}
    for dimension in dimensions:
        for assumption_id in dimension.assumption_ids:
            by_assumption.setdefault(assumption_id, []).append(dimension.id)
    for item in assumptions.assumptions:
        item.used_by_line_items = by_assumption.get(item.id, [])


def _is_vague_formula(formula: str | None) -> bool:
    value = (formula or "").lower()
    return not value or value in {"not_estimated"} or "no exact" in value or "not bound" in value or "not estimated" in value


def _ledger_limitations(dimension: ServiceUsageDimension | None, rate: AwsRateBinding | None, procurement_ready: bool, evidence_class: str) -> list[str]:
    if procurement_ready:
        return []
    if evidence_class == "not_estimated":
        return ["No concrete usage quantity and formula were available, so this line is not estimated."]
    if rate and rate.binding_status == "bound" and dimension and dimension.assumption_ids:
        return ["AWS SKU/tier rate is bound, but one or more usage quantities are assumed; customer-confirm quantities before procurement use."]
    if rate and rate.binding_status == "ambiguous":
        return ["Multiple plausible AWS Price List rates matched; candidate rate is shown for traceability but is not used for monthly_total because binding_status=ambiguous."]
    if rate and rate.binding_status == "not_found":
        return [*(rate.notes or []), "No exact AWS SKU/tier rate was found for this usage dimension; total remains heuristic and directional."]
    if dimension and dimension.quantity is not None:
        return ["Usage quantity is explicit, but exact AWS SKU/tier rate was not bound; total remains directional."]
    return ["Exact AWS SKU/tier rate was not bound; total remains directional."]


def _apply_ledger_totals_to_pricing(pricing: PricingAnalysis, ledger: PricingLedger) -> None:
    by_service = {item.service_name: item for item in ledger.line_items}
    for line in pricing.line_items:
        ledger_line = by_service.get(line.service)
        if not ledger_line:
            continue
        if ledger_line.monthly_total is None:
            line.low_monthly_usd = 0
            line.expected_monthly_usd = 0
            line.high_monthly_usd = 0
            line.unit_basis = "Not estimated in Pass 1B; no concrete usage quantity/formula is available."
            continue
        if ledger_line.evidence_class == "sku_tier_backed":
            value = float(ledger_line.monthly_total)
            line.low_monthly_usd = value
            line.expected_monthly_usd = value
            line.high_monthly_usd = value
    pricing.low_monthly_usd = round(sum(item.low_monthly_usd for item in pricing.line_items), 2)
    pricing.expected_monthly_usd = round(sum(item.expected_monthly_usd for item in pricing.line_items), 2)
    pricing.high_monthly_usd = round(sum(item.high_monthly_usd for item in pricing.line_items), 2)


def _normalized_service(service: str) -> str:
    return service.lower().replace("amazon ", "").replace("aws ", "").replace("@", "").replace(" ", "_").replace("/", "_")


def _fact_alias(name: str) -> str:
    aliases = {
        "open_positions": "open_derivatives_positions",
        "greeks_recalculation_seconds": "greeks_frequency_seconds",
        "risk_runs_per_day": "risk_compute_jobs_per_day",
        "average_bitrate_mbps": "bitrate_mbps",
        "latency_target_ms": "scoring_latency_target",
    }
    return aliases.get(name, name)


def _core_driver_names(family: str) -> set[str]:
    return {
        PricingDriverFamily.HEALTHCARE_OPERATIONS_SCHEDULING.value: {"active_or_count_poc", "refresh_cadence_minutes", "recommendation_runs_per_day", "approval_workflow_executions_per_day", "audit_retention_months"},
        PricingDriverFamily.PAYMENT_FRAUD_SCORING.value: {"transactions_per_day", "latency_target_ms", "scoring_events_per_day", "audit_retention_years"},
        PricingDriverFamily.CAPITAL_MARKETS_RISK_ENGINE.value: {"open_positions", "greeks_recalculation_seconds", "risk_runs_per_day", "hpc_compute_node_hours_per_day"},
        PricingDriverFamily.LIVE_MEDIA_STREAMING.value: {"concurrent_viewers", "average_viewer_hours_per_month", "average_bitrate_mbps", "region_traffic_mix", "cdn_cache_hit_ratio"},
    }[family]


def _assumed_core_driver_names() -> set[str]:
    return {
        "average_viewer_hours_per_month",
        "average_bitrate_mbps",
        "region_traffic_mix",
        "cdn_cache_hit_ratio",
        "event_hours_per_month",
        "live_channel_count",
        "hpc_compute_node_hours_per_day",
        "market_data_gb_per_day",
        "analyst_review_rate_percent",
        "auto_block_rate_percent",
        "active_or_count_poc",
        "recommendation_runs_per_day",
        "approval_workflow_executions_per_day",
        "ehr_writeback_attempts_per_day",
    }
