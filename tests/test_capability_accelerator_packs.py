"""Tests for the advisory capability accelerator packs.

Packs may improve questions, missing-fact prompts, governance/sensitivity notes,
and fill a generic fallback-family void. They must never change pricing,
readiness, architecture selection, final capability status, or known
classifications. Flag off = byte/behavior equivalent.
"""

import json

import pytest

from app.core.config import get_settings
from app.services.capability_accelerator_packs import (
    CAPABILITY_ACCELERATOR_PACKS,
    HCM_PAYROLL_WORKFORCE_PACK,
    NETWORK_SECURITY_OBSERVABILITY_PACK,
    match_accelerator_packs,
)
from app.services.capability_router import (
    GENERIC_FALLBACK_FAMILIES,
    CapabilityRouter,
    screen_sensitivity,
)
from app.services.use_case_profile import profile_use_case

NETWORK_OBSERVABILITY_USE_CASE = (
    "Network operations team wants to analyze NetFlow and syslog telemetry from 5,000 "
    "switches and routers across campus networks to detect packet loss and latency "
    "anomalies, with SIEM integration for the SOC."
)
COLLABORATION_CC_USE_CASE = (
    "Build collaboration analytics over meeting quality and a contact-center reporting "
    "view for agent performance across the enterprise."
)
PAYROLL_ANOMALY_USE_CASE = (
    "Detect payroll anomalies across 50,000 employees before each payroll cycle, "
    "comparing timecards against expected hours."
)
WORKFORCE_SCHEDULING_USE_CASE = (
    "Optimize workforce management scheduling and time and attendance for hourly staff "
    "with manager approval workflows."
)


@pytest.fixture
def packs_enabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "enable_capability_accelerator_packs", True)


def _route(text: str):
    return CapabilityRouter().route(profile_use_case(text), {}, raw_use_case=text)


# --- matching -----------------------------------------------------------------


def test_network_pack_matches_network_observability_usecase():
    matches = match_accelerator_packs(NETWORK_OBSERVABILITY_USE_CASE)
    assert any(m.pack.pack_id == "network_security_observability" for m in matches)


def test_network_pack_matches_collaboration_contact_center_analytics():
    matches = match_accelerator_packs(COLLABORATION_CC_USE_CASE)
    assert any(m.pack.pack_id == "network_security_observability" for m in matches)


def test_network_pack_does_not_match_switching_payment_provider():
    text = "We are switching payment provider for our checkout flow and need a migration plan."
    assert NETWORK_SECURITY_OBSERVABILITY_PACK.match(text) is None


def test_network_pack_does_not_match_web_router():
    text = "Our React app uses react router for navigation and a web router for API paths."
    assert NETWORK_SECURITY_OBSERVABILITY_PACK.match(text) is None


def test_network_pack_requires_more_than_security_alone():
    assert NETWORK_SECURITY_OBSERVABILITY_PACK.match("We care about security for our web app.") is None


def test_hcm_pack_matches_payroll_anomaly_usecase():
    matches = match_accelerator_packs(PAYROLL_ANOMALY_USE_CASE)
    assert any(m.pack.pack_id == "hcm_payroll_workforce" for m in matches)


def test_hcm_pack_matches_workforce_scheduling_usecase():
    matches = match_accelerator_packs(WORKFORCE_SCHEDULING_USE_CASE)
    assert any(m.pack.pack_id == "hcm_payroll_workforce" for m in matches)


def test_hcm_pack_does_not_match_generic_hr_policy_without_hcm_signals_if_threshold_not_met():
    text = "Build a RAG assistant over HR policy documents so staff can ask questions."
    assert HCM_PAYROLL_WORKFORCE_PACK.match(text) is None


# --- sensitivity / governance ---------------------------------------------------


def test_hcm_pack_marks_payroll_employee_data_sensitive_for_model_prior_skip():
    # Record/value-level markers skip the model prior (approved posture)...
    sensitive, reason = screen_sensitivity(
        "Reconcile employee pay statements and direct deposit details nightly."
    )
    assert sensitive is True
    assert reason == "hcm_payroll_record"
    # ...but bare topic words must NOT block valid HCM use cases.
    topic_only, _ = screen_sensitivity(PAYROLL_ANOMALY_USE_CASE)
    assert topic_only is False
    # The pack itself always carries advisory sensitivity concerns.
    assert HCM_PAYROLL_WORKFORCE_PACK.sensitivity_concerns


def test_hcm_pack_writeback_question_mentions_approval(packs_enabled):
    decision = _route(WORKFORCE_SCHEDULING_USE_CASE)
    pack_meta = next(m for m in decision.capability_accelerators if m["pack_id"] == "hcm_payroll_workforce")
    blob = " ".join(pack_meta["questions"] + pack_meta["governance_concerns"]).lower()
    assert "approval" in blob and "writeback" in blob
    assert any("approval" in q.lower() for q in decision.next_best_questions)


# --- registry safety -------------------------------------------------------------


def test_all_accelerator_fallback_families_exist():
    for pack in CAPABILITY_ACCELERATOR_PACKS:
        assert pack.candidate_fallback_families, pack.pack_id
        for family in pack.candidate_fallback_families:
            assert family in GENERIC_FALLBACK_FAMILIES, f"{pack.pack_id}: {family}"


# --- flag gating ------------------------------------------------------------------


def test_flag_off_no_accelerator_metadata():
    assert get_settings().enable_capability_accelerator_packs is False
    decision = _route(NETWORK_OBSERVABILITY_USE_CASE)
    assert decision.capability_accelerators == []
    assert "capability_accelerators" not in decision.to_dict()


def test_flag_on_adds_advisory_metadata_only(packs_enabled):
    baseline = None
    settings = get_settings()
    settings.enable_capability_accelerator_packs = False
    try:
        baseline = _route(NETWORK_OBSERVABILITY_USE_CASE)
    finally:
        settings.enable_capability_accelerator_packs = True
    enriched = _route(NETWORK_OBSERVABILITY_USE_CASE)

    assert enriched.capability_accelerators
    assert all(item["advisory_only"] is True for item in enriched.capability_accelerators)
    # Advisory only: status / safety / readiness-bearing fields identical to flag-off.
    assert enriched.status == baseline.status
    assert enriched.matched_known_family == baseline.matched_known_family
    assert enriched.expected_artifact_level == baseline.expected_artifact_level
    assert enriched.safe_to_generate_architecture == baseline.safe_to_generate_architecture
    assert enriched.safe_to_generate_pricing == baseline.safe_to_generate_pricing
    assert enriched.safe_to_generate_diagrams == baseline.safe_to_generate_diagrams
    # Questions may only be ADDED, never removed.
    assert set(baseline.next_best_questions) <= set(enriched.next_best_questions)


def test_pack_fallback_candidate_fills_void_only(packs_enabled):
    # Construct a genuine void: no families/capabilities/actions and no
    # deterministic-fallback trigger words in the text — the pack may then fill it.
    text = "Correlate NetFlow and syslog from campus switches to find packet loss."
    profile = profile_use_case(text)
    profile.workload_families = []
    profile.capabilities = []
    profile.capability_model = []
    profile.actions = []
    decision = CapabilityRouter().route(profile, {}, raw_use_case=text)
    assert decision.fallback_family_source == "accelerator_pack"
    assert decision.generic_fallback_family in NETWORK_SECURITY_OBSERVABILITY_PACK.candidate_fallback_families
    # When the deterministic fallback already resolves, packs must NOT override it —
    # even for a strongly matching pack (the profiler resolves this text itself).
    decision2 = _route(NETWORK_OBSERVABILITY_USE_CASE)
    assert decision2.capability_accelerators, "pack matched"
    assert decision2.fallback_family_source == "deterministic"


# --- non-interference ---------------------------------------------------------------


def test_packs_do_not_change_pricing_quantities_or_readiness(packs_enabled):
    from app.services.pattern_catalog import pricing_dimensions
    from app.services.pricing_driver_selector import select_pricing_driver_family

    settings = get_settings()
    for text in (PAYROLL_ANOMALY_USE_CASE, NETWORK_OBSERVABILITY_USE_CASE):
        settings.enable_capability_accelerator_packs = False
        try:
            profile_off = profile_use_case(text)
            family_off = select_pricing_driver_family(profile_off)
            dims_off = pricing_dimensions(profile_off)
            decision_off = _route(text)
        finally:
            settings.enable_capability_accelerator_packs = True
        profile_on = profile_use_case(text)
        decision_on = _route(text)
        assert select_pricing_driver_family(profile_on) == family_off
        assert pricing_dimensions(profile_on) == dims_off
        assert decision_on.safe_to_generate_pricing == decision_off.safe_to_generate_pricing
        assert decision_on.expected_artifact_level == decision_off.expected_artifact_level


def test_packs_do_not_override_known_healthcare_iot_payment_legal_classifications(packs_enabled):
    known = {
        "healthcare": (
            "Large tertiary hospital wants to optimize OR scheduling, predict surgical delays, "
            "coordinate sterile processing and EHR updates with approval workflow. Epic EHR, PHI-safe, HIPAA."
        ),
        "iot": (
            "Industrial manufacturer streams sensor telemetry from 10,000 machines for predictive "
            "maintenance with real-time anomaly detection and field crew dispatch."
        ),
        "payment": (
            "Payment fraud scoring for 50 million card transactions per day with real-time risk decisions."
        ),
        "legal": (
            "Law firm needs retrieval augmented generation over legal documents with citations and audit trail."
        ),
    }
    settings = get_settings()
    for label, text in known.items():
        settings.enable_capability_accelerator_packs = False
        try:
            profile_off = profile_use_case(text)
            decision_off = _route(text)
        finally:
            settings.enable_capability_accelerator_packs = True
        profile_on = profile_use_case(text)
        decision_on = _route(text)
        assert profile_on.domain == profile_off.domain, label
        assert profile_on.workload_families == profile_off.workload_families, label
        assert decision_on.status == decision_off.status, label
        assert decision_on.matched_known_family == decision_off.matched_known_family, label
        assert decision_on.generic_fallback_family == decision_off.generic_fallback_family, label


def test_capability_decision_serializes_with_accelerator_metadata(packs_enabled):
    decision = _route(PAYROLL_ANOMALY_USE_CASE)
    payload = decision.to_dict()
    assert payload["capability_accelerators"]
    json.dumps(payload)
