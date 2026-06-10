"""Pricing headline display must fail closed.

A missing or unproven headline-safety flag must never render a confident executive
headline. Directional pricing stays visible (range + line items) but without a
confident headline. These tests lock the fail-closed presentation behavior and the
fail-closed default on the sanity-review safety flag. No pricing numbers are changed.
"""

import json

from app.services.pricing_sanity_reviewer import PricingSanityReview
from app.services.research_view_model import build_research_view_model


def _report():
    return {
        "session_id": "sess_headline",
        "generated_at": "2026-06-08T00:00:00Z",
        "executive_verdict": "Proceed with caution.",
        "proceed_recommendation": "proceed_with_caution",
        "use_case_interpretation": "Retail order-status assistant with workflow integration.",
        "assumptions": [],
        "recommended_poc": "Start with a scoped POC.",
        "recommended_production_direction": "Harden with multi-AZ production controls.",
        "aws_service_recommendations": [
            {"service": "Amazon Kinesis Data Streams", "purpose": "ingestion", "rationale": "managed ingestion", "alternatives_considered": ["Amazon MSK"]}
        ],
        "risks": [],
        "evidence_items": [{"id": "ev_1", "source_type": "aws_docs", "title": "guidance", "quote_or_summary": "summary", "confidence": "high"}],
        "citation_coverage": {"coverage_percent": 100},
        "metadata": {
            "use_case_profile": {"domain": "retail", "workload_families": ["web_api_application"]},
            "workload_families": ["web_api_application"],
            "customer_readiness": {"status": "directional_only"},
            "evidence_quality": {"evidence_authority": "official"},
        },
    }


def _pricing(metadata: dict):
    return {
        "region": "us-east-1",
        "low_monthly_usd": 10,
        "expected_monthly_usd": 20,
        "high_monthly_usd": 40,
        "unknown_variables": ["event_rate"],
        "line_items": [
            {"service": "Amazon Kinesis Data Streams", "unit_basis": "event ingestion", "expected_monthly_usd": 20,
             "pricing_trace": {"calculation_source": "deterministic_model", "quantity": 1000, "unit": "events"}}
        ],
        "metadata": metadata,
    }


def _vm(metadata: dict):
    pricing = _pricing(metadata)
    vm = build_research_view_model("sess_headline", _report(), None, pricing, None)
    assert vm is not None
    return vm, pricing


# Test 1 — missing headline flag fails closed
def test_missing_headline_flag_fails_closed():
    vm, _ = _vm({"pricing_maturity": "pricing_directional_with_assumptions"})  # flag ABSENT
    assert vm.pricing_poc.headline_safe is False
    assert vm.pricing_poc.monthly_expected == "Withheld from headline"


# Test 2 — explicit false remains false
def test_explicit_false_remains_false():
    vm, _ = _vm({"pricing_can_be_displayed_as_headline": False})
    assert vm.pricing_poc.headline_safe is False
    assert vm.pricing_poc.monthly_expected == "Withheld from headline"


# Test 3 — explicit true is preserved (only where existing logic allows: POC phase)
def test_explicit_true_preserved_for_poc():
    vm, _ = _vm({"pricing_can_be_displayed_as_headline": True})
    assert vm.pricing_poc.headline_safe is True
    assert vm.pricing_poc.monthly_expected == "$20.00"  # headline shown when explicitly safe + POC


# Test 4 — production is not headline-safe by default (phase rule preserved)
def test_production_not_headline_safe_even_when_flag_true():
    vm, _ = _vm({"pricing_can_be_displayed_as_headline": True})
    assert vm.pricing_production.headline_safe is False
    assert vm.pricing_production.monthly_expected == "Withheld from headline"


# Test 5 — directional/heuristic estimate is still visible, just not a headline
def test_directional_estimate_visible_but_not_headline():
    vm, _ = _vm({"pricing_maturity": "pricing_directional_with_assumptions"})  # flag absent => unsafe
    assert vm.pricing_poc.headline_safe is False
    # Range / details remain available even though the confident headline is withheld.
    assert vm.pricing_poc.monthly_low == "$10.00"
    assert vm.pricing_poc.monthly_high == "$40.00"
    assert len(vm.pricing_poc.line_items) == 1


# Test 6 — no numeric drift: building the view model does not mutate pricing totals
def test_no_numeric_drift_in_pricing_inputs():
    vm, pricing = _vm({"pricing_can_be_displayed_as_headline": True})
    assert pricing["low_monthly_usd"] == 10
    assert pricing["expected_monthly_usd"] == 20
    assert pricing["high_monthly_usd"] == 40
    assert pricing["line_items"][0]["expected_monthly_usd"] == 20


# Sanity-review safety flag defaults to fail-closed
def test_pricing_sanity_review_flag_defaults_false():
    review = PricingSanityReview(passed=True)
    assert review.pricing_can_be_displayed_as_headline is False
