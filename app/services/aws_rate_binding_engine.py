from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.domain.pricing_evidence import PriceDimensionEvidence
from app.domain.source_of_truth import AwsRateBinding, ServiceUsageDimension
from app.services.aws_price_list_parser import parse_price_list_query_response


class AwsRateBindingEngine:
    def bind(self, dimension: ServiceUsageDimension, *, region_code: str) -> AwsRateBinding:
        if dimension.aws_service_code == "unknown":
            return AwsRateBinding(
                service_name=dimension.service_name,
                aws_service_code=dimension.aws_service_code,
                binding_status="unsupported",
                notes=["No supported AWS Price List service-code mapping exists for this service."],
            )
        if dimension.quantity is None:
            return AwsRateBinding(
                service_name=dimension.service_name,
                aws_service_code=dimension.aws_service_code,
                unit=dimension.unit,
                binding_status="not_found",
                notes=["No concrete usage quantity was available, so exact rate binding was skipped."],
            )
        try:
            response = _get_products(dimension, region_code)
        except Exception as exc:
            return AwsRateBinding(
                service_name=dimension.service_name,
                aws_service_code=dimension.aws_service_code,
                unit=dimension.unit,
                binding_status="not_found",
                source="unbound",
                notes=[f"AWS Price List Query API lookup failed: {type(exc).__name__}: {str(exc)[:220]}"],
            )
        parsed = parse_price_list_query_response(
            response,
            service_code=dimension.aws_service_code,
            source_reference=f"pricing:GetProducts:{dimension.aws_service_code}",
        )
        candidates = _matching_dimensions(dimension, parsed.dimensions)
        if not candidates:
            notes = list(parsed.failures)
            if parsed.ambiguous_skus:
                notes.append(f"Matched products were ambiguous before dimension filtering: {', '.join(parsed.ambiguous_skus[:5])}.")
            notes.append(f"No OnDemand price dimension matched usage '{dimension.usage_name}' with unit '{dimension.unit}'.")
            return AwsRateBinding(
                service_name=dimension.service_name,
                aws_service_code=dimension.aws_service_code,
                unit=dimension.unit,
                binding_status="not_found",
                source="price_list_query_api",
                confidence="low",
                notes=notes,
            )
        if len(candidates) > 1:
            return _binding_from_dimension(
                dimension,
                candidates[0],
                status="ambiguous",
                confidence="medium",
                notes=[
                    f"{len(candidates)} plausible AWS Price List rates matched; Archway did not silently choose one.",
                    "Confirm usage type, operation, region/edge location, tier, and product attributes before procurement use.",
                ],
            )
        return _binding_from_dimension(
            dimension,
            candidates[0],
            status="bound",
            confidence="high",
            notes=["Exact single OnDemand price dimension matched the service usage dimension."],
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
    return client.get_products(ServiceCode=dimension.aws_service_code, Filters=filters, MaxResults=12)


def _filters_for_dimension(dimension: ServiceUsageDimension, region_code: str) -> list[dict[str, str]]:
    filters: list[dict[str, str]] = []
    if dimension.aws_service_code != "AmazonCloudFront":
        filters.append({"Type": "TERM_MATCH", "Field": "regionCode", "Value": region_code})
    for key, value in dimension.required_rate_dimensions.items():
        if value:
            filters.append({"Type": "TERM_MATCH", "Field": key, "Value": value})
    return filters


def _matching_dimensions(dimension: ServiceUsageDimension, dimensions: list[PriceDimensionEvidence]) -> list[PriceDimensionEvidence]:
    expected_unit = _canonical_unit(dimension.unit)
    service = dimension.service_name.lower()
    usage = dimension.usage_name.lower()
    matches: list[PriceDimensionEvidence] = []
    for item in dimensions:
        item_unit = _canonical_unit(item.unit)
        text = " ".join(str(value or "").lower() for value in (item.usage_type, item.operation, item.product_family))
        if expected_unit and item_unit and expected_unit != item_unit:
            continue
        if "cloudfront" in service and "data transfer" in usage:
            if any(token in text for token in ("datatransfer-out", "data-out", "data transfer out", "out-bytes", "regional data transfer out")):
                matches.append(item)
            continue
        if ("lambda@edge" in service or "cloudfront function" in service or "edge function" in usage) and expected_unit == "requests":
            if any(token in text for token in ("request", "invocation", "cloudfront-function", "lambda-edge-request")):
                matches.append(item)
            continue
        if "medialive" in service and expected_unit in {"hours", "channel-hours"}:
            if any(token in text for token in ("channel", "output", "input", "hour")):
                matches.append(item)
            continue
        if dimension.required_rate_dimensions:
            matches.append(item)
    return matches[:8]


def _canonical_unit(unit: str | None) -> str:
    value = str(unit or "").lower().strip()
    if value in {"gb", "gbs", "gigabyte", "gigabytes"}:
        return "gb"
    if value in {"tb", "tbs", "terabyte", "terabytes"}:
        return "tb"
    if value in {"request", "requests", "invocation", "invocations"}:
        return "requests"
    if value in {"hour", "hours", "hrs", "channel-hours", "channel hours"}:
        return "hours"
    return value


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
