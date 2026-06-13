from __future__ import annotations

import json
from zipfile import ZipFile

import pytest

from app.core.config import get_settings
from app.db.session_store import SessionStore
from app.services.agentic.architecture_candidate_agent import (
    ArchitectureCandidateProposal,
    ArchitectureComponentCandidate,
    ArchitectureControlCandidate,
    ArchitectureFlowCandidate,
    DeterministicFixtureArchitectureCandidateProvider,
    LiveArchitectureCandidateProvider,
    build_architecture_candidate_context,
    build_architecture_candidate_trace,
    validate_architecture_candidate_proposal,
)
from app.services.agentic.evaluation import ScenarioObservation, run_evaluation_battery, score_scenario
from app.services.agentic.evaluation_scenarios import thin_evaluation_scenarios
from app.services.agentic.provenance import MODEL_PROPOSED, can_unlock_readiness
from app.services.export_package import ExportPackageService
from app.services.synthesis import SynthesisEngine
from tests.test_d21_agentic_foundation import _load_verifier


def _architecture_context() -> dict:
    return {
        "deterministic_component_ids": ["api", "lambda", "store"],
        "deterministic_services": ["Amazon API Gateway", "AWS Lambda", "Amazon DynamoDB"],
        "deterministic_flow_ids": ["request_flow"],
        "known_data_classes": ["customer_data"],
        "known_trust_boundaries": ["application", "data"],
        "pricing_services": ["AWS Lambda", "Amazon DynamoDB"],
        "procurement_ready": False,
        "readiness_status": "directional_only",
        "architecture_critique_ref": [
            {
                "mode": "production",
                "architecture_id": "production",
                "critique": {"passed": True, "findings": [], "enhancement_status": "deterministic_fallback"},
            }
        ],
    }


def test_architecture_candidate_flag_defaults_false_and_provider_not_invoked(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.delenv("ARCHWAY_ENABLE_AGENTIC_ARCHITECTURE", raising=False)
    get_settings.cache_clear()

    class ExplodingProvider:
        provider_name = "explode"

        def propose(self, context):  # pragma: no cover
            raise AssertionError("architecture candidate provider should not be invoked")

        def validate(self, proposal, deterministic_context):  # pragma: no cover
            raise AssertionError("architecture candidate provider should not be invoked")

    trace = build_architecture_candidate_trace(settings=get_settings(), context=_architecture_context(), provider=ExplodingProvider())

    assert get_settings().enable_agentic_architecture is False
    assert trace.enabled is False
    assert trace.provider == "disabled"
    assert trace.human_review_gate.required is True
    assert trace.human_review_gate.status == "not_reviewed"
    assert trace.proposal.procurement_cap is True
    assert trace.critique.can_affect_client is False
    assert trace.critique.can_affect_procurement is False
    assert trace.decisions[0].decision == "blocked_from_authority"


def test_live_architecture_candidate_provider_degrades_without_live_demo():
    provider = LiveArchitectureCandidateProvider()
    proposal = provider.propose({})
    assert provider.last_call is not None
    assert provider.last_call.status == "not_attempted"
    assert proposal.open_questions


def test_architecture_candidate_fixture_provider_is_deterministic(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.setenv("ARCHWAY_ENABLE_AGENTIC_ARCHITECTURE", "true")
    get_settings.cache_clear()
    context = _architecture_context()
    provider = DeterministicFixtureArchitectureCandidateProvider()

    trace = build_architecture_candidate_trace(settings=get_settings(), context=context, provider=provider)
    again = build_architecture_candidate_trace(settings=get_settings(), context=context, provider=provider)

    assert trace.enabled is True
    assert trace.provider == "deterministic_fixture"
    assert trace.input_hash == again.input_hash
    assert trace.output_hash == again.output_hash
    assert trace.proposal.output_hash == again.proposal.output_hash
    assert trace.human_review_gate.status == "not_reviewed"
    assert trace.proposal.procurement_cap is True
    assert trace.critique.human_review_required is True
    assert any(item.decision == "blocked_from_authority" for item in trace.decisions)


def test_architecture_candidate_validation_keeps_candidates_out_of_authority_surfaces():
    proposal = ArchitectureCandidateProposal(
        proposal_id="architecture_candidate_unit",
        title="Unit architecture candidate",
        candidate_components=[
            ArchitectureComponentCandidate(
                component_id="api",
                label="API",
                service_hint="Amazon API Gateway",
                role="Existing API",
                data_class="customer_data",
                trust_boundary="application",
                provenance="derived",
            ),
            ArchitectureComponentCandidate(
                component_id="candidate_vector_store",
                label="Candidate Vector Store",
                service_hint="Amazon OpenSearch Serverless",
                role="Candidate retrieval store",
                data_class="customer_data",
                provenance="model_proposed",
            ),
        ],
        candidate_flows=[
            ArchitectureFlowCandidate(
                flow_id="known_flow_candidate",
                source="api",
                target="lambda",
                flow_type="request",
                data_class="customer_data",
                security_controls=["identity", "audit"],
                provenance="derived",
            ),
            ArchitectureFlowCandidate(
                flow_id="unknown_flow_candidate",
                source="ghost",
                target="lambda",
                flow_type="request",
                data_class="customer_data",
                provenance="model_proposed",
            ),
        ],
        trust_boundaries=["application"],
        data_classes=["customer_data"],
        security_controls=[
            ArchitectureControlCandidate(
                control_id="audit_control",
                control_type="audit",
                target_components=["api"],
                rationale="Known component audit control.",
                evidence_refs=["deterministic_architecture"],
                provenance="derived",
            ),
            ArchitectureControlCandidate(
                control_id="unknown_control",
                control_type="network",
                target_components=["ghost"],
                rationale="Unknown control target.",
                evidence_refs=[],
                provenance="model_proposed",
            ),
        ],
        reliability_controls=[],
        observability_controls=[],
        failure_modes=["Candidate may add latency."],
        assumptions=["Candidate not applied."],
        risks=["Needs human review."],
        open_questions=["Promote later?"],
        human_review_required=False,
        procurement_cap=False,
        input_hash="sha256:input",
        output_hash="sha256:output",
    )

    trace = validate_architecture_candidate_proposal(proposal, _architecture_context(), provider_name="unit")
    component_statuses = {item.component_id: item.accepted_status for item in trace.proposal.candidate_components}
    flow_decisions = {item.target_id: item.decision for item in trace.decisions if item.target_type == "flow"}
    finding_categories = {item.category for item in trace.critique.findings}

    assert component_statuses["api"] == "pattern_backed"
    assert component_statuses["candidate_vector_store"] == "needs_review"
    assert flow_decisions["known_flow_candidate"] == "accepted_for_audit"
    assert flow_decisions["unknown_flow_candidate"] == "rejected"
    assert "unsupported_service_claim" in finding_categories
    assert "missing_trust_boundary" in finding_categories
    assert "human_review_required" in finding_categories
    assert "procurement_cap" in finding_categories
    assert trace.critique.structural_status == "block"
    assert trace.proposal.human_review_required is True
    assert trace.proposal.procurement_cap is True
    assert trace.human_review_gate.status == "not_reviewed"
    assert not can_unlock_readiness(MODEL_PROPOSED)


def test_build_architecture_candidate_context_reads_deterministic_architecture_and_critiques():
    context = build_architecture_candidate_context(
        architectures=[
            {
                "id": "production",
                "mode": "production",
                "components": [
                    {"id": "api", "service": "Amazon API Gateway", "data_class": "customer_data", "trust_boundary": "application"},
                    {"id": "lambda", "service": "AWS Lambda", "data_class": "customer_data", "trust_boundary": "application"},
                ],
                "flows": [{"id": "request_flow", "source": "api", "target": "lambda", "data_class": "customer_data"}],
                "metadata": {"architecture_critique": {"passed": True, "findings": []}},
            }
        ],
        pricing={"line_items": [{"service": "AWS Lambda"}], "metadata": {"procurement_ready": False}},
        report={"metadata": {"customer_readiness": {"status": "directional_only"}}},
    )

    assert "api" in context["deterministic_component_ids"]
    assert "Amazon API Gateway" in context["deterministic_services"]
    assert "request_flow" in context["deterministic_flow_ids"]
    assert context["architecture_critique_ref"]


def test_export_emits_architecture_candidate_raw_audit_only_and_verifier_hashes(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.delenv("ARCHWAY_ENABLE_AGENTIC_ARCHITECTURE", raising=False)
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
        trace = json.loads(archive.read("raw/agent_architecture_candidate_trace.json").decode("utf-8"))
        proposal = json.loads(archive.read("raw/agent_architecture_candidate_proposal.json").decode("utf-8"))
        client_text = "\n".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in names
            if name.startswith("client_pack/") and not name.endswith("/")
        ).lower()

    assert "raw/agent_architecture_candidate_trace.json" in names
    assert "raw/agent_architecture_candidate_proposal.json" in names
    assert "audit_pack/agentic-architecture-candidates.md" in names
    assert "client_pack/agentic-architecture-candidates.md" not in names
    assert "agentic architecture candidate" not in client_text
    assert "agent_architecture_candidate" not in client_text
    assert trace["enabled"] is False
    assert trace["provider"] == "disabled"
    assert trace["human_review_gate"]["status"] == "not_reviewed"
    assert trace["critique"]["can_affect_client"] is False
    assert trace["critique"]["can_affect_procurement"] is False
    assert proposal["lane"] == "architecture"
    assert proposal["procurement_cap"] is True

    manifest = json.loads((export_dir / "dossier_manifest.json").read_text(encoding="utf-8"))
    inventory_paths = {item["path"] for item in manifest["artifact_inventory"]}
    assert "raw/agent_architecture_candidate_trace.json" in inventory_paths
    assert "audit_pack/agentic-architecture-candidates.md" in inventory_paths
    assert manifest["identity"]["feature_flags"]["enable_agentic_architecture"] is False

    ok, errors, _ = _load_verifier().verify(export_dir)
    assert ok, errors

    (export_dir / "raw/agent_architecture_candidate_trace.json").write_text("[]\n", encoding="utf-8")
    ok, errors, _ = _load_verifier().verify(export_dir)
    assert not ok
    assert any("hash mismatch: raw/agent_architecture_candidate_trace.json" in error for error in errors)


def test_evaluation_battery_scores_architecture_candidate_safety():
    scenario = thin_evaluation_scenarios()[0]
    observation = ScenarioObservation(
        scenario_id=scenario.scenario_id,
        aws_claims_have_evidence=False,
        missing_evidence_labeled=True,
        pricing_labels=["scenario_assumed"],
        diagram_fallback_recorded=True,
        repair_actions=["Ask for volume"],
        architecture_candidate_schema_valid=False,
        architecture_candidate_no_semantic_spec_mutation=False,
        architecture_candidate_no_flowledger_mutation=False,
        architecture_candidate_no_diagram_mutation=False,
        architecture_candidate_no_client_surface=False,
        architecture_candidate_human_review_gate_present=False,
        architecture_candidate_procurement_cap_enforced=False,
        architecture_candidate_critique_ref_present=False,
        architecture_candidate_unsupported_claims_flagged=False,
        architecture_candidate_trace_hash_present=False,
    )

    metrics, findings = score_scenario(scenario, observation)
    failed = {metric.metric_id.rsplit(".", 1)[1] for metric in metrics if not metric.passed and metric.score_type == "auto"}

    assert "architecture_candidate_schema_valid" in failed
    assert "architecture_candidate_no_semantic_spec_mutation" in failed
    assert "architecture_candidate_procurement_cap" in failed
    assert any(finding.lane == "architecture" and finding.severity == "critical" for finding in findings)

    result = run_evaluation_battery([scenario])
    architecture_score = next(item for item in result.lane_scores if item.lane == "architecture")
    assert architecture_score.score_type == "mixed"
    assert architecture_score.confidence_label == "requires_human_review"
