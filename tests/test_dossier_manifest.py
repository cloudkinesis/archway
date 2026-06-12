"""Tests for the verifiable dossier manifest builder."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.dossier_manifest import (
    MANIFEST_FILENAME,
    build_dossier_manifest,
    stable_json_hash,
)
from app.services.sku_pricing.official_snapshot_builder import UNSUPPORTED_OFFICIAL_DIMENSIONS

REQUIRED = ["README.md", "manifest.json", "01-solution-brief.md", "03-pricing.md",
            "raw/pricing.json", "raw/session.json"]


def _seed_export(tmp_path: Path) -> Path:
    export = tmp_path / "export"
    (export / "raw").mkdir(parents=True)
    for rel in REQUIRED:
        (export / rel).write_text(f"content of {rel}\n", encoding="utf-8")
    return export


def _pilot(*, procurement_ready=False, quantities_confirmed=False):
    return {
        "enabled": True, "status": "completed", "workload": "legal_document_rag_poc",
        "snapshot_id": "aws-price-list-us-east-1-abc123", "snapshot_source": "local_cache",
        "snapshot_authoritative": True, "source_hash": "sha256:deadbeefcafe",
        "estimate_input_hash": "feedface00", "sku_backed_subtotal": "1.73", "directional_subtotal": "0.00",
        "not_estimated": ["Amazon EventBridge:eventbridge_custom_events (not_found)"],
        "rate_authoritative": True, "quantities_confirmed": quantities_confirmed,
        "quantity_source": "user_confirmed" if quantities_confirmed else "assumed",
        "quantity_confidence": "confirmed" if quantities_confirmed else "assumed",
        "sku_pilot_estimate_ready": True, "sku_pilot_procurement_ready": procurement_ready,
        "lines": [{"service_name": "Amazon S3", "dimension_key": "s3_standard_storage_gb_month",
                   "evidence_class": "sku_tier_backed", "rate_authoritative": True, "quantities_confirmed": quantities_confirmed,
                   "quantity": "19.53", "unit": "GB-Mo", "rate": "0.023", "monthly_subtotal": "0.45", "reason": "ok"}],
        "note": "supplemental",
    }


def _pricing(*, sku=None, headline=True, canonical_facts=None):
    md = {
        "pricing_can_be_displayed_as_headline": headline,
        "pricing_ledger": {"summary": {"headline_safe": headline, "procurement_ready": False,
                                       "sku_tier_backed_subtotal": 0, "heuristic_subtotal": 150}},
        "pricing_driver_closure": {"status": "directional"},
        "canonical_facts": canonical_facts if canonical_facts is not None else {"facts": [{"name": "asset_count"}]},
    }
    if sku is not None:
        md["sku_pricing_pilot"] = sku
    return {"low_monthly_usd": 100, "expected_monthly_usd": 150, "high_monthly_usd": 200, "metadata": md}


_REPORT = {"executive_verdict": "verdict", "facts": [], "recommendations": [],
           "evidence_items": [{"id": "E1"}], "metadata": {"customer_readiness": {"status": "customer_ready", "warnings": [], "blockers": []}}}
_ARCH = [{"mode": "poc", "title": "POC", "components": [{"service": "AWSLambda"}], "governance_controls": [], "metadata": {"pattern_id": "rag"}}]


def _build(export, pricing, **kw):
    return build_dossier_manifest(
        export, session_id="sess1", export_name="pkg-1",
        generated_at=kw.pop("generated_at", "2026-06-09T00:00:00+00:00"),
        session_input="Build a legal RAG assistant.", brief={"use_case_profile": {"domain": "legal", "workload_families": ["rag_assistant"]}},
        report=_REPORT, pricing=pricing, architectures=_ARCH, architecture_revisions=[{"version": 2}],
        diagrams=[], warnings=[], feature_flags={"enable_sku_pricing_pilot": bool(pricing.get("metadata", {}).get("sku_pricing_pilot"))},
        convergence_status="passed",
        sku_trace_hash=kw.pop("sku_trace_hash", None),
        unsupported_dimensions=kw.pop("unsupported_dimensions", None),
    )


# 1 — stable hash deterministic ------------------------------------------------
def test_manifest_stable_hash_deterministic(tmp_path):
    export = _seed_export(tmp_path)
    m1 = _build(export, _pricing())
    m2 = _build(export, _pricing())
    assert stable_json_hash({"a": 1, "b": [2, 3]}) == stable_json_hash({"b": [2, 3], "a": 1})
    assert stable_json_hash(m1["inputs"]) == stable_json_hash(m2["inputs"])
    assert stable_json_hash(m1["pricing"]) == stable_json_hash(m2["pricing"])
    assert stable_json_hash(m1["artifact_inventory"]) == stable_json_hash(m2["artifact_inventory"])


# 2 — different canonical facts change the canonical facts hash ----------------
def test_different_canonical_facts_change_hash(tmp_path):
    export = _seed_export(tmp_path)
    a = _build(export, _pricing(canonical_facts={"facts": [{"name": "asset_count"}]}))
    b = _build(export, _pricing(canonical_facts={"facts": [{"name": "daily_events"}]}))
    assert a["inputs"]["canonical_facts_hash"] != b["inputs"]["canonical_facts_hash"]


# 3 & 4 — snapshot + trace hash appear when SKU pilot exists -------------------
def test_pricing_snapshot_and_trace_hash_present_with_sku_pilot(tmp_path):
    export = _seed_export(tmp_path)
    m = _build(export, _pricing(sku=_pilot()), sku_trace_hash="sha256:tracehash")
    sku = m["pricing"]["sku_pilot"]
    assert sku is not None
    assert sku["source_hash"] == "sha256:deadbeefcafe"
    assert sku["snapshot_id"] == "aws-price-list-us-east-1-abc123"
    assert sku["sku_trace_hash"] == "sha256:tracehash"


# 5 — manifest separates global readiness from SKU pilot readiness ------------
def test_manifest_separates_global_and_sku_readiness(tmp_path):
    export = _seed_export(tmp_path)
    m = _build(export, _pricing(sku=_pilot()), sku_trace_hash="sha256:x")
    global_section = m["pricing"]["global"]
    sku = m["pricing"]["sku_pilot"]
    # Global has no SKU axes; SKU has its own.
    assert "rate_authoritative" not in global_section
    assert "quantities_confirmed" not in global_section
    assert {"rate_authoritative", "quantities_confirmed", "sku_pilot_procurement_ready"} <= set(sku)
    # Distinct fields for global vs pilot procurement-ready.
    assert global_section["procurement_ready"] is False
    assert sku["sku_pilot_procurement_ready"] is False


def test_manifest_headline_safety_fails_closed_when_missing_or_null(tmp_path):
    export = _seed_export(tmp_path)

    missing_flag = _pricing()
    missing_flag["metadata"].pop("pricing_can_be_displayed_as_headline")
    m_missing = _build(export, missing_flag)
    assert m_missing["pricing"]["global"]["pricing_can_be_displayed_as_headline"] is False

    null_flag = _pricing()
    null_flag["metadata"]["pricing_can_be_displayed_as_headline"] = None
    m_null = _build(export, null_flag)
    assert m_null["pricing"]["global"]["pricing_can_be_displayed_as_headline"] is False


# 6 — assumed quantities never produce procurement-ready -----------------------
def test_assumed_quantities_never_procurement_ready(tmp_path):
    export = _seed_export(tmp_path)
    m = _build(export, _pricing(sku=_pilot(procurement_ready=False, quantities_confirmed=False)), sku_trace_hash="sha256:x")
    sku = m["pricing"]["sku_pilot"]
    assert sku["rate_authoritative"] is True
    assert sku["quantities_confirmed"] is False
    assert sku["sku_pilot_procurement_ready"] is False
    # Global readiness unchanged and not promoted.
    assert m["pricing"]["global"]["procurement_ready"] is False
    assert m["overall_status"] in {"ready", "ready_with_warnings", "directional_only"}


# provenance — complete vs partial -------------------------------------------
def test_sku_provenance_status_complete_and_partial(tmp_path):
    export = _seed_export(tmp_path)
    # Complete: rate authoritative + upstream_source + version_hash + source_hash.
    full = dict(_pilot(), upstream_source="aws_price_list_bulk_api", version_hash="v1234")
    m_full = _build(export, _pricing(sku=full), sku_trace_hash="sha256:x")
    sku_full = m_full["pricing"]["sku_pilot"]
    assert sku_full["provenance_status"] == "complete"
    assert sku_full["upstream_source"] == "aws_price_list_bulk_api"
    assert sku_full["version_hash"] == "v1234"
    # Partial: authoritative rate but upstream_source/version_hash missing.
    m_partial = _build(export, _pricing(sku=_pilot()), sku_trace_hash="sha256:x")
    assert m_partial["pricing"]["sku_pilot"]["provenance_status"] == "partial"


# 16 — EventBridge unsupported reason preserved when present ------------------
def test_eventbridge_unsupported_reason_preserved(tmp_path):
    export = _seed_export(tmp_path)
    m = _build(export, _pricing(sku=_pilot()), sku_trace_hash="sha256:x",
               unsupported_dimensions=dict(UNSUPPORTED_OFFICIAL_DIMENSIONS))
    unsupported = m["pricing"]["sku_pilot"]["unsupported_dimensions"]
    assert "eventbridge_custom_events" in unsupported
    assert "64K-Chunks" in unsupported["eventbridge_custom_events"]


# extra — manifest written to disk loads as valid JSON with inventory ---------
def test_manifest_inventory_excludes_itself_and_lists_artifacts(tmp_path):
    export = _seed_export(tmp_path)
    m = _build(export, _pricing())
    (export / MANIFEST_FILENAME).write_text(json.dumps(m, indent=2, sort_keys=True), encoding="utf-8")
    paths = {i["path"] for i in m["artifact_inventory"]}
    assert MANIFEST_FILENAME not in paths  # no self-recursion
    assert "03-pricing.md" in paths
    assert all(i["status"] == "present" for i in m["artifact_inventory"] if i["required"])
