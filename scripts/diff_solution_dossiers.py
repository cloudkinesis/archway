#!/usr/bin/env python3
"""Diff two Archway solution dossiers (offline).

Usage:
    python scripts/diff_solution_dossiers.py old_export/ new_export/
    python scripts/diff_solution_dossiers.py old_manifest.json new_manifest.json

Compares trust/provenance signals between two dossier manifests and prints a concise
report: input changed, pricing changed, SKU subtotal delta, snapshot/trace hash change,
architecture changed, diagrams changed, readiness changed, new/resolved blockers.

This is a manifest-level diff. It does NOT recompute pricing, regenerate anything,
or perform a semantic architecture diff. NO network.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

MANIFEST_FILENAME = "dossier_manifest.json"


def _load(path: Path) -> dict:
    if path.is_dir():
        path = path / MANIFEST_FILENAME
    if not path.is_file():
        raise FileNotFoundError(f"manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _num(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _changed(label: str, old, new) -> list[str]:
    return [f"{label}: changed", f"    old: {old}", f"    new: {new}"] if old != new else []


def _diagram_map(manifest: dict) -> dict:
    out = {}
    for d in manifest.get("diagrams") or []:
        out[f"{d.get('mode')}/{d.get('view_id')}"] = (d.get("d2_source_hash"), d.get("image_hash"), d.get("validation_status"))
    return out


def diff(old: dict, new: dict) -> list[str]:
    report: list[str] = []
    op, np_ = old.get("pricing", {}), new.get("pricing", {})
    og, ng = op.get("global", {}) or {}, np_.get("global", {}) or {}
    osku, nsku = op.get("sku_pilot") or {}, np_.get("sku_pilot") or {}

    # Inputs
    oi, ni = old.get("inputs", {}), new.get("inputs", {})
    report += _changed("input (raw user input hash)", oi.get("raw_user_input_hash"), ni.get("raw_user_input_hash"))
    report += _changed("canonical facts hash", oi.get("canonical_facts_hash"), ni.get("canonical_facts_hash"))
    report += _changed("research summary hash", (old.get("research") or {}).get("summary_hash"), (new.get("research") or {}).get("summary_hash"))

    # Legacy pricing totals
    for key in ("low_monthly_usd", "expected_monthly_usd", "high_monthly_usd"):
        report += _changed(f"legacy pricing {key}", og.get(key), ng.get(key))

    # SKU pilot
    old_sub, new_sub = _num(osku.get("sku_backed_subtotal")), _num(nsku.get("sku_backed_subtotal"))
    if old_sub is not None and new_sub is not None and old_sub != new_sub:
        report.append(f"SKU pilot subtotal delta: {old_sub} -> {new_sub} (Δ {new_sub - old_sub})")
    elif bool(osku) != bool(nsku):
        report.append(f"SKU pilot presence changed: {bool(osku)} -> {bool(nsku)}")
    report += _changed("pricing snapshot source_hash", osku.get("source_hash"), nsku.get("source_hash"))
    report += _changed("SKU trace hash", osku.get("sku_trace_hash"), nsku.get("sku_trace_hash"))
    report += _changed("SKU pilot procurement-ready", osku.get("sku_pilot_procurement_ready"), nsku.get("sku_pilot_procurement_ready"))

    # Architecture
    oa, na = old.get("architecture", {}), new.get("architecture", {})
    report += _changed("architecture spec hash", oa.get("spec_hash"), na.get("spec_hash"))
    report += _changed("service inventory hash", oa.get("service_inventory_hash"), na.get("service_inventory_hash"))

    # Diagrams
    odm, ndm = _diagram_map(old), _diagram_map(new)
    for key in sorted(set(odm) | set(ndm)):
        if odm.get(key) != ndm.get(key):
            report.append(f"diagram changed: {key} ({odm.get(key)} -> {ndm.get(key)})")

    # Readiness gates + blockers
    og2, ng2 = old.get("readiness_gates", {}), new.get("readiness_gates", {})
    report += _changed("overall status", old.get("overall_status"), new.get("overall_status"))
    old_block, new_block = set(og2.get("blockers") or []), set(ng2.get("blockers") or [])
    for b in sorted(new_block - old_block):
        report.append(f"NEW blocker: {b}")
    for b in sorted(old_block - new_block):
        report.append(f"resolved blocker: {b}")
    old_warn, new_warn = set(og2.get("warnings") or []), set(ng2.get("warnings") or [])
    if old_warn != new_warn:
        report.append(f"warnings changed: {len(old_warn)} -> {len(new_warn)}")

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diff two Archway solution dossiers (offline, manifest-level).")
    parser.add_argument("old", help="Old export dir or dossier_manifest.json")
    parser.add_argument("new", help="New export dir or dossier_manifest.json")
    args = parser.parse_args(argv)

    try:
        old, new = _load(Path(args.old)), _load(Path(args.new))
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report = diff(old, new)
    print(f"Dossier diff: {old.get('dossier_id')}  ->  {new.get('dossier_id')}")
    if not report:
        print("No tracked differences.")
    else:
        for line in report:
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
