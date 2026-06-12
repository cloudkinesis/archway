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


# =============================================================================
# Wave 2 packs: firewall / smart spaces / banking / financial crime + HCM delta
# =============================================================================

from app.services.capability_accelerator_packs import (  # noqa: E402
    BANKING_OPEN_BANKING_PAYMENTS_PACK,
    FINANCIAL_CRIME_RISK_OPERATIONS_PACK,
    FIREWALL_SECURITY_OPERATIONS_PACK,
    SMART_SPACES_LOCATION_IOT_PACK,
)

FIREWALL_POLICY_USE_CASE = (
    "Optimize firewall policies and automate rule recertification across 200 firewalls "
    "with SIEM integration."
)
PURE_TELEMETRY_USE_CASE = NETWORK_OBSERVABILITY_USE_CASE  # NetFlow/switches/SIEM/SOC
SMART_SPACES_USE_CASE = (
    "Analyze workspace occupancy and meeting room utilization with indoor location from "
    "WiFi presence across our smart buildings."
)
OPEN_BANKING_USE_CASE = (
    "Build open banking payment initiation with consent management for bank-to-bank payments."
)
AML_TRIAGE_USE_CASE = (
    "AML alert triage with case management for transaction monitoring alerts."
)


def test_firewall_pack_matches_firewall_policy_optimization():
    assert FIREWALL_SECURITY_OPERATIONS_PACK.match(FIREWALL_POLICY_USE_CASE)


def test_firewall_pack_matches_vpn_firewall_event_triage():
    assert FIREWALL_SECURITY_OPERATIONS_PACK.match(
        "Triage VPN anomalies and firewall events from security appliances, integrated with the SOC."
    )


def test_pure_telemetry_matches_network_pack_but_not_firewall_pack():
    assert NETWORK_SECURITY_OBSERVABILITY_PACK.match(PURE_TELEMETRY_USE_CASE)
    assert FIREWALL_SECURITY_OPERATIONS_PACK.match(PURE_TELEMETRY_USE_CASE) is None


def test_firewall_metaphor_does_not_match_firewall_pack():
    assert FIREWALL_SECURITY_OPERATIONS_PACK.match("Run a wall fire drill evacuation plan for the office.") is None
    assert FIREWALL_SECURITY_OPERATIONS_PACK.match(
        "Train staff to act as a human firewall against phishing with security awareness."
    ) is None


def test_smart_spaces_pack_matches_occupancy_indoor_location():
    assert SMART_SPACES_LOCATION_IOT_PACK.match(SMART_SPACES_USE_CASE)


def test_smart_spaces_person_location_markers_trigger_sensitivity_skip():
    sensitive, reason = screen_sensitivity("Track badge IDs and individual location history for employees.")
    assert sensitive is True and reason == "spaces_location_record"
    topic_only, _ = screen_sensitivity("Workspace occupancy analytics with indoor location heatmaps.")
    assert topic_only is False
    assert SMART_SPACES_LOCATION_IOT_PACK.sensitivity_concerns


def test_smart_spaces_does_not_match_generic_real_estate_planning():
    assert SMART_SPACES_LOCATION_IOT_PACK.match(
        "Plan office space allocation and lease optimization for our real estate portfolio."
    ) is None


def test_banking_pack_matches_open_banking_payment_initiation():
    assert BANKING_OPEN_BANKING_PAYMENTS_PACK.match(OPEN_BANKING_USE_CASE)


def test_banking_pack_matches_account_information_consent_workflow():
    assert BANKING_OPEN_BANKING_PAYMENTS_PACK.match(
        "Account information service with customer consent workflow across banking APIs."
    )


def test_banking_pack_does_not_match_generic_bank_marketing_site():
    assert BANKING_OPEN_BANKING_PAYMENTS_PACK.match(
        "Build a marketing website where customers can open a bank account online."
    ) is None


def test_swift_programming_does_not_trigger_banking_swift():
    assert BANKING_OPEN_BANKING_PAYMENTS_PACK.match(
        "Build an iOS app in Swift with SwiftUI for our retail bank's marketing site."
    ) is None


def test_financial_crime_pack_matches_aml_alert_triage():
    assert FINANCIAL_CRIME_RISK_OPERATIONS_PACK.match(AML_TRIAGE_USE_CASE)


def test_financial_crime_pack_matches_sanctions_screening_kyc_refresh():
    assert FINANCIAL_CRIME_RISK_OPERATIONS_PACK.match(
        "Sanctions screening and KYC refresh for customer onboarding."
    )


def test_search_and_rescue_sar_does_not_trigger_financial_crime():
    assert FINANCIAL_CRIME_RISK_OPERATIONS_PACK.match(
        "Build a dispatch coordination system for search and rescue (SAR) operations with mission filing."
    ) is None


def test_banking_sensitivity_skips_records_not_abstract_account_wording():
    assert screen_sensitivity("Reconcile transfers for IBAN GB29NWBK60161331926819")[1] == "financial_record"
    assert screen_sensitivity("Validate sort codes during payment setup")[1] == "financial_record"
    assert screen_sensitivity("Match customer account numbers against statements")[1] == "financial_record"
    # Abstract account wording and financial-crime topics never skip the prior.
    assert screen_sensitivity("Account information service for account onboarding and account analytics")[0] is False
    assert screen_sensitivity("Build AML alert triage with sanctions screening and KYC refresh")[0] is False


def test_financial_crime_pack_does_not_override_deterministic_payment_fraud(packs_enabled):
    text = "Payment fraud scoring for 50 million card transactions per day with real-time risk decisions."
    settings = get_settings()
    settings.enable_capability_accelerator_packs = False
    try:
        profile_off = profile_use_case(text)
        decision_off = _route(text)
    finally:
        settings.enable_capability_accelerator_packs = True
    profile_on = profile_use_case(text)
    decision_on = _route(text)
    assert profile_on.workload_families == profile_off.workload_families
    assert decision_on.status == decision_off.status
    assert decision_on.matched_known_family == decision_off.matched_known_family
    assert decision_on.generic_fallback_family == decision_off.generic_fallback_family


def test_hcm_delta_signals_match_and_hr_policy_rag_still_unmatched():
    assert HCM_PAYROLL_WORKFORCE_PACK.match(
        "Handle payroll exceptions and absence management with benefits administration workflows."
    )
    assert HCM_PAYROLL_WORKFORCE_PACK.match(PAYROLL_ANOMALY_USE_CASE)
    assert HCM_PAYROLL_WORKFORCE_PACK.match(
        "Build a RAG assistant over HR policy documents so staff can ask questions."
    ) is None


def test_context_vocabulary_uses_word_boundaries():
    match = HCM_PAYROLL_WORKFORCE_PACK.match(
        "We adapted our workforce management and time and attendance processes."
    )
    assert match is not None
    assert all(not s.startswith("context:") for s in match.matched_signals), match.matched_signals


def test_company_names_are_context_only_not_pack_ids():
    for pack in CAPABILITY_ACCELERATOR_PACKS:
        for company in ("cisco", "adp", "barclays", "natwest", "workday", "meraki"):
            assert company not in pack.pack_id


def test_wave2_flag_on_adds_advisory_metadata_only(packs_enabled):
    for text in (FIREWALL_POLICY_USE_CASE, SMART_SPACES_USE_CASE, OPEN_BANKING_USE_CASE, AML_TRIAGE_USE_CASE):
        settings = get_settings()
        settings.enable_capability_accelerator_packs = False
        try:
            baseline = _route(text)
        finally:
            settings.enable_capability_accelerator_packs = True
        enriched = _route(text)
        assert enriched.capability_accelerators
        assert all(item["advisory_only"] is True for item in enriched.capability_accelerators)
        assert enriched.status == baseline.status
        assert enriched.safe_to_generate_pricing == baseline.safe_to_generate_pricing
        assert enriched.expected_artifact_level == baseline.expected_artifact_level
        assert set(baseline.next_best_questions) <= set(enriched.next_best_questions)
        json.dumps(enriched.to_dict())
