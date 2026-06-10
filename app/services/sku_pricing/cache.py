"""Local-cache adapter for official AWS Price List-derived snapshots.

Loads/builds ``local_cache`` snapshots that carry upstream provenance, validates
that provenance (fail closed), and builds estimates that may reach
procurement-ready ONLY when the snapshot is provenance-authoritative AND every
required line binds with a confirmed quantity.

Standalone: NOT wired into the live PricingEngine / source_truth_pricing_compiler.
DEPENDS ON: feature/sku-backed-pricing-foundation (app/services/sku_pricing).
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from app.services.sku_pricing.binding import UsageDimension
from app.services.sku_pricing.estimate import SkuBackedEstimate, build_estimate
from app.services.sku_pricing.price_list_parser import parse_reduced_price_list
from app.services.sku_pricing.provenance import is_authoritative_snapshot, provenance_report
from app.services.sku_pricing.snapshot import PriceSnapshot, RateRecord, _finalize

LOCAL_CACHE_SCHEMA_VERSION = "1.0"


class LocalCacheError(ValueError):
    pass


class ProvenanceError(LocalCacheError):
    def __init__(self, reasons: list[str]):
        self.reasons = list(reasons)
        super().__init__("Snapshot is not provenance-authoritative: " + "; ".join(reasons))


def compute_source_hash(rates: list[RateRecord], *, region: str, upstream_source: str) -> str:
    """Deterministic provenance hash over the rate content + upstream source."""
    payload = {
        "region": region,
        "upstream_source": upstream_source,
        "rates": sorted(
            f"{r.service_code}|{r.dimension_key}|{r.usage_type}|{r.operation}|{r.sku}|{r.price_dimension_id}|{r.unit}|{r.rate}|{r.currency}"
            for r in rates
        ),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def _snapshot_from_cache_dict(data: dict) -> PriceSnapshot:
    if str(data.get("source")) != "local_cache":
        raise LocalCacheError(f"Expected source 'local_cache', got {data.get('source')!r}.")
    rates = tuple(RateRecord.from_dict(item) for item in data.get("rates", []))
    provenance = {
        "upstream_source": data.get("upstream_source"),
        "upstream_source_url": data.get("upstream_source_url"),
        "source_hash": data.get("source_hash"),
        "schema_version": data.get("schema_version", LOCAL_CACHE_SCHEMA_VERSION),
    }
    # Preserve optional builder provenance (offer-file-derived caches) when present.
    for optional_key in ("source_file_hashes", "builder_version", "mapping_version"):
        if data.get(optional_key) is not None:
            provenance[optional_key] = data.get(optional_key)
    snapshot = PriceSnapshot(
        snapshot_id=str(data.get("snapshot_id")),
        generated_at=str(data.get("generated_at", "")),
        region=str(data.get("region", "")),
        source="local_cache",
        currency=str(data.get("currency", "USD")),
        services=tuple(data.get("services_included", []) or data.get("services", [])),
        rates=rates,
        provenance=provenance,
    )
    return _finalize(snapshot)


def load_local_cache_snapshot(path: str | Path, *, require_authoritative: bool = True) -> PriceSnapshot:
    """Load a local-cache snapshot JSON. Fail closed on weak provenance.

    With ``require_authoritative=True`` (default) a snapshot that fails provenance
    validation raises ``ProvenanceError`` rather than being silently trusted.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    snapshot = _snapshot_from_cache_dict(data)
    report = provenance_report(snapshot)
    if require_authoritative and not report.authoritative:
        raise ProvenanceError(list(report.reasons))
    return snapshot


def build_local_cache_snapshot(
    rates: list[RateRecord],
    *,
    region: str,
    snapshot_id: str,
    upstream_source: str,
    upstream_source_url: str,
    generated_at: str,
    currency: str = "USD",
) -> PriceSnapshot:
    """Build a local_cache snapshot from parsed rate records, stamping provenance."""
    services = tuple(dict.fromkeys(r.service_name for r in rates))
    provenance = {
        "upstream_source": upstream_source,
        "upstream_source_url": upstream_source_url,
        "source_hash": compute_source_hash(rates, region=region, upstream_source=upstream_source),
        "schema_version": LOCAL_CACHE_SCHEMA_VERSION,
    }
    snapshot = PriceSnapshot(
        snapshot_id=snapshot_id,
        generated_at=generated_at,
        region=region,
        source="local_cache",
        currency=currency,
        services=services,
        rates=tuple(rates),
        provenance=provenance,
    )
    return _finalize(snapshot)


def build_local_cache_snapshot_from_reduced_price_list(
    payload: dict,
    *,
    snapshot_id: str,
    upstream_source: str = "aws_price_list_api",
    upstream_source_url: str = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/index.json",
    generated_at: str,
) -> PriceSnapshot:
    rates = parse_reduced_price_list(payload)
    region = str(payload.get("region") or (rates[0].region if rates else ""))
    currency = str(payload.get("currency", "USD"))
    return build_local_cache_snapshot(
        rates,
        region=region,
        snapshot_id=snapshot_id,
        upstream_source=upstream_source,
        upstream_source_url=upstream_source_url,
        generated_at=generated_at,
        currency=currency,
    )


def build_local_cache_estimate(
    snapshot: PriceSnapshot,
    dimensions: list[UsageDimension],
    *,
    workload_drivers: dict | None = None,
) -> SkuBackedEstimate:
    """Build an estimate using the PROVENANCE-validated authority gate.

    Procurement-ready / headline-safe require provenance authority here, so a
    local_cache snapshot with weak/fake provenance can never unlock readiness even
    if every line binds.
    """
    authoritative = is_authoritative_snapshot(snapshot)
    return build_estimate(
        snapshot,
        dimensions,
        workload_drivers=workload_drivers,
        region=snapshot.region,
        authoritative=authoritative,
    )
