"""Tests for scripts/diff_solution_dossiers.py (offline manifest-level diff)."""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name, relpath):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relpath)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


differ = _load_script("diff_solution_dossiers", "scripts/diff_solution_dossiers.py")


def _manifest():
    return {
        "dossier_id": "pkg",
        "inputs": {"raw_user_input_hash": "sha256:i", "canonical_facts_hash": "sha256:c"},
        "research": {"summary_hash": "sha256:r"},
        "pricing": {
            "global": {"low_monthly_usd": 100, "expected_monthly_usd": 150, "high_monthly_usd": 200},
            "sku_pilot": {"sku_backed_subtotal": "1.73", "source_hash": "sha256:s",
                          "sku_trace_hash": "sha256:t", "sku_pilot_procurement_ready": False},
        },
        "architecture": {"spec_hash": "sha256:a", "service_inventory_hash": "sha256:svc"},
        "diagrams": [{"mode": "poc", "view_id": "service_flow", "d2_source_hash": "sha256:d2",
                      "image_hash": "sha256:svg", "validation_status": "passed"}],
        "readiness_gates": {"blockers": [], "warnings": []},
        "overall_status": "ready",
    }


# 13 — diff detects SKU subtotal delta ----------------------------------------
def test_diff_detects_sku_subtotal_delta():
    old = _manifest()
    new = copy.deepcopy(old)
    new["pricing"]["sku_pilot"]["sku_backed_subtotal"] = "2.50"
    report = "\n".join(differ.diff(old, new))
    assert "SKU pilot subtotal delta" in report
    assert "1.73" in report and "2.50" in report


# 14 — diff detects pricing snapshot hash change ------------------------------
def test_diff_detects_snapshot_hash_change():
    old = _manifest()
    new = copy.deepcopy(old)
    new["pricing"]["sku_pilot"]["source_hash"] = "sha256:NEW"
    report = "\n".join(differ.diff(old, new))
    assert "pricing snapshot source_hash: changed" in report


# 15 — diff detects architecture + diagram hash change ------------------------
def test_diff_detects_architecture_and_diagram_change():
    old = _manifest()
    new = copy.deepcopy(old)
    new["architecture"]["spec_hash"] = "sha256:ARCH2"
    new["diagrams"][0]["image_hash"] = "sha256:SVG2"
    report = "\n".join(differ.diff(old, new))
    assert "architecture spec hash: changed" in report
    assert "diagram changed: poc/service_flow" in report


# extra — diff surfaces new/resolved blockers + status change -----------------
def test_diff_surfaces_blockers_and_status():
    old = _manifest()
    new = copy.deepcopy(old)
    new["overall_status"] = "blocked"
    new["readiness_gates"]["blockers"] = ["raw/pricing.json"]
    report = "\n".join(differ.diff(old, new))
    assert "overall status: changed" in report
    assert "NEW blocker: raw/pricing.json" in report


# extra — identical manifests produce no tracked differences ------------------
def test_diff_no_changes():
    old = _manifest()
    assert differ.diff(old, copy.deepcopy(old)) == []
