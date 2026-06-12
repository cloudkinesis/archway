"""Tests for scripts/verify_solution_dossier.py (offline package verification)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from app.services.dossier_manifest import MANIFEST_FILENAME, build_dossier_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ["README.md", "manifest.json", "01-solution-brief.md", "03-pricing.md",
            "raw/pricing.json", "raw/session.json"]


def _load_script(name, relpath):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relpath)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


verifier = _load_script("verify_solution_dossier", "scripts/verify_solution_dossier.py")

_PRICING = {"low_monthly_usd": 100, "expected_monthly_usd": 150, "high_monthly_usd": 200,
            "metadata": {"pricing_can_be_displayed_as_headline": True,
                         "pricing_ledger": {"summary": {"headline_safe": True, "procurement_ready": False}},
                         "pricing_driver_closure": {"status": "directional"}, "canonical_facts": {}}}
_REPORT = {"executive_verdict": "v", "evidence_items": [], "metadata": {"customer_readiness": {"status": "customer_ready"}}}
_ARCH = [{"mode": "poc", "components": [{"service": "AWSLambda"}], "metadata": {"pattern_id": "rag"}}]


def _build_package(tmp_path: Path) -> Path:
    export = tmp_path / "export"
    (export / "raw").mkdir(parents=True)
    for rel in REQUIRED:
        (export / rel).write_text(f"content {rel}\n", encoding="utf-8")
    manifest = build_dossier_manifest(
        export, session_id="s", export_name="pkg", generated_at="2026-06-09T00:00:00+00:00",
        session_input="x", brief={"use_case_profile": {}}, report=_REPORT, pricing=_PRICING,
        architectures=_ARCH, architecture_revisions=[], diagrams=[], warnings=[],
        feature_flags={}, convergence_status="passed",
    )
    (export / MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return export


# 10 — verifier passes for a valid package ------------------------------------
def test_verifier_passes_for_valid_package(tmp_path):
    export = _build_package(tmp_path)
    ok, errors, _ = verifier.verify(export)
    assert ok, errors
    assert verifier.main([str(export)]) == 0


# 11 — verifier fails when an artifact's bytes change -------------------------
def test_verifier_fails_on_hash_mismatch(tmp_path):
    export = _build_package(tmp_path)
    (export / "03-pricing.md").write_text("TAMPERED CONTENT\n", encoding="utf-8")
    ok, errors, _ = verifier.verify(export)
    assert not ok
    assert any("hash mismatch" in e for e in errors)
    assert verifier.main([str(export)]) == 1


# 12 — verifier fails when a required artifact is missing ---------------------
def test_verifier_fails_on_missing_required_artifact(tmp_path):
    export = _build_package(tmp_path)
    (export / "03-pricing.md").unlink()
    ok, errors, _ = verifier.verify(export)
    assert not ok
    assert any("03-pricing.md" in e for e in errors)


# extra — verifier rejects an SKU-procurement-ready-with-assumed-quantities manifest
def test_verifier_rejects_dishonest_sku_readiness(tmp_path):
    export = _build_package(tmp_path)
    manifest = json.loads((export / MANIFEST_FILENAME).read_text())
    manifest["pricing"]["sku_pilot"] = {
        "sku_trace_hash": "sha256:x", "source_hash": "sha256:y", "snapshot_id": "snap",
        "quantities_confirmed": False, "sku_pilot_procurement_ready": True,
    }
    (export / MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    ok, errors, _ = verifier.verify(export)
    assert not ok
    assert any("procurement_ready" in e and "quantities_confirmed=false" in e for e in errors)


# extra — partial SKU provenance warns by default, fails under --strict --------
def test_verifier_partial_provenance_warns_then_fails_strict(tmp_path):
    export = _build_package(tmp_path)
    manifest = json.loads((export / MANIFEST_FILENAME).read_text())
    manifest["pricing"]["sku_pilot"] = {
        "sku_trace_hash": "sha256:x", "source_hash": "sha256:y", "snapshot_id": "snap",
        "quantities_confirmed": False, "sku_pilot_procurement_ready": False,
        "rate_authoritative": True, "provenance_status": "partial",
    }
    (export / MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    ok, errors, notes = verifier.verify(export)  # non-strict
    assert ok
    assert any("provenance partial" in n.lower() for n in notes)

    ok_strict, errors_strict, _ = verifier.verify(export, strict=True)
    assert not ok_strict
    assert any("provenance partial" in e.lower() for e in errors_strict)
    assert verifier.main([str(export), "--strict"]) == 1
