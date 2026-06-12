"""SKU-backed estimate assembly + reproducibility.

Builds line items from usage dimensions against a price snapshot, classifies each
line's evidence (sku_tier_backed / catalog_referenced / not_estimated), and
aggregates subtotals. Fail-closed: a line is procurement-ready only when it binds
exactly AND the snapshot is authoritative; the estimate is procurement-ready /
headline-safe only when every required line is procurement-ready.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.services.sku_pricing.binding import (
    AMBIGUOUS,
    BOUND,
    MISSING_QUANTITY,
    NOT_FOUND,
    UNIT_MISMATCH,
    UNSUPPORTED,
    RateBinding,
    UsageDimension,
    bind_rate,
)
from app.services.sku_pricing.snapshot import PriceSnapshot

# Evidence classes.
SKU_TIER_BACKED = "sku_tier_backed"
CATALOG_REFERENCED = "catalog_referenced"
HEURISTIC = "heuristic"          # reserved for the legacy engine; never produced here
NOT_ESTIMATED = "not_estimated"

_CENTS = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class SkuBackedLine:
    service_name: str
    service_code: str
    region: str
    dimension_key: str
    usage_type: str | None
    operation: str | None
    sku: str | None
    price_dimension_id: str | None
    unit: str
    rate: Decimal | None
    quantity: Decimal | None
    formula: str
    monthly_subtotal: Decimal | None
    evidence_class: str
    snapshot_id: str
    snapshot_source: str
    procurement_ready: bool
    required_for_headline: bool
    assumptions: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict:
        return {
            "service_name": self.service_name,
            "service_code": self.service_code,
            "region": self.region,
            "dimension_key": self.dimension_key,
            "usage_type": self.usage_type,
            "operation": self.operation,
            "sku": self.sku,
            "price_dimension_id": self.price_dimension_id,
            "unit": self.unit,
            "rate": str(self.rate) if self.rate is not None else None,
            "quantity": str(self.quantity) if self.quantity is not None else None,
            "formula": self.formula,
            "monthly_subtotal": str(self.monthly_subtotal) if self.monthly_subtotal is not None else None,
            "evidence_class": self.evidence_class,
            "snapshot_id": self.snapshot_id,
            "snapshot_source": self.snapshot_source,
            "procurement_ready": self.procurement_ready,
            "required_for_headline": self.required_for_headline,
            "assumptions": list(self.assumptions),
            "reason": self.reason,
        }


@dataclass
class SkuBackedEstimate:
    snapshot_id: str
    snapshot_source: str
    snapshot_version_hash: str
    region: str
    currency: str
    estimate_input_hash: str
    snapshot_generated_at: str = ""
    snapshot_provenance: dict = field(default_factory=dict)
    lines: list[SkuBackedLine] = field(default_factory=list)
    sku_backed_subtotal: Decimal = Decimal("0.00")
    directional_subtotal: Decimal = Decimal("0.00")   # catalog_referenced
    heuristic_subtotal: Decimal = Decimal("0.00")
    not_estimated: list[str] = field(default_factory=list)
    headline_safe: bool = False
    procurement_ready: bool = False

    def to_trace(self) -> dict:
        return {
            "schema": "sku_backed_pricing_trace_v1",
            "snapshot": {
                "snapshot_id": self.snapshot_id,
                "source": self.snapshot_source,
                "version_hash": self.snapshot_version_hash,
                "generated_at": self.snapshot_generated_at,
                "upstream_source": (self.snapshot_provenance or {}).get("upstream_source"),
                "upstream_source_url": (self.snapshot_provenance or {}).get("upstream_source_url"),
                "source_hash": (self.snapshot_provenance or {}).get("source_hash"),
                "is_authoritative": self.snapshot_source in {"local_cache", "price_list_api", "mcp"},
            },
            "region": self.region,
            "currency": self.currency,
            "estimate_input_hash": self.estimate_input_hash,
            "headline_safe": self.headline_safe,
            "procurement_ready": self.procurement_ready,
            "subtotals": {
                "sku_backed": str(self.sku_backed_subtotal),
                "directional_catalog_referenced": str(self.directional_subtotal),
                "heuristic": str(self.heuristic_subtotal),
            },
            "not_estimated": list(self.not_estimated),
            "lines": [line.to_dict() for line in self.lines],
            "disclaimer": (
                "SKU-backed math is reproducible against the named snapshot. A static_fixture "
                "snapshot is illustrative and NOT procurement-authoritative; refresh from a live "
                "AWS Price List snapshot before procurement use."
            ),
        }

    def to_csv_rows(self) -> list[list[str]]:
        header = ["service", "dimension_key", "unit", "rate", "quantity", "monthly_subtotal", "evidence_class", "procurement_ready", "snapshot_id"]
        rows = [header]
        for line in self.lines:
            rows.append([
                line.service_name, line.dimension_key, line.unit,
                str(line.rate) if line.rate is not None else "",
                str(line.quantity) if line.quantity is not None else "",
                str(line.monthly_subtotal) if line.monthly_subtotal is not None else "",
                line.evidence_class, str(line.procurement_ready), line.snapshot_id,
            ])
        return rows


def estimate_input_hash(*, workload_drivers: dict, region: str, snapshot: PriceSnapshot, dimensions: list[UsageDimension]) -> str:
    """Reproducibility key: same inputs + same snapshot => identical hash & subtotals."""
    payload = {
        "region": region,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version_hash": snapshot.version_hash,
        "workload_drivers": {str(k): str(v) for k, v in sorted((workload_drivers or {}).items())},
        "dimensions": sorted(
            f"{d.service_code}|{d.dimension_key}|{d.unit}|{d.quantity}|{d.formula}" for d in dimensions
        ),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build_estimate(
    snapshot: PriceSnapshot,
    dimensions: list[UsageDimension],
    *,
    workload_drivers: dict | None = None,
    region: str | None = None,
    authoritative: bool | None = None,
) -> SkuBackedEstimate:
    region = region or snapshot.region
    workload_drivers = workload_drivers or {}
    # Default to the snapshot's structural authority. Callers (e.g. the local-cache
    # adapter) may pass the provenance-validated authority for a stricter gate.
    authoritative = snapshot.is_authoritative if authoritative is None else bool(authoritative)

    estimate = SkuBackedEstimate(
        snapshot_id=snapshot.snapshot_id,
        snapshot_source=snapshot.source,
        snapshot_version_hash=snapshot.version_hash,
        region=region,
        currency=snapshot.currency,
        estimate_input_hash=estimate_input_hash(
            workload_drivers=workload_drivers, region=region, snapshot=snapshot, dimensions=dimensions
        ),
        snapshot_generated_at=snapshot.generated_at,
        snapshot_provenance=dict(snapshot.provenance) if snapshot.provenance else {},
    )

    sku_total = Decimal("0.00")
    directional_total = Decimal("0.00")

    for dim in dimensions:
        binding = bind_rate(snapshot, dim)
        rate = binding.rate_record
        if binding.status == BOUND and rate is not None:
            subtotal = _money(Decimal(dim.quantity) * Decimal(rate.rate))
            # A bound line is SKU-shaped; it is procurement-ready only with an authoritative snapshot.
            procurement_ready = authoritative
            line = SkuBackedLine(
                service_name=rate.service_name, service_code=rate.service_code, region=region,
                dimension_key=dim.dimension_key, usage_type=rate.usage_type, operation=rate.operation,
                sku=rate.sku, price_dimension_id=rate.price_dimension_id, unit=rate.unit,
                rate=Decimal(rate.rate), quantity=Decimal(dim.quantity),
                formula=dim.formula or f"{dim.quantity} {rate.unit} x {rate.rate}",
                monthly_subtotal=subtotal, evidence_class=SKU_TIER_BACKED, snapshot_id=snapshot.snapshot_id,
                snapshot_source=snapshot.source, procurement_ready=procurement_ready,
                required_for_headline=dim.required_for_headline, assumptions=dim.assumptions,
                reason="Exact single SKU/rate match." + ("" if authoritative else " Snapshot is a static fixture; not procurement-authoritative."),
            )
            sku_total += subtotal
        elif binding.status == AMBIGUOUS and rate is not None:
            subtotal = _money(Decimal(dim.quantity) * Decimal(rate.rate))
            line = SkuBackedLine(
                service_name=dim.service_name, service_code=dim.service_code, region=region,
                dimension_key=dim.dimension_key, usage_type=rate.usage_type, operation=rate.operation,
                sku=rate.sku, price_dimension_id=rate.price_dimension_id, unit=dim.unit,
                rate=Decimal(rate.rate), quantity=Decimal(dim.quantity),
                formula=dim.formula or f"{dim.quantity} {dim.unit} x {rate.rate} (candidate)",
                monthly_subtotal=subtotal, evidence_class=CATALOG_REFERENCED, snapshot_id=snapshot.snapshot_id,
                snapshot_source=snapshot.source, procurement_ready=False,
                required_for_headline=dim.required_for_headline, assumptions=dim.assumptions,
                reason=binding.reason,
            )
            directional_total += subtotal
        else:
            # missing_quantity / not_found / unsupported / unit_mismatch -> not estimated.
            line = SkuBackedLine(
                service_name=dim.service_name, service_code=dim.service_code, region=region,
                dimension_key=dim.dimension_key, usage_type=None, operation=None, sku=None,
                price_dimension_id=None, unit=dim.unit, rate=None, quantity=dim.quantity,
                formula=dim.formula, monthly_subtotal=None, evidence_class=NOT_ESTIMATED,
                snapshot_id=snapshot.snapshot_id, snapshot_source=snapshot.source, procurement_ready=False,
                required_for_headline=dim.required_for_headline, assumptions=dim.assumptions,
                reason=binding.reason,
            )
            estimate.not_estimated.append(f"{dim.service_name}:{dim.dimension_key} ({binding.status})")
        estimate.lines.append(line)

    estimate.sku_backed_subtotal = _money(sku_total)
    estimate.directional_subtotal = _money(directional_total)
    estimate.heuristic_subtotal = Decimal("0.00")

    required_lines = [ln for ln in estimate.lines if ln.required_for_headline]
    all_required_sku_backed = bool(required_lines) and all(ln.evidence_class == SKU_TIER_BACKED for ln in required_lines)
    all_required_have_qty = all(ln.quantity is not None for ln in required_lines)

    # No fake readiness: requires every required line SKU-backed, quantities confirmed,
    # AND an authoritative snapshot (a static fixture can never be procurement-ready).
    estimate.procurement_ready = bool(all_required_sku_backed and all_required_have_qty and authoritative)
    estimate.headline_safe = estimate.procurement_ready
    return estimate
