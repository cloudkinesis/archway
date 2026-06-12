"""Supplemental SKU pilot trace export (JSON / CSV / Markdown).

These artifacts are ADDITIVE and SUPPLEMENTAL. They never replace the legacy
pricing totals and never promote global readiness. The Markdown summary states the
honest caveats explicitly: rate authority vs quantity confidence, supplemental-only,
non-authoritative fixtures, and the EventBridge 64KB-chunk limitation.

DEPENDS ON: app.services.dossier_manifest.stable_json_hash (one-directional import).
"""

from __future__ import annotations

import csv
import io
import json

from app.services.dossier_manifest import stable_json_hash
from app.services.sku_pricing.official_snapshot_builder import UNSUPPORTED_OFFICIAL_DIMENSIONS

CSV_COLUMNS = [
    "service_name", "service_code", "usage_purpose", "dimension_key", "region",
    "usage_type", "operation", "sku", "price_dimension_id", "unit", "official_unit",
    "rate", "quantity", "formula", "monthly_subtotal", "evidence_class",
    "rate_authoritative", "quantities_confirmed", "procurement_ready",
    "snapshot_id", "source_hash", "estimate_input_hash", "assumptions", "reason",
]


def pilot_trace_hash(pilot: dict) -> str:
    """Stable content hash of the pilot trace (matches what the manifest records)."""
    return stable_json_hash(pilot)


def _eventbridge_applicable(pilot: dict) -> bool:
    not_estimated = " ".join(pilot.get("not_estimated") or []).lower()
    line_keys = {ln.get("dimension_key") for ln in pilot.get("lines") or []}
    return "eventbridge" in not_estimated or "eventbridge_custom_events" in line_keys


def build_pilot_trace_json(pilot: dict) -> str:
    payload = {
        "schema": "sku_pricing_pilot_trace_v1",
        "supplemental": True,
        "disclaimer": (
            "Supplemental SKU-backed pilot trace. Does not replace the legacy pricing estimate "
            "and does not change global headline_safe / procurement_ready."
        ),
        "trace": pilot,
        "trace_hash": pilot_trace_hash(pilot),
    }
    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"


def build_pilot_trace_csv(pilot: dict) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    source_hash = pilot.get("source_hash")
    estimate_input_hash = pilot.get("estimate_input_hash")
    snapshot_id = pilot.get("snapshot_id")
    for line in pilot.get("lines") or []:
        writer.writerow({
            "service_name": line.get("service_name"),
            "service_code": line.get("service_code"),
            "usage_purpose": line.get("usage_purpose"),
            "dimension_key": line.get("dimension_key"),
            "region": line.get("region"),
            "usage_type": line.get("usage_type"),
            "operation": line.get("operation"),
            "sku": line.get("sku"),
            "price_dimension_id": line.get("price_dimension_id"),
            "unit": line.get("unit"),
            "official_unit": line.get("official_unit", ""),
            "rate": line.get("rate"),
            "quantity": line.get("quantity"),
            "formula": line.get("formula"),
            "monthly_subtotal": line.get("monthly_subtotal"),
            "evidence_class": line.get("evidence_class"),
            "rate_authoritative": line.get("rate_authoritative"),
            "quantities_confirmed": line.get("quantities_confirmed"),
            "procurement_ready": line.get("procurement_ready"),
            "snapshot_id": snapshot_id,
            "source_hash": source_hash,
            "estimate_input_hash": estimate_input_hash,
            "assumptions": "; ".join(line.get("assumptions") or []),
            "reason": line.get("reason"),
        })
    return buffer.getvalue()


def build_pilot_trace_markdown(pilot: dict) -> str:
    authoritative = bool(pilot.get("snapshot_authoritative")) and bool(pilot.get("rate_authoritative"))
    quantities_confirmed = bool(pilot.get("quantities_confirmed"))
    lines = [
        "# SKU-backed Pilot Pricing — Supplemental Trace",
        "",
        "**Supplemental SKU-backed pilot trace.** Legacy pricing totals are unchanged.",
        "Does not replace the legacy estimate. Does not change global headline/procurement readiness.",
        "",
        f"- Status: {pilot.get('status')}",
        f"- Workload: {pilot.get('workload')}",
        f"- SKU-backed subtotal: {pilot.get('sku_backed_subtotal')}",
        f"- Rate authoritative: {str(bool(pilot.get('rate_authoritative'))).lower()}",
        f"- Quantities confirmed: {str(quantities_confirmed).lower()} (source: {pilot.get('quantity_source')})",
        f"- Pilot estimate ready: {str(bool(pilot.get('sku_pilot_estimate_ready'))).lower()}",
        f"- Pilot procurement-ready: {str(bool(pilot.get('sku_pilot_procurement_ready'))).lower()}",
        "- Global procurement-ready: unchanged",
        f"- Snapshot: {pilot.get('snapshot_id')} ({pilot.get('snapshot_source')})",
        f"- Source hash: {pilot.get('source_hash')}",
        f"- Estimate input hash: {pilot.get('estimate_input_hash')}",
        "",
    ]
    if not authoritative:
        lines += [
            "> This trace is not authoritative and must not be used as a procurement estimate.",
            "",
        ]
    elif not quantities_confirmed:
        lines += [
            "> Rates are authoritative, but quantities are assumed. This is not procurement-ready.",
            "",
        ]
    not_estimated = pilot.get("not_estimated") or []
    if not_estimated:
        lines += ["## Not estimated", *[f"- {item}" for item in not_estimated], ""]
    if _eventbridge_applicable(pilot):
        reason = UNSUPPORTED_OFFICIAL_DIMENSIONS.get(
            "eventbridge_custom_events",
            "AWS bills custom events per 64KB chunks, not raw events.",
        )
        lines += [
            "## EventBridge",
            f"EventBridge not estimated because AWS bills 64KB chunks, not raw events. {reason}",
            "",
        ]
    lines += ["## Line items", ""]
    for line in pilot.get("lines") or []:
        lines.append(
            f"- {line.get('service_name')} · {line.get('dimension_key')}: "
            f"{line.get('evidence_class')}; qty={line.get('quantity')} {line.get('unit')}; "
            f"rate={line.get('rate')}; subtotal={line.get('monthly_subtotal')}; "
            f"rate_authoritative={line.get('rate_authoritative')}; reason={line.get('reason')}"
        )
    lines.append("")
    return "\n".join(lines)


def build_pilot_trace_files(pilot: dict) -> dict[str, str]:
    """Return the three supplemental SKU pilot export artifacts as strings."""
    return {
        "json": build_pilot_trace_json(pilot),
        "csv": build_pilot_trace_csv(pilot),
        "md": build_pilot_trace_markdown(pilot),
    }
