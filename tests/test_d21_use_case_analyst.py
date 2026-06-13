from __future__ import annotations

import copy
import json
from zipfile import ZipFile

import pytest

from app.core.config import get_settings
from app.db.session_store import SessionStore
from app.services.agentic.evaluation import ScenarioObservation, run_evaluation_battery, score_scenario
from app.services.agentic.evaluation_scenarios import thin_evaluation_scenarios
from app.services.agentic.use_case_analyst import (
    AnalystCandidate,
    DeterministicFixtureUseCaseAnalystProvider,
    LiveUseCaseAnalystProvider,
    UseCaseAnalystProposal,
    build_use_case_analyst_context,
    build_use_case_analyst_trace,
    validate_use_case_analyst_proposal,
)
from app.services.export_package import ExportPackageService
from app.services.synthesis import SynthesisEngine


def test_use_case_analyst_flag_defaults_false_and_provider_is_not_invoked(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.delenv("ARCHWAY_ENABLE_AGENTIC_USE_CASE_ANALYST", raising=False)
    get_settings.cache_clear()

    class ExplodingProvider:
        provider_name = "explode"

        def propose(self, context):  # pragma: no cover - should never run
            raise AssertionError("provider should not be invoked when disabled")

        def validate(self, proposal, deterministic_context):  # pragma: no cover
            raise AssertionError("provider should not be invoked when disabled")

    trace = build_use_case_analyst_trace(
        settings=get_settings(),
        context={"deterministic_profile": {"domain": "retail", "workload_families": ["web_api_application"]}},
        provider=ExplodingProvider(),
    )

    assert get_settings().enable_agentic_use_case_analyst is False
    assert trace.enabled is False
    assert trace.provider == "disabled"
    assert trace.proposal.domain_candidates == []
    assert trace.decisions[0].decision == "rejected"


def test_use_case_analyst_fixture_provider_is_deterministic(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.setenv("ARCHWAY_ENABLE_AGENTIC_USE_CASE_ANALYST", "true")
    get_settings.cache_clear()
    context = {
        "raw_use_case": "Build a customer support assistant with contact-center escalation.",
        "deterministic_profile": {
            "domain": "contact_center",
            "workload_families": ["customer_support_chatbot"],
            "confidence": "medium",
        },
        "services": ["Amazon Connect", "Amazon Lex"],
        "pricing_missing_drivers": ["monthly_text_requests"],
        "signals": ["unit_test"],
    }
    provider = DeterministicFixtureUseCaseAnalystProvider()

    trace = build_use_case_analyst_trace(settings=get_settings(), context=context, provider=provider)
    again = build_use_case_analyst_trace(settings=get_settings(), context=context, provider=provider)

    assert trace.enabled is True
    assert trace.provider == "deterministic_fixture"
    assert trace.input_hash == again.input_hash
    assert trace.output_hash == again.output_hash
    assert trace.proposal.output_hash == again.proposal.output_hash
    assert [item.key for item in trace.proposal.candidate_services] == sorted(item.key for item in trace.proposal.candidate_services)
    assert all(item.accepted_status == "proposed" for item in trace.proposal.candidate_services)
    assert all(item.accepted_status == "proposed" for item in trace.proposal.candidate_pricing_drivers)


def test_live_use_case_analyst_provider_degrades_without_live_demo():
    provider = LiveUseCaseAnalystProvider()
    proposal = provider.propose({})
    assert provider.last_call is not None
    assert provider.last_call.status == "not_attempted"
    assert proposal.uncertainties


def test_use_case_analyst_does_not_overwrite_deterministic_facts():
    context = {
        "deterministic_profile": {
            "domain": "healthcare",
            "workload_families": ["healthcare_operations_scheduling"],
        }
    }
    proposal = UseCaseAnalystProposal(
        proposal_id="proposal_conflict",
        domain_candidates=[
            AnalystCandidate(
                key="domain:retail",
                label="retail",
                reason="fixture conflict",
            )
        ],
        workload_family_candidates=[
            AnalystCandidate(
                key="family:healthcare_operations_scheduling",
                label="healthcare_operations_scheduling",
                reason="fixture match",
            )
        ],
        input_hash="sha256:input",
        output_hash="sha256:output",
    )

    trace = validate_use_case_analyst_proposal(proposal, context, provider_name="unit")

    assert trace.proposal.domain_candidates[0].accepted_status == "conflict"
    assert trace.proposal.workload_family_candidates[0].accepted_status == "accepted"
    assert trace.deterministic_profile_ref["domain"] == "healthcare"
    assert trace.conflicts
    assert trace.decisions[0].decision == "downgraded"


def test_missing_deterministic_fact_remains_proposed_and_questions_are_recorded():
    context = {"deterministic_profile": {"domain": None, "workload_families": []}}
    proposal = UseCaseAnalystProposal(
        proposal_id="proposal_missing",
        domain_candidates=[AnalystCandidate(key="domain:retail", label="retail", reason="candidate")],
        missing_facts=["domain", "actors"],
        follow_up_questions=["Please confirm the missing fact: domain."],
        input_hash="sha256:input",
        output_hash="sha256:output",
    )

    trace = validate_use_case_analyst_proposal(proposal, context, provider_name="unit")

    assert trace.proposal.domain_candidates[0].accepted_status == "proposed"
    assert trace.proposal.missing_facts == ["domain", "actors"]
    assert trace.proposal.follow_up_questions == ["Please confirm the missing fact: domain."]


def test_use_case_analyst_context_uses_existing_signals_and_does_not_mutate_inputs(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.setenv("ARCHWAY_ENABLE_AGENTIC_USE_CASE_ANALYST", "true")
    get_settings.cache_clear()
    brief = {"raw_use_case": "Support chatbot", "use_case_profile": {"domain": "retail", "workload_families": ["chatbot"]}}
    pricing = {"metadata": {"pricing_driver_closure": {"missing_drivers": ["monthly_requests"]}}}
    architectures = [{"components": [{"service": "Amazon Lex"}]}]
    original_pricing = copy.deepcopy(pricing)
    original_architectures = copy.deepcopy(architectures)
    context = build_use_case_analyst_context(
        session_input="Support chatbot",
        brief=brief,
        report={},
        pricing=pricing,
        architectures=architectures,
        diagrams=[],
        reviewer_findings=[],
    )

    trace = build_use_case_analyst_trace(settings=get_settings(), context=context, provider=DeterministicFixtureUseCaseAnalystProvider())

    assert trace.proposal.candidate_services[0].label == "Amazon Lex"
    assert trace.proposal.candidate_pricing_drivers[0].label == "monthly_requests"
    assert pricing == original_pricing
    assert architectures == original_architectures


def test_export_emits_use_case_analyst_trace_raw_and_audit_only(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.delenv("ARCHWAY_ENABLE_AGENTIC_USE_CASE_ANALYST", raising=False)
    get_settings.cache_clear()
    store = SessionStore()
    brief = SynthesisEngine().create_initial_brief("Build a retail assistant for order questions.")
    session = store.create("Build a retail assistant for order questions.", brief)
    service = ExportPackageService()

    bundle = service.generate(session.id)
    zip_path = service.artifacts.resolve(session.id, bundle.artifact_id)
    export_dir = service.artifacts.session_root(session.id) / "exports" / bundle.name

    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        trace = json.loads(archive.read("raw/agent_use_case_analyst_trace.json").decode("utf-8"))
        proposal = json.loads(archive.read("raw/agent_use_case_analyst_proposal.json").decode("utf-8"))

    assert "raw/agent_use_case_analyst_trace.json" in names
    assert "raw/agent_use_case_analyst_proposal.json" in names
    assert "audit_pack/agentic-use-case-analysis.md" in names
    assert "client_pack/agentic-use-case-analysis.md" not in names
    assert trace["enabled"] is False
    assert trace["provider"] == "disabled"
    assert proposal["domain_candidates"] == []

    manifest = json.loads((export_dir / "dossier_manifest.json").read_text(encoding="utf-8"))
    inventory_paths = {item["path"] for item in manifest["artifact_inventory"]}
    assert "raw/agent_use_case_analyst_trace.json" in inventory_paths

    (export_dir / "raw/agent_use_case_analyst_trace.json").write_text("[]\n", encoding="utf-8")
    from tests.test_d21_agentic_foundation import _load_verifier

    ok, errors, _ = _load_verifier().verify(export_dir)
    assert not ok
    assert any("hash mismatch: raw/agent_use_case_analyst_trace.json" in error for error in errors)


def test_evaluation_battery_scores_use_case_analyst_lane_safety():
    scenario = thin_evaluation_scenarios()[0]
    observation = ScenarioObservation(
        scenario_id=scenario.scenario_id,
        aws_claims_have_evidence=False,
        missing_evidence_labeled=True,
        pricing_labels=["scenario_assumed"],
        diagram_fallback_recorded=True,
        repair_actions=["Ask for volume"],
        analyst_domain_workload_labeled=False,
        analyst_missing_facts_detected=False,
        analyst_conflicts_recorded=False,
        analyst_deterministic_facts_not_overwritten=False,
        analyst_trace_hash_present=False,
        analyst_candidate_services_not_architecture=False,
        analyst_pricing_drivers_not_bound=False,
    )

    metrics, findings = score_scenario(scenario, observation)
    failed = {metric.metric_id.rsplit(".", 1)[1] for metric in metrics if not metric.passed and metric.score_type == "auto"}

    assert "analyst_domain_workload_labeling" in failed
    assert "analyst_missing_facts" in failed
    assert "analyst_no_deterministic_overwrite" in failed
    assert "analyst_candidate_services_not_architecture" in failed
    assert "analyst_pricing_drivers_not_bound" in failed
    assert any(finding.lane == "use_case_analyst" and finding.severity == "critical" for finding in findings)
    result = run_evaluation_battery([scenario])
    score = next(item for item in result.lane_scores if item.lane == "use_case_analyst")
    assert score.score_type == "mixed"
    assert score.confidence_label == "requires_human_review"
