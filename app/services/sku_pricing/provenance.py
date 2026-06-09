"""Snapshot provenance validation.

A static fixture is fine for unit tests but is NOT authoritative. A snapshot may
be treated as authoritative only if it carries clear provenance: an authoritative
source type, an official/trusted upstream source, a source/version hash, a
generated timestamp, a region, a non-empty service list, a currency, and rate
records that carry SKU or price-dimension identifiers plus unit/rate.

DEPENDS ON: feature/sku-backed-pricing-foundation (app/services/sku_pricing).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.sku_pricing.snapshot import AUTHORITATIVE_SOURCES, PriceSnapshot

# Upstream sources we accept as official/trusted provenance for a local cache.
TRUSTED_UPSTREAM_SOURCES = frozenset(
    {
        "aws_price_list_api",
        "aws_price_list_bulk",
        "aws_price_list_bulk_api",  # official offer-file-derived caches (official_snapshot_builder)
        "aws_pricing_mcp",
        "aws_pricing_reference_mcp",
    }
)


@dataclass(frozen=True)
class ProvenanceResult:
    authoritative: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def __bool__(self) -> bool:  # allow truthiness
        return self.authoritative


def provenance_report(snapshot: PriceSnapshot) -> ProvenanceResult:
    """Return why a snapshot is / is not authoritative. Fail closed on any gap."""
    reasons: list[str] = []

    if snapshot.source not in AUTHORITATIVE_SOURCES:
        reasons.append(f"source '{snapshot.source}' is not authoritative (static_fixture is never authoritative)")

    provenance = snapshot.provenance or {}
    upstream = provenance.get("upstream_source")
    source_hash = provenance.get("source_hash")

    # local_cache must carry official upstream provenance + a source hash.
    if snapshot.source == "local_cache":
        if not upstream:
            reasons.append("local_cache snapshot has no upstream_source provenance")
        elif upstream not in TRUSTED_UPSTREAM_SOURCES:
            reasons.append(f"upstream_source '{upstream}' is not a trusted official source")
        if not source_hash:
            reasons.append("local_cache snapshot is missing source_hash")

    if not (snapshot.version_hash or source_hash):
        reasons.append("snapshot has no source_hash / version_hash")
    if not snapshot.generated_at:
        reasons.append("snapshot has no generated_at timestamp")
    if not snapshot.region:
        reasons.append("snapshot has no region")
    if not snapshot.services:
        reasons.append("snapshot services_included is empty")
    if not snapshot.currency:
        reasons.append("snapshot has no currency")

    if not snapshot.rates:
        reasons.append("snapshot has no rate records")
    else:
        for rate in snapshot.rates:
            if not (rate.sku or rate.price_dimension_id):
                reasons.append(f"rate for '{rate.dimension_key}' lacks SKU and price_dimension_id")
            if rate.rate is None:
                reasons.append(f"rate for '{rate.dimension_key}' has no rate value")
            if not rate.unit:
                reasons.append(f"rate for '{rate.dimension_key}' has no unit")
            if not rate.currency:
                reasons.append(f"rate for '{rate.dimension_key}' has no currency")

    return ProvenanceResult(authoritative=not reasons, reasons=tuple(dict.fromkeys(reasons)))


def is_authoritative_snapshot(snapshot: PriceSnapshot) -> bool:
    """Convenience boolean wrapper around ``provenance_report``."""
    return provenance_report(snapshot).authoritative
