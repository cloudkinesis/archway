"""Pilot integration: supplemental SKU-backed trace on legal/document RAG pricing.

The pilot is flag-gated (ARCHWAY_ENABLE_SKU_PRICING_PILOT, default off), additive
(metadata only), fail-closed, and offline (uses the committed local-cache fixture;
no network / AWS creds / MCP). It must never change PricingAnalysis totals or the
global headline/procurement readiness.

DEPENDS ON: feature/sku-backed-pricing-foundation @ 9b168d7,
            feature/sku-pricing-local-cache-adapter @ efe0849.
"""

import asyncio
import os
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.models.domain import UseCaseBrief
from app.services.pricing import PricingEngine

LOCAL_CACHE = str(Path("tests/fixtures/sku_pricing/local_cache_snapshot_us_east_1.json").resolve())
STATIC_FIXTURE = str(Path("tests/fixtures/sku_pricing/snapshot_us_east_1_fixture.json").resolve())

FLAG = "ARCHWAY_ENABLE_SKU_PRICING_PILOT"
PATH_ENV = "ARCHWAY_SKU_PRICING_SNAPSHOT_PATH"


@pytest.fixture(autouse=True)
def _clean_settings():
    for key in (FLAG, PATH_ENV):
        os.environ.pop(key, None)
    get_settings.cache_clear()
    yield
    for key in (FLAG, PATH_ENV):
        os.environ.pop(key, None)
    get_settings.cache_clear()


def _brief(drivers: dict | None = None, *, families=("rag_assistant", "document_intelligence")) -> UseCaseBrief:
    profile = {
        "domain": "legal",
        "workload_families": list(families),
        "capabilities": ["document_retrieval", "generative_ai"],
        "sku_pricing_pilot_drivers": drivers or {},
    }
    return UseCaseBrief(
        title="Legal contract RAG POC",
        raw_use_case="Legal contract intelligence assistant using RAG over historical contracts.",
        refined_problem_statement="Legal/document RAG POC over a contract corpus.",
        use_case_profile=profile,
    )


def _estimate(brief, *, flag=False, snapshot_path=None, monkeypatch=None):
    if flag:
        monkeypatch.setenv(FLAG, "true")
    if snapshot_path:
        monkeypatch.setenv(PATH_ENV, snapshot_path)
    get_settings.cache_clear()
    return asyncio.run(PricingEngine().estimate(brief, []))


# Test 1 — flag off means no behavior change
def test_flag_off_no_pilot_metadata_and_totals_stable(monkeypatch):
    brief = _brief({"historical_contract_count": 10000, "average_mb_per_contract": 2, "rag_queries_per_day": 5000})
    est = _estimate(brief, flag=False, monkeypatch=monkeypatch)
    assert "sku_pricing_pilot" not in (est.metadata or {})


# Test 2 — flag on but no snapshot path skips safely
def test_flag_on_no_snapshot_path_skips(monkeypatch):
    brief = _brief({"historical_contract_count": 10000, "average_mb_per_contract": 2})
    est = _estimate(brief, flag=True, snapshot_path=None, monkeypatch=monkeypatch)
    pilot = est.metadata["sku_pricing_pilot"]
    assert pilot["status"] == "skipped"
    assert "snapshot path not configured" in pilot["reason"]
    assert est.metadata.get("pricing_can_be_displayed_as_headline") is False
    assert "sku_pilot_procurement_ready" not in pilot


# Test 3 — flag on with authoritative snapshot attaches a trace
def test_flag_on_authoritative_snapshot_attaches_trace(monkeypatch):
    brief = _brief({"historical_contract_count": 10000, "average_mb_per_contract": 2, "rag_queries_per_day": 5000})
    est = _estimate(brief, flag=True, snapshot_path=LOCAL_CACHE, monkeypatch=monkeypatch)
    pilot = est.metadata["sku_pricing_pilot"]
    assert pilot["status"] in {"completed", "partial"}
    assert pilot["snapshot_id"] and pilot["snapshot_source"] == "local_cache"
    assert pilot["source_hash"] and pilot["estimate_input_hash"]
    sku_lines = [ln for ln in pilot["lines"] if ln["evidence_class"] == "sku_tier_backed"]
    assert sku_lines  # at least S3 storage / Lambda requests bound
    assert any(ln["dimension_key"] == "s3_standard_storage_gb_month" for ln in sku_lines)


# Test 4 — partial binding remains directional / not ready
def test_partial_binding_remains_directional(monkeypatch):
    # S3 driver present, RAG-query driver absent -> lambda_requests not_estimated.
    brief = _brief({"historical_contract_count": 10000, "average_mb_per_contract": 2})
    est = _estimate(brief, flag=True, snapshot_path=LOCAL_CACHE, monkeypatch=monkeypatch)
    pilot = est.metadata["sku_pricing_pilot"]
    assert pilot["status"] == "partial"
    assert float(pilot["sku_backed_subtotal"]) > 0  # S3 bound
    assert pilot["not_estimated"]
    assert pilot["sku_pilot_procurement_ready"] is False
    # Global readiness untouched.
    assert est.metadata.get("pricing_can_be_displayed_as_headline") is False


# Test 5 — all required pilot lines bound can mark pilot ready only
def test_all_required_lines_bound_marks_pilot_ready_only(monkeypatch):
    brief = _brief({"historical_contract_count": 10000, "average_mb_per_contract": 2, "rag_queries_per_day": 5000})
    est = _estimate(brief, flag=True, snapshot_path=LOCAL_CACHE, monkeypatch=monkeypatch)
    pilot = est.metadata["sku_pricing_pilot"]
    assert pilot["status"] == "completed"
    assert pilot["sku_pilot_procurement_ready"] is True
    # Global PricingAnalysis readiness is NOT promoted by the pilot.
    assert est.metadata.get("pricing_can_be_displayed_as_headline") is False
    assert est.metadata.get("source_truth_pricing_compiler", {}).get("procurement_ready") in (None, False)


# Test 6 — non-authoritative snapshot fails closed
def test_non_authoritative_snapshot_fails_closed(monkeypatch):
    brief = _brief({"historical_contract_count": 10000, "average_mb_per_contract": 2, "rag_queries_per_day": 5000})
    est = _estimate(brief, flag=True, snapshot_path=STATIC_FIXTURE, monkeypatch=monkeypatch)
    pilot = est.metadata["sku_pricing_pilot"]
    assert pilot["status"] in {"skipped", "failed_closed"}
    assert pilot.get("sku_pilot_procurement_ready") in (None, False)
    assert est.metadata.get("pricing_can_be_displayed_as_headline") is False


# Test 7 — existing pricing numbers do not change with/without flag
def test_existing_pricing_totals_identical_with_and_without_flag(monkeypatch):
    drivers = {"historical_contract_count": 10000, "average_mb_per_contract": 2, "rag_queries_per_day": 5000}
    off = _estimate(_brief(drivers), flag=False, monkeypatch=monkeypatch)
    monkeypatch.delenv(FLAG, raising=False)
    on = _estimate(_brief(drivers), flag=True, snapshot_path=LOCAL_CACHE, monkeypatch=monkeypatch)
    assert (off.low_monthly_usd, off.expected_monthly_usd, off.high_monthly_usd) == (
        on.low_monthly_usd, on.expected_monthly_usd, on.high_monthly_usd
    )
    assert "sku_pricing_pilot" not in (off.metadata or {})
    assert "sku_pricing_pilot" in on.metadata  # only metadata differs


# Test 8 — trace includes reproducibility + line fields
def test_trace_includes_reproducibility_and_line_fields(monkeypatch):
    brief = _brief({"historical_contract_count": 10000, "average_mb_per_contract": 2, "rag_queries_per_day": 5000})
    est = _estimate(brief, flag=True, snapshot_path=LOCAL_CACHE, monkeypatch=monkeypatch)
    pilot = est.metadata["sku_pricing_pilot"]
    for field in ("snapshot_id", "snapshot_source", "source_hash", "estimate_input_hash"):
        assert pilot.get(field)
    line = next(ln for ln in pilot["lines"] if ln["evidence_class"] == "sku_tier_backed")
    for field in ("sku", "rate", "unit", "quantity", "monthly_subtotal", "usage_purpose", "service_code", "price_dimension_id"):
        assert field in line


# Test 9 — no network dependency (runs fully offline with the committed fixture)
def test_pilot_runs_offline_no_network(monkeypatch):
    # No AWS creds / MCP / Tavily env required; the fixture path is local.
    for noisy in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "ARCHWAY_AWS_PRICING_MCP_URL"):
        monkeypatch.delenv(noisy, raising=False)
    brief = _brief({"historical_contract_count": 10000, "average_mb_per_contract": 2, "rag_queries_per_day": 5000})
    est = _estimate(brief, flag=True, snapshot_path=LOCAL_CACHE, monkeypatch=monkeypatch)
    assert est.metadata["sku_pricing_pilot"]["status"] == "completed"
