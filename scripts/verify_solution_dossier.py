#!/usr/bin/env python3
"""Offline verifier for an Archway solution dossier export package.

Usage:
    python scripts/verify_solution_dossier.py /path/to/export-package

Loads `dossier_manifest.json`, recomputes every artifact hash in the inventory,
confirms required artifacts exist, and (when an SKU pilot is present) confirms the
SKU trace hash and pricing snapshot/source-hash fields are present. Prints a readable
summary. Exit 0 when valid; non-zero on missing required artifact or hash mismatch.

NO network. NO AWS credentials. NO regeneration. Package verification only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

MANIFEST_FILENAME = "dossier_manifest.json"
EXPECTED_SCHEMA = "dossier_manifest_v1"


def _hash_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _load_manifest(package: Path) -> tuple[dict, Path]:
    if package.is_file() and package.name == MANIFEST_FILENAME:
        manifest_path = package
        root = package.parent
    else:
        manifest_path = package / MANIFEST_FILENAME
        root = package
    if not manifest_path.is_file():
        raise FileNotFoundError(f"{MANIFEST_FILENAME} not found at {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8")), root


def verify(package: Path, *, strict: bool = False) -> tuple[bool, list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []
    manifest, root = _load_manifest(package)

    schema = manifest.get("schema_version")
    if schema != EXPECTED_SCHEMA:
        errors.append(f"unexpected schema_version: {schema!r} (expected {EXPECTED_SCHEMA!r})")

    inventory = manifest.get("artifact_inventory") or []
    checked = mismatched = missing = 0
    for item in inventory:
        rel = item.get("path")
        status = item.get("status")
        expected = item.get("sha256")
        target = root / rel
        if status != "present":
            if item.get("required"):
                errors.append(f"required artifact recorded as {status}: {rel}")
                missing += 1
            continue
        if not target.is_file():
            errors.append(f"artifact listed but missing on disk: {rel}")
            missing += 1
            continue
        actual = _hash_file(target)
        checked += 1
        if expected and actual != expected:
            errors.append(f"hash mismatch: {rel}\n    expected {expected}\n    actual   {actual}")
            mismatched += 1
    notes.append(f"artifacts checked: {checked}, mismatched: {mismatched}, missing: {missing}")

    # Required artifacts present?
    present_paths = {Path(root / i["path"]).is_file() for i in inventory if i.get("status") == "present"}
    for item in inventory:
        if item.get("required") and item.get("status") == "present" and not (root / item["path"]).is_file():
            errors.append(f"required artifact missing: {item['path']}")

    # SKU pilot integrity checks.
    sku = (manifest.get("pricing") or {}).get("sku_pilot")
    if sku:
        notes.append("SKU pilot present.")
        if not sku.get("sku_trace_hash"):
            errors.append("SKU pilot present but sku_trace_hash is missing from the manifest")
        if not sku.get("source_hash"):
            errors.append("SKU pilot present but pricing snapshot source_hash is missing")
        if not sku.get("snapshot_id"):
            errors.append("SKU pilot present but snapshot_id is missing")
        # Cross-check the exported trace file hash if present.
        trace_path = root / "pricing/sku_pricing_pilot_trace.json"
        if trace_path.is_file():
            try:
                payload = json.loads(trace_path.read_text(encoding="utf-8"))
                if payload.get("trace_hash") and payload["trace_hash"] != sku.get("sku_trace_hash"):
                    errors.append("sku_trace_hash mismatch between manifest and exported trace file")
            except json.JSONDecodeError:
                errors.append("pricing/sku_pricing_pilot_trace.json is not valid JSON")
        # Honesty guard: assumed quantities must never read as procurement-ready.
        if sku.get("sku_pilot_procurement_ready") and not sku.get("quantities_confirmed"):
            errors.append("manifest claims sku_pilot_procurement_ready with quantities_confirmed=false")
        # Provenance completeness: authoritative rates must carry upstream_source + version_hash.
        provenance_status = sku.get("provenance_status")
        if provenance_status == "partial":
            message = ("SKU provenance partial: rate_authoritative=true but upstream_source/version_hash "
                       "is missing from the snapshot metadata")
            if strict:
                errors.append(message + " (strict mode)")
            else:
                notes.append("WARNING: " + message)
    else:
        notes.append("No SKU pilot present (recorded as absent).")

    return (not errors), errors, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an Archway solution dossier export package (offline).")
    parser.add_argument("package", help="Path to the export package directory (or its dossier_manifest.json)")
    parser.add_argument("--strict", action="store_true",
                        help="Treat partial SKU provenance (missing upstream_source/version_hash) as a failure.")
    args = parser.parse_args(argv)

    package = Path(args.package)
    if not package.exists():
        print(f"error: path not found: {package}", file=sys.stderr)
        return 2

    try:
        ok, errors, notes = verify(package, strict=args.strict)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    manifest, _ = _load_manifest(package)
    print(f"Dossier: {manifest.get('dossier_id')}")
    print(f"Schema:  {manifest.get('schema_version')}")
    print(f"Overall status: {manifest.get('overall_status')}")
    for note in notes:
        print(f"  - {note}")
    if ok:
        print("RESULT: VALID — all listed artifacts present and hashes match.")
        return 0
    print("RESULT: INVALID")
    for err in errors:
        print(f"  ✗ {err}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
