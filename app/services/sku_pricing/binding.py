"""Fail-closed SKU/rate binding.

A usage dimension binds to a snapshot rate only when exactly one rate matches the
dimension key AND the billable unit matches. Everything else (missing quantity,
no match, multiple matches, unit mismatch, unsupported service) is reported with a
status and reason and must NOT be treated as SKU-backed headline pricing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.services.sku_pricing.snapshot import PriceSnapshot, RateRecord, _canonical_unit

# Binding statuses.
BOUND = "bound"
AMBIGUOUS = "ambiguous"
NOT_FOUND = "not_found"
UNSUPPORTED = "unsupported"
UNIT_MISMATCH = "unit_mismatch"
MISSING_QUANTITY = "missing_quantity"


@dataclass(frozen=True)
class UsageDimension:
    service_name: str
    service_code: str
    dimension_key: str
    unit: str
    quantity: Decimal | None     # None => required workload driver is missing
    formula: str = ""
    assumptions: tuple[str, ...] = ()
    required_for_headline: bool = True


@dataclass(frozen=True)
class RateBinding:
    status: str
    reason: str
    rate_record: RateRecord | None = None
    candidate_count: int = 0


def bind_rate(snapshot: PriceSnapshot, dimension: UsageDimension) -> RateBinding:
    if dimension.quantity is None:
        return RateBinding(MISSING_QUANTITY, "Required workload driver / quantity is missing.")

    if dimension.service_name not in snapshot.services and dimension.service_code not in {r.service_code for r in snapshot.rates}:
        return RateBinding(UNSUPPORTED, f"Service '{dimension.service_name}' is not present in snapshot {snapshot.snapshot_id}.")

    candidates = snapshot.rates_for(dimension.dimension_key)
    if not candidates:
        return RateBinding(NOT_FOUND, f"No rate for dimension_key '{dimension.dimension_key}' in region {snapshot.region}.")

    want_unit = _canonical_unit(dimension.unit)
    unit_matched = [r for r in candidates if r.canonical_unit == want_unit]
    if not unit_matched:
        found_units = sorted({r.unit for r in candidates})
        return RateBinding(
            UNIT_MISMATCH,
            f"Dimension unit '{dimension.unit}' does not match available rate unit(s) {found_units}.",
            candidate_count=len(candidates),
        )
    if len(unit_matched) > 1:
        # Do not silently pick one; show a candidate for traceability but mark ambiguous.
        return RateBinding(
            AMBIGUOUS,
            f"{len(unit_matched)} rates matched dimension_key '{dimension.dimension_key}' with unit '{dimension.unit}'; binding is ambiguous.",
            rate_record=unit_matched[0],
            candidate_count=len(unit_matched),
        )
    return RateBinding(BOUND, "Exactly one rate matched the usage dimension.", rate_record=unit_matched[0], candidate_count=1)
