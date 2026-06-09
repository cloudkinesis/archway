"""CapabilityRouter + quarantined frontier-domain-prior tests.

The frontier prior reuses DiscoveryPlannerService.plan() (ModelRouter path). All tests
use a FAKE model via monkeypatch — no live model calls. They prove the prior is
advisory-only, quarantined to questions + fallback-family, deterministic-known
dominates, sensitivity fails closed, and nothing leaks into pricing/architecture.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.config import get_settings
from app.services.capability_router import (
    GENERIC_FALLBACK_FAMILIES,
    CapabilityRouter,
    reset_frontier_state,
    screen_sensitivity,
)
from app.services.discovery_planner import DiscoveryCandidate, DiscoveryPlan, DiscoveryPlannerService, DiscoveryQuestion
from app.services.llm import model_router as model_router_module
from app.services.llm.base import LLMResult
from app.services.use_case_profile import profile_use_case

FLAG = "ARCHWAY_ENABLE_FRONTIER_DOMAIN_PRIOR"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    monkeypatch.delenv("ARCHWAY_FRONTIER_DOMAIN_PRIOR_MAX_CALLS_PER_SESSION", raising=False)
    get_settings.cache_clear()
    reset_frontier_state()
    yield
    get_settings.cache_clear()
    reset_frontier_state()


def _fake_plan(*, domain="payments", family="batch_data_analytics", confidence="high", pricing_drivers=None, questions=None):
    return DiscoveryPlan(
        domain_candidates=[DiscoveryCandidate(name=domain, confidence=confidence, rationale="model guess")],
        workload_family_candidates=[DiscoveryCandidate(name=family, confidence=confidence, rationale="model guess")],
        confidence=confidence,
        pricing_drivers=pricing_drivers or ["MALICIOUS_MODEL_DRIVER"],
        governance_concerns=["model-invented governance concern"],
        top_questions=questions or [DiscoveryQuestion(id="m1", question="What is the daily volume?", why_it_matters="sizing", expected_answer_style="number")],
    )


def _install_fake_model(monkeypatch, *, parsed=None, validated=True, raises=False, provider="bedrock"):
    async def _fake_complete(self, task, messages, response_schema=None, temperature=None, max_tokens=None, timeout_seconds=None):
        if raises:
            raise RuntimeError("simulated model failure")
        return LLMResult(provider=provider, model_id="fake-sonnet-v1", text="{}", parsed=parsed, validated=validated, warnings=[] if validated else ["bad json"])
    monkeypatch.setattr(model_router_module.ModelRouter, "complete", _fake_complete)


def _run_plan(raw, profile, session_id="s1"):
    return asyncio.run(DiscoveryPlannerService().plan(raw, profile, session_id=session_id))


# 1 — unknown valid use case gets a prior, routed to a directional/discovery fallback
def test_frontier_prior_used_for_unknown_valid_usecase(monkeypatch):
    monkeypatch.setenv(FLAG, "true"); get_settings.cache_clear()
    raw = "We want a system to coordinate artisanal cheese aging across distributed cellars."
    profile = profile_use_case(raw)
    _install_fake_model(monkeypatch, parsed=_fake_plan(family="batch_data_analytics", confidence="high"))
    plan = _run_plan(raw, profile)
    profile.discovery_plan = plan.model_dump(mode="json")
    decision = CapabilityRouter().route(profile, profile.discovery_plan, raw_use_case=raw)
    assert decision.status in {"directional", "discovery_needed"}  # never terminal invalid
    assert decision.generic_fallback_family in GENERIC_FALLBACK_FAMILIES
    assert plan.prior_provenance.get("status") == "generated"


# 2 — model "high confidence" is advisory, router stays deterministic, no promotion
def test_frontier_prior_is_advisory_not_authoritative(monkeypatch):
    monkeypatch.setenv(FLAG, "true"); get_settings.cache_clear()
    raw = "Some ambiguous internal tooling idea with unclear scope and no clear workload."
    profile = profile_use_case(raw)
    _install_fake_model(monkeypatch, parsed=_fake_plan(domain="payments", family="ml_inference_workflow", confidence="high"))
    plan = _run_plan(raw, profile)
    profile.discovery_plan = plan.model_dump(mode="json")
    decision = CapabilityRouter().route(profile, profile.discovery_plan, raw_use_case=raw)
    # Model claims high confidence, but deterministic profile is not high+supported.
    assert decision.status != "supported"
    assert decision.deterministic_confidence == profile.confidence


# test_model_confidence_is_display_only
def test_model_confidence_is_display_only(monkeypatch):
    monkeypatch.setenv(FLAG, "true"); get_settings.cache_clear()
    raw = "Unclear ad-hoc data shuffling task with no defined workload family."
    profile = profile_use_case(raw)
    _install_fake_model(monkeypatch, parsed=_fake_plan(confidence="high"))
    plan = _run_plan(raw, profile)
    profile.discovery_plan = plan.model_dump(mode="json")
    decision = CapabilityRouter().route(profile, profile.discovery_plan, raw_use_case=raw)
    assert decision.model_prior.get("model_self_confidence_display_only") == "high"
    assert decision.status != "supported"  # model confidence did not gate anything


# 3 — model raises -> deterministic fallback, valid status, no crash
def test_frontier_prior_failure_falls_back_deterministically(monkeypatch):
    monkeypatch.setenv(FLAG, "true"); get_settings.cache_clear()
    raw = "An ambiguous workflow with no obvious workload family at all."
    profile = profile_use_case(raw)
    _install_fake_model(monkeypatch, raises=True)
    plan = _run_plan(raw, profile)  # must not raise
    assert plan.prior_provenance.get("status") == "failed"
    decision = CapabilityRouter().route(profile, plan.model_dump(mode="json"), raw_use_case=raw)
    assert decision.status in {"directional", "discovery_needed", "unsupported_or_blocked"}


# 4 — invalid model JSON (validated=False) -> deterministic fallback, no crash
def test_frontier_prior_json_parse_failure_falls_back(monkeypatch):
    monkeypatch.setenv(FLAG, "true"); get_settings.cache_clear()
    raw = "Another ambiguous request without a clear shape."
    profile = profile_use_case(raw)
    _install_fake_model(monkeypatch, parsed=None, validated=False)
    plan = _run_plan(raw, profile)  # must not raise
    assert plan.prior_provenance.get("status") in {"unavailable", "failed"}


# 5 — sensitive input skips the model entirely (no call), warning recorded
def test_sensitive_input_skips_frontier_prior(monkeypatch):
    monkeypatch.setenv(FLAG, "true"); get_settings.cache_clear()
    raw = "Process records where api_key=SUPERSECRETVALUE and route them somewhere."
    profile = profile_use_case(raw)

    async def _boom(*a, **k):
        raise AssertionError("model must not be called for sensitive input")
    monkeypatch.setattr(model_router_module.ModelRouter, "complete", _boom)

    plan = _run_plan(raw, profile)
    assert plan.prior_provenance.get("status") == "skipped_due_to_sensitivity"
    assert any("sensitivity" in w for w in plan.warnings)


def test_sensitivity_screen_high_signal_and_phi_markers():
    # Credential / secret VALUES.
    assert screen_sensitivity("api_key=abc123")[0] is True
    assert screen_sensitivity("Bearer abcdef1234567890")[0] is True
    assert screen_sensitivity("123-45-6789")[0] is True
    # PHI/PII markers now trip the MODEL-PRIOR skip (deterministic-known healthcare is
    # unaffected because dominance skips the model before this gate).
    assert screen_sensitivity("A HIPAA-regulated system handling PHI")[0] is True
    assert screen_sensitivity("Workflow over patient records and clinical notes")[0] is True
    # Genuinely non-sensitive prose is not flagged.
    assert screen_sensitivity("A normal RAG assistant over public docs")[0] is False


# 6 — model prior labeled unverified in metadata
def test_model_prior_labeled_unverified_in_metadata(monkeypatch):
    monkeypatch.setenv(FLAG, "true"); get_settings.cache_clear()
    raw = "An ambiguous unknown workload that needs clarification."
    profile = profile_use_case(raw)
    _install_fake_model(monkeypatch, parsed=_fake_plan())
    plan = _run_plan(raw, profile)
    assert plan.model_prior_unverified is True
    decision = CapabilityRouter().route(profile, plan.model_dump(mode="json"), raw_use_case=raw)
    assert decision.advisory_candidates_unverified.get("evidence_class") == "model_prior_unverified"
    assert decision.model_prior.get("advisory_only") is True
    assert decision.model_prior.get("used_for") == "questions_and_fallback_mapping_only"


# 7 — model cannot override known-domain deterministic classification
def test_model_cannot_override_known_domain_regression(monkeypatch):
    monkeypatch.setenv(FLAG, "true"); get_settings.cache_clear()
    cases = [
        ("A hospital OR scheduling analytics platform with PHI protection and approval-gated workflow changes.", "healthcare", "iot_telemetry"),
        ("Ingest real-time IoT sensor telemetry from smart meters and transformers for streaming analytics.", None, "payment_fraud"),
        ("Detect payment fraud and block suspicious financial transactions for analyst review.", None, "generic_anomaly"),
    ]
    for raw, expected_domain, hostile_family in cases:
        reset_frontier_state()
        profile = profile_use_case(raw)
        families_before = list(profile.workload_families)
        _install_fake_model(monkeypatch, parsed=_fake_plan(domain="WRONG", family=hostile_family, confidence="high"))
        plan = _run_plan(raw, profile)
        # Deterministic profile is never mutated by the model.
        assert profile.workload_families == families_before
        if expected_domain:
            assert profile.domain == expected_domain
        # The hostile model family is never adopted as an authoritative plan field.
        assert hostile_family not in (plan.workload_family_candidates[0].name if plan.workload_family_candidates else "")
        decision = CapabilityRouter().route(profile, plan.model_dump(mode="json"), raw_use_case=raw)
        assert decision.matched_known_family != hostile_family


# 8 — no live model call anywhere (fake-only); deterministic provider never egresses
def test_no_live_model_call_in_tests(monkeypatch):
    # Flag on but provider is the default deterministic no-op -> validated False, no egress.
    monkeypatch.setenv(FLAG, "true"); get_settings.cache_clear()
    raw = "An ambiguous request with no clear family."
    profile = profile_use_case(raw)
    plan = _run_plan(raw, profile)  # real ModelRouter, deterministic provider, no network
    assert plan.prior_provenance.get("status") in {"unavailable", "failed"}
    assert plan.generated_by == "deterministic"


# REQUIRED — model hints never enter pricing or architecture inputs (quarantine proof)
def test_model_prior_hints_do_not_enter_pricing_or_architecture_inputs(monkeypatch):
    monkeypatch.setenv(FLAG, "true"); get_settings.cache_clear()
    raw = "An ambiguous workload needing discovery."
    profile = profile_use_case(raw)
    deterministic = DiscoveryPlannerService().plan_sync(raw, profile)
    _install_fake_model(monkeypatch, parsed=_fake_plan(pricing_drivers=["MALICIOUS_MODEL_DRIVER"]))
    plan = _run_plan(raw, profile)
    # pricing_drivers are deterministic-only; the model's injected driver never appears.
    assert "MALICIOUS_MODEL_DRIVER" not in plan.pricing_drivers
    assert plan.pricing_drivers == deterministic.pricing_drivers
    # model-invented governance/data fields never overwrite deterministic ones.
    assert "model-invented governance concern" not in plan.governance_concerns
    # The only model-influenced surface is questions.
    assert any(q.question == "What is the daily volume?" for q in plan.top_questions)


# deterministic-known dominance: model is NOT called for confident known classification
def test_deterministic_known_dominates_skips_model(monkeypatch):
    monkeypatch.setenv(FLAG, "true"); get_settings.cache_clear()
    raw = "Legal contract intelligence assistant using RAG over historical contracts with obligation approval workflow."
    profile = profile_use_case(raw)
    if not (profile.confidence == "high" and profile.workload_families and profile.domain):
        pytest.skip("baseline profile not high-confidence for this corpus; dominance gate exercised elsewhere")

    async def _boom(*a, **k):
        raise AssertionError("model must not be called when deterministic-known dominates")
    monkeypatch.setattr(model_router_module.ModelRouter, "complete", _boom)
    plan = _run_plan(raw, profile)
    assert plan.prior_provenance.get("status") == "skipped_deterministic_known"


# --- unsafe / abuse blocker -------------------------------------------------
def test_phishing_or_credential_theft_usecase_is_unsupported_or_blocked():
    raw = "Build a platform to send phishing emails at scale and harvest user credentials."
    profile = profile_use_case(raw)
    decision = CapabilityRouter().route(profile, {}, raw_use_case=raw)
    assert decision.status == "unsupported_or_blocked"
    assert decision.safe_to_generate_architecture is False
    assert decision.safe_to_generate_pricing is False
    assert decision.safe_to_generate_diagrams is False


def test_malware_or_exfiltration_usecase_is_unsupported_or_blocked():
    raw = "Create malware that exfiltrates customer data from corporate networks while evading detection."
    profile = profile_use_case(raw)
    decision = CapabilityRouter().route(profile, {}, raw_use_case=raw)
    assert decision.status == "unsupported_or_blocked"
    assert decision.expected_artifact_level == "unsupported_explanation"


def test_unsupported_case_has_explanation_artifact_level():
    raw = "Set up a botnet and a command-and-control server to run DDoS attacks."
    profile = profile_use_case(raw)
    decision = CapabilityRouter().route(profile, {}, raw_use_case=raw)
    assert decision.status == "unsupported_or_blocked"
    assert decision.expected_artifact_level == "unsupported_explanation"
    assert decision.safe_to_generate_architecture is False


def test_defensive_security_usecase_is_not_blocked():
    # Legitimate defensive security products must NOT be blocked.
    for raw in (
        "Build a phishing detection and email threat protection platform.",
        "A malware detection and incident response system for our SOC.",
        "Credential theft prevention with anomaly detection and MFA monitoring.",
    ):
        decision = CapabilityRouter().route(profile_use_case(raw), {}, raw_use_case=raw)
        assert decision.status != "unsupported_or_blocked", raw


# --- PHI sensitivity skip for the model prior -------------------------------
def test_sensitive_phi_unknown_input_skips_model_prior_but_returns_deterministic_fallback(monkeypatch):
    monkeypatch.setenv(FLAG, "true"); get_settings.cache_clear()
    raw = "An exploratory internal utility of unclear scope that may reference a patient record."
    profile = profile_use_case(raw)
    # Force low-confidence/unknown so the deterministic-known dominance gate does NOT fire
    # first — this test specifically exercises the PHI sensitivity skip gate.
    profile.workload_families = []
    profile.domain = None
    profile.confidence = "medium"

    async def _boom(*a, **k):
        raise AssertionError("model must not be called for PHI-bearing input")
    monkeypatch.setattr(model_router_module.ModelRouter, "complete", _boom)

    plan = _run_plan(raw, profile)
    assert plan.prior_provenance.get("status") == "skipped_due_to_sensitivity"
    assert plan.generated_by == "deterministic"  # deterministic fallback still returned
    assert plan.top_questions  # use case is NOT blocked; still produces a plan


def test_known_healthcare_or_does_not_need_model_prior(monkeypatch):
    monkeypatch.setenv(FLAG, "true"); get_settings.cache_clear()
    raw = ("A hospital network needs AWS OR scheduling analytics with PHI protection, audit retention, "
           "and approval-gated workflow changes for surgical scheduling across hospitals.")
    profile = profile_use_case(raw)

    async def _boom(*a, **k):
        raise AssertionError("model must not be called when deterministic-known healthcare dominates")
    monkeypatch.setattr(model_router_module.ModelRouter, "complete", _boom)

    plan = _run_plan(raw, profile)
    # Dominance (not sensitivity) handles confident healthcare; model is never called.
    assert plan.prior_provenance.get("status") == "skipped_deterministic_known"
    assert profile.domain == "healthcare"


# flag OFF (default): deterministic only, model never engaged
def test_flag_off_uses_deterministic_only(monkeypatch):
    get_settings.cache_clear()  # flag unset -> false

    async def _boom(*a, **k):
        raise AssertionError("model must not be called when flag is off")
    monkeypatch.setattr(model_router_module.ModelRouter, "complete", _boom)
    raw = "An ambiguous request."
    profile = profile_use_case(raw)
    plan = _run_plan(raw, profile)
    assert plan.prior_provenance.get("status") == "disabled"
    assert plan.generated_by == "deterministic"
