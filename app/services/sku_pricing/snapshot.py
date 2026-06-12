"""Versioned pricing snapshot abstraction.

A snapshot is a small, content-hashed set of rate records for a region. Real AWS
Price List payloads are large and are NOT committed; this module ships a compact
hand-authored fixture snapshot (source=static_fixture) for the foundation/tests,
and can load a snapshot from a small JSON file.

Honesty rule: only AUTHORITATIVE_SOURCES may ever back procurement-ready /
headline-safe pricing. ``static_fixture`` is SKU-shaped but not rate-authoritative.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Sources whose rates may back procurement-ready / headline-safe pricing.
AUTHORITATIVE_SOURCES = frozenset({"local_cache", "price_list_api", "mcp"})
VALID_SOURCES = AUTHORITATIVE_SOURCES | {"static_fixture"}


def _canonical_unit(unit: str) -> str:
    value = str(unit or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    aliases = {
        "gbmo": "gb-month", "gbmonth": "gb-month", "gbmonths": "gb-month",
        "gbsecond": "gb-second", "gbseconds": "gb-second", "gbs": "gb-second",
        "request": "requests", "requests": "requests",
        "event": "events", "events": "events",
        "gb": "gb", "gigabyte": "gb", "gigabytes": "gb",
        "readrequestunits": "read-request-units", "readrequestunit": "read-request-units",
        "writerequestunits": "write-request-units", "writerequestunit": "write-request-units",
    }
    return aliases.get(value, value)


@dataclass(frozen=True)
class RateRecord:
    service_name: str
    service_code: str
    region: str
    dimension_key: str   # logical key a UsageDimension references (e.g. "lambda_requests")
    usage_type: str
    unit: str            # billable unit, e.g. "GB-Mo", "Requests", "GB-Second"
    rate: Decimal        # price per unit (USD by default)
    currency: str = "USD"
    operation: str | None = None
    sku: str | None = None
    price_dimension_id: str | None = None

    @property
    def canonical_unit(self) -> str:
        return _canonical_unit(self.unit)

    def to_dict(self) -> dict:
        return {
            "service_name": self.service_name,
            "service_code": self.service_code,
            "region": self.region,
            "dimension_key": self.dimension_key,
            "usage_type": self.usage_type,
            "unit": self.unit,
            "rate": str(self.rate),
            "currency": self.currency,
            "operation": self.operation,
            "sku": self.sku,
            "price_dimension_id": self.price_dimension_id,
        }

    @staticmethod
    def from_dict(data: dict) -> "RateRecord":
        return RateRecord(
            service_name=str(data["service_name"]),
            service_code=str(data["service_code"]),
            region=str(data["region"]),
            dimension_key=str(data["dimension_key"]),
            usage_type=str(data["usage_type"]),
            unit=str(data["unit"]),
            rate=Decimal(str(data["rate"])),
            currency=str(data.get("currency", "USD")),
            operation=data.get("operation"),
            sku=data.get("sku"),
            price_dimension_id=data.get("price_dimension_id"),
        )


def compute_version_hash(rates: list[RateRecord], region: str, currency: str) -> str:
    """Content hash over the rate records. Changing any rate changes this hash."""
    payload = {
        "region": region,
        "currency": currency,
        "rates": sorted(
            (
                f"{r.service_code}|{r.dimension_key}|{r.usage_type}|{r.canonical_unit}|{r.rate}|{r.sku}|{r.price_dimension_id}"
                for r in rates
            )
        ),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:32]


@dataclass(frozen=True)
class PriceSnapshot:
    snapshot_id: str
    generated_at: str
    region: str
    source: str          # local_cache | price_list_api | mcp | static_fixture
    currency: str
    services: tuple[str, ...]
    rates: tuple[RateRecord, ...]
    version_hash: str = ""
    # Optional upstream provenance for local_cache / api / mcp snapshots:
    # {upstream_source, upstream_source_url, source_hash, schema_version}.
    provenance: dict | None = None

    @property
    def is_authoritative(self) -> bool:
        # Source-level authority (structural). Provenance-aware authority for
        # local_cache snapshots is enforced by sku_pricing.provenance.
        return self.source in AUTHORITATIVE_SOURCES

    def rates_for(self, dimension_key: str) -> list[RateRecord]:
        return [r for r in self.rates if r.dimension_key == dimension_key and r.region == self.region]

    def to_metadata(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "generated_at": self.generated_at,
            "region": self.region,
            "source": self.source,
            "currency": self.currency,
            "services": list(self.services),
            "version_hash": self.version_hash,
            "is_authoritative": self.is_authoritative,
            "provenance": dict(self.provenance) if self.provenance else None,
        }


def _finalize(snapshot: PriceSnapshot) -> PriceSnapshot:
    version = compute_version_hash(list(snapshot.rates), snapshot.region, snapshot.currency)
    return PriceSnapshot(
        snapshot_id=snapshot.snapshot_id,
        generated_at=snapshot.generated_at,
        region=snapshot.region,
        source=snapshot.source,
        currency=snapshot.currency,
        services=snapshot.services,
        rates=snapshot.rates,
        version_hash=version,
        provenance=snapshot.provenance,
    )


def load_snapshot(path: str | Path) -> PriceSnapshot:
    """Load a snapshot from a small JSON file and (re)compute its version hash."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if str(data.get("source")) not in VALID_SOURCES:
        raise ValueError(f"Unknown snapshot source: {data.get('source')!r}")
    rates = tuple(RateRecord.from_dict(item) for item in data.get("rates", []))
    snapshot = PriceSnapshot(
        snapshot_id=str(data["snapshot_id"]),
        generated_at=str(data.get("generated_at", "")),
        region=str(data["region"]),
        source=str(data["source"]),
        currency=str(data.get("currency", "USD")),
        services=tuple(data.get("services", [])),
        rates=rates,
    )
    return _finalize(snapshot)


# --------------------------------------------------------------------------- #
# Built-in compact FIXTURE snapshot (NOT authoritative AWS rates).
# Representative us-east-1 on-demand values for the supported service set, used by
# the foundation and tests. Refresh from a live Price List snapshot before any
# procurement use.
# --------------------------------------------------------------------------- #
_FIXTURE_RATES = [
    ("Amazon S3", "AmazonS3", "s3_standard_storage_gb_month", "TimedStorage-ByteHrs", "GB-Mo", "0.023", "S3-Standard"),
    ("AWS Lambda", "AWSLambda", "lambda_requests", "Request", "Requests", "0.0000002", "Lambda-Requests"),
    ("AWS Lambda", "AWSLambda", "lambda_gb_seconds", "Lambda-GB-Second", "GB-Second", "0.0000166667", "Lambda-Duration"),
    ("Amazon SQS", "AmazonSQS", "sqs_requests", "Requests-Tier1", "Requests", "0.0000004", "SQS-Requests"),
    ("Amazon EventBridge", "AmazonEventBridge", "eventbridge_custom_events", "Event-64K-Chunks", "Events", "0.000001", "EB-CustomEvents"),
    ("Amazon DynamoDB", "AmazonDynamoDB", "dynamodb_write_request_units", "WriteRequestUnits", "WriteRequestUnits", "0.00000125", "DDB-WRU"),
    ("Amazon DynamoDB", "AmazonDynamoDB", "dynamodb_read_request_units", "ReadRequestUnits", "ReadRequestUnits", "0.00000025", "DDB-RRU"),
    ("Amazon DynamoDB", "AmazonDynamoDB", "dynamodb_storage_gb_month", "TimedStorage-ByteHrs", "GB-Mo", "0.25", "DDB-Storage"),
    ("Amazon CloudWatch Logs", "AmazonCloudWatch", "cwl_ingestion_gb", "DataProcessing-Bytes", "GB", "0.50", "CWL-Ingestion"),
    ("Amazon CloudWatch Logs", "AmazonCloudWatch", "cwl_storage_gb_month", "TimedStorage-ByteHrs", "GB-Mo", "0.03", "CWL-Storage"),
]


def builtin_fixture_snapshot(region: str = "us-east-1", snapshot_id: str = "fixture-us-east-1-v1") -> PriceSnapshot:
    rates = tuple(
        RateRecord(
            service_name=name,
            service_code=code,
            region=region,
            dimension_key=key,
            usage_type=usage_type,
            unit=unit,
            rate=Decimal(rate),
            currency="USD",
            operation=None,
            sku=f"{sku}-FIXTURE",
            price_dimension_id=f"{sku}-FIXTURE.dim",
        )
        for (name, code, key, usage_type, unit, rate, sku) in _FIXTURE_RATES
    )
    services = tuple(dict.fromkeys(r.service_name for r in rates))
    snapshot = PriceSnapshot(
        snapshot_id=snapshot_id,
        generated_at=datetime(2026, 6, 8, tzinfo=timezone.utc).isoformat(),
        region=region,
        source="static_fixture",
        currency="USD",
        services=services,
        rates=rates,
    )
    return _finalize(snapshot)
