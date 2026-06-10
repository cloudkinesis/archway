"""Reduced AWS Price List parser.

This is intentionally a REDUCED parser. It does NOT parse the full, large official
AWS Price List payload. It consumes a small, documented "reduced" shape that
preserves the fields Archway needs for the supported service set, and converts it
into foundation ``RateRecord`` objects.

Reduced shape (per product entry):
    {
      "service_name": "Amazon S3",
      "service_code": "AmazonS3",
      "region": "us-east-1",
      "usage_type": "TimedStorage-ByteHrs",
      "operation": "StandardStorage",
      "sku": "...",
      "price_dimension_id": "....dim",
      "unit": "GB-Mo",
      "usd_rate": "0.023",
      "dimension_key": "s3_standard_storage_gb_month"   # logical key UsageDimensions reference
    }

The explicit ``dimension_key`` keeps this reduced and honest: we do not attempt to
infer logical drivers from raw AWS usage types in this branch.

DEPENDS ON: feature/sku-backed-pricing-foundation (app/services/sku_pricing).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.services.sku_pricing.snapshot import RateRecord

# Services this reduced parser is scoped to.
SUPPORTED_SERVICE_CODES = frozenset(
    {"AmazonS3", "AWSLambda", "AmazonSQS", "AmazonEventBridge", "AmazonDynamoDB", "AmazonCloudWatch"}
)

REQUIRED_FIELDS = ("service_name", "service_code", "region", "usage_type", "unit", "usd_rate", "dimension_key")


class PriceListParseError(ValueError):
    pass


def parse_reduced_price_list(data: dict, *, strict: bool = False) -> list[RateRecord]:
    """Parse a reduced AWS Price List-style payload into RateRecords.

    Skips entries for unsupported services or with missing required fields (or
    raises if ``strict``). Only OnDemand USD rates in the reduced shape are read.
    """
    products = data.get("products") if isinstance(data, dict) else None
    if products is None:
        raise PriceListParseError("Reduced price list payload missing 'products' array.")
    region = data.get("region")
    records: list[RateRecord] = []
    for entry in products:
        if not isinstance(entry, dict):
            continue
        missing = [f for f in REQUIRED_FIELDS if not entry.get(f)]
        if missing:
            if strict:
                raise PriceListParseError(f"Product entry missing required fields {missing}: {entry}")
            continue
        if entry["service_code"] not in SUPPORTED_SERVICE_CODES:
            if strict:
                raise PriceListParseError(f"Unsupported service_code: {entry['service_code']}")
            continue
        if region and entry.get("region") != region:
            continue
        try:
            rate = Decimal(str(entry["usd_rate"]))
        except (InvalidOperation, TypeError) as exc:
            if strict:
                raise PriceListParseError(f"Invalid usd_rate {entry.get('usd_rate')!r}: {exc}") from exc
            continue
        records.append(
            RateRecord(
                service_name=str(entry["service_name"]),
                service_code=str(entry["service_code"]),
                region=str(entry["region"]),
                dimension_key=str(entry["dimension_key"]),
                usage_type=str(entry["usage_type"]),
                unit=str(entry["unit"]),
                rate=rate,
                currency=str(entry.get("currency", "USD")),
                operation=entry.get("operation"),
                sku=entry.get("sku"),
                price_dimension_id=entry.get("price_dimension_id"),
            )
        )
    return records
