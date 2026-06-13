from __future__ import annotations

import json
from zipfile import ZipFile

import pytest

from app.core.config import get_settings
from app.db.session_store import SessionStore
from app.services.agentic.diagram_planning_agent import (
    DeterministicFixtureDiagramPlanningProvider,
    DiagramViewCandidate,
    DiagramViewPlanProposal,
    LiveDiagramPlanningProvider,
    build_diagram_planning_context,
    build_diagram_planning_trace,
    validate_diagram_plan_proposal,
)
from app.services.agentic.evaluation import ScenarioObservation, run_evaluation_battery, score_scenario
from app.services.agentic.evaluation_scenarios import thin_evaluation_scenarios
from app.services.agentic.provenance import MODEL_PROPOSED, can_unlock_readiness
from app.services.export_package import ExportPackageService
from app.services.synthesis import SynthesisEngine
from tests.test_d21_agentic_foundation import _load_verifier


def _diagram_context() -> dict:
    return {
        "known_nodes": ["api", "lambda"],
        "known_flows": ["request_flow"],
        "deterministic_view_ids": ["production_logical_service_flow", "telemetry_ingestion_view"],
        "rendered_view_ids": ["production_logical_service_flow"],
        "supported_view_types": ["production_logical_service_flow", "logical_service_flow", "telemetry_ingestion_view"],
        "unsupported_view_ids": ["unsupported_customer_journey_view"],
        "fallback_view_ids": ["telemetry_ingestion_view"],
        "compiler_ledger": {
            "rendered_via_broader_supported_view": [
                {
                    "mode": "production",
                    "view_id": "telemetry_ingestion_view",
                    "compiler_view_id": "async_flow_view",
                    "reason": "Rendered through broader supported view.",
                }
            ]
        },
        "ledger_by_view": {
            "telemetry_ingestion_view": {
                "mode": "production",
                "view_id": "telemetry_ingestion_view",
                "compiler_view_id": "async_flow_view",
                "ledger_bucket": "rendered_via_broader_supported_view",
            }
        },
    }


def test_diagram_planner_flag_defaults_false_and_provider_not_invoked(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.delenv("ARCHWAY_ENABLE_AGENTIC_DIAGRAM_PLANNER", raising=False)
    get_settings.cache_clear()

    class ExplodingProvider:
        provider_name = "explode"

        def propose(self, context):  # pragma: no cover
            raise AssertionError("diagram planner provider should not be invoked")

        def validate(self, proposal, deterministic_context):  # pragma: no cover
            raise AssertionError("diagram planner provider should not be invoked")

    trace = build_diagram_planning_trace(settings=get_settings(), context={}, provider=ExplodingProvider())

    assert get_settings().enable_agentic_diagram_planner is False
    assert trace.enabled is False
    assert trace.provider == "disabled"
    assert trace.decisions[0].decision == "ignored"
    assert trace.output_hash.startswith("sha256:")


def test_live_diagram_planner_provider_degrades_without_live_demo():
    provider = LiveDiagramPlanningProvider()
    proposal = provider.propose({})
    assert provider.last_call is not None
    assert provider.last_call.status == "not_attempted"
    assert proposal.rationale


def test_diagram_planner_fixture_provider_is_deterministic(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.setenv("ARCHWAY_ENABLE_AGENTIC_DIAGRAM_PLANNER", "true")
    get_settings.cache_clear()
    context = _diagram_context()
    provider = DeterministicFixtureDiagramPlanningProvider()

    trace = build_diagram_planning_trace(settings=get_settings(), context=context, provider=provider)
    again = build_diagram_planning_trace(settings=get_settings(), context=context, provider=provider)

    assert trace.enabled is True
    assert trace.provider == "deterministic_fixture"
    assert trace.input_hash == again.input_hash
    assert trace.output_hash == again.output_hash
    assert trace.proposal.output_hash == again.proposal.output_hash
    assert trace.proposal.candidate_views[0].accepted_status in {"accepted", "fallback"}


def test_diagram_plan_validation_rejects_authority_leaks_and_records_fallbacks():
    proposal = DiagramViewPlanProposal(
        proposal_id="diagram_plan_unit",
        candidate_views=[
            DiagramViewCandidate(
                view_id="production_logical_service_flow",
                view_type="production_logical_service_flow",
                display_label="Production Flow",
                purpose="Existing deterministic view.",
                intended_nodes=["api"],
                intended_flows=["request_flow"],
                claims_rendered=True,
            ),
            DiagramViewCandidate(
                view_id="production_logical_service_flow",
                view_type="production_logical_service_flow",
                display_label="Duplicate Production Flow",
                purpose="Duplicate deterministic view.",
            ),
            DiagramViewCandidate(
                view_id="unsupported_customer_journey_view",
                view_type="unsupported_customer_journey_view",
                display_label="Customer Journey",
                purpose="Unsupported view.",
            ),
            DiagramViewCandidate(
                view_id="unknown_node_view",
                view_type="logical_service_flow",
                display_label="Unknown Node",
                purpose="References an unknown node.",
                intended_nodes=["ghost"],
            ),
            DiagramViewCandidate(
                view_id="unknown_flow_view",
                view_type="logical_service_flow",
                display_label="Unknown Flow",
                purpose="References an unknown flow.",
                intended_flows=["ghost_flow"],
            ),
            DiagramViewCandidate(
                view_id="render_claim_without_ledger",
                view_type="logical_service_flow",
                display_label="False Render Claim",
                purpose="Claims rendering without ledger.",
                claims_rendered=True,
            ),
            DiagramViewCandidate(
                view_id="telemetry_ingestion_view",
                view_type="telemetry_ingestion_view",
                display_label="Telemetry",
                purpose="Fallback view.",
                accepted_status="fallback",
            ),
            DiagramViewCandidate(
                view_id="architecture_mutation_view",
                view_type="logical_service_flow",
                display_label="Mutation",
                purpose="Would require architecture changes.",
                requires_architecture_changes=True,
            ),
        ],
        rationale="Unit validation matrix.",
        input_hash="sha256:input",
        output_hash="sha256:output",
    )

    trace = validate_diagram_plan_proposal(proposal, _diagram_context(), provider_name="unit")
    decisions = {item.view_id: item.decision for item in trace.decisions if item.view_id != "production_logical_service_flow"}
    production_decisions = [item.decision for item in trace.decisions if item.view_id == "production_logical_service_flow"]
    statuses = {item.view_id: item.accepted_status for item in trace.proposal.candidate_views}

    assert production_decisions == ["accepted_for_audit", "ignored"]
    assert decisions["unsupported_customer_journey_view"] == "unsupported"
    assert decisions["unknown_node_view"] == "rejected"
    assert decisions["unknown_flow_view"] == "rejected"
    assert decisions["render_claim_without_ledger"] == "rejected"
    assert decisions["telemetry_ingestion_view"] == "fallback_recorded"
    assert decisions["architecture_mutation_view"] == "rejected"
    assert statuses["telemetry_ingestion_view"] == "fallback"
    assert not can_unlock_readiness(MODEL_PROPOSED)


def test_build_diagram_planning_context_reads_rendering_ledger():
    context = build_diagram_planning_context(
        architectures=[
            {
                "mode": "production",
                "metadata": {"expected_views": ["logical_service_flow"]},
                "components": [{"id": "api", "service": "Amazon API Gateway"}],
                "flows": [{"id": "request_flow", "label": "Request"}],
            }
        ],
        diagrams=[
            {
                "mode": "production",
                "diagrams": [{"view_id": "production_logical_service_flow", "compiler_view_id": "production_logical_service_flow"}],
                "view_rendering_ledger": {
                    "unsupported_not_rendered": [
                        {"mode": "production", "view_id": "unsupported_customer_journey_view", "reason": "No renderer."}
                    ]
                },
            }
        ],
    )

    assert "api" in context["known_nodes"]
    assert "request_flow" in context["known_flows"]
    assert "production_logical_service_flow" in context["rendered_view_ids"]
    assert "unsupported_customer_journey_view" in context["unsupported_view_ids"]


def test_export_emits_diagram_planner_raw_audit_only_and_verifier_hashes(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.delenv("ARCHWAY_ENABLE_AGENTIC_DIAGRAM_PLANNER", raising=False)
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
        trace = json.loads(archive.read("raw/agent_diagram_plan_trace.json").decode("utf-8"))
        proposal = json.loads(archive.read("raw/agent_diagram_plan_proposal.json").decode("utf-8"))

    assert "raw/agent_diagram_plan_trace.json" in names
    assert "raw/agent_diagram_plan_proposal.json" in names
    assert "audit_pack/agentic-diagram-plan.md" in names
    assert "client_pack/agentic-diagram-plan.md" not in names
    assert trace["enabled"] is False
    assert trace["provider"] == "disabled"
    assert proposal["lane"] == "diagram_planner"

    manifest = json.loads((export_dir / "dossier_manifest.json").read_text(encoding="utf-8"))
    inventory_paths = {item["path"] for item in manifest["artifact_inventory"]}
    assert "raw/agent_diagram_plan_trace.json" in inventory_paths
    assert "audit_pack/agentic-diagram-plan.md" in inventory_paths

    ok, errors, _ = _load_verifier().verify(export_dir)
    assert ok, errors

    (export_dir / "raw/agent_diagram_plan_trace.json").write_text("[]\n", encoding="utf-8")
    ok, errors, _ = _load_verifier().verify(export_dir)
    assert not ok
    assert any("hash mismatch: raw/agent_diagram_plan_trace.json" in error for error in errors)


def test_evaluation_battery_scores_diagram_planning_safety():
    scenario = thin_evaluation_scenarios()[0]
    observation = ScenarioObservation(
        scenario_id=scenario.scenario_id,
        aws_claims_have_evidence=False,
        missing_evidence_labeled=True,
        pricing_labels=["scenario_assumed"],
        diagram_fallback_recorded=True,
        repair_actions=["Ask for volume"],
        diagram_plan_proposed_view_labeling=False,
        diagram_plan_unsupported_disclosure=False,
        diagram_plan_no_rendered_claim_without_ledger=False,
        diagram_plan_unknown_node_flow_rejected=False,
        diagram_plan_duplicate_handling=False,
        diagram_plan_no_client_surface=False,
        diagram_plan_no_compiler_mutation=False,
        diagram_plan_trace_hash_present=False,
    )

    metrics, findings = score_scenario(scenario, observation)
    failed = {metric.metric_id.rsplit(".", 1)[1] for metric in metrics if not metric.passed and metric.score_type == "auto"}

    assert "diagram_plan_proposed_view_labeling" in failed
    assert "diagram_plan_no_rendered_claim_without_ledger" in failed
    assert "diagram_plan_no_compiler_mutation" in failed
    assert any(finding.lane == "diagram_planner" and finding.severity == "critical" for finding in findings)

    result = run_evaluation_battery([scenario])
    diagram_score = next(item for item in result.lane_scores if item.lane == "diagram_planner")
    assert diagram_score.score_type == "mixed"
    assert diagram_score.confidence_label == "requires_human_review"
