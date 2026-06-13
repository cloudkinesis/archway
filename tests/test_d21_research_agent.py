from __future__ import annotations

import json
from zipfile import ZipFile

import pytest

from app.core.config import get_settings
from app.db.session_store import SessionStore
from app.services.agentic.evaluation import ScenarioObservation, run_evaluation_battery, score_scenario
from app.services.agentic.evaluation_scenarios import thin_evaluation_scenarios
from app.services.agentic.research_agent import (
    DeterministicFixtureResearchProvider,
    DisabledResearchProvider,
    LiveResearchProvider,
    ResearchEvidenceItem,
    ResearchQueryPlan,
    ResearchQuestion,
    build_research_agent_trace,
    build_research_input_context,
    classify_research_status,
)
from app.services.export_package import ExportPackageService
from app.services.synthesis import SynthesisEngine


def test_research_flag_defaults_false_and_disabled_provider_does_not_invoke_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.delenv("ARCHWAY_ENABLE_AGENTIC_RESEARCH", raising=False)
    get_settings.cache_clear()

    class ExplodingProvider:
        provider_name = "explode"

        def plan_queries(self, input_context):  # pragma: no cover - should never run
            raise AssertionError("provider should not be invoked when disabled")

        def retrieve(self, plan):  # pragma: no cover
            raise AssertionError("provider should not be invoked when disabled")

        def synthesize(self, plan, evidence_items):  # pragma: no cover
            raise AssertionError("provider should not be invoked when disabled")

    settings = get_settings()
    trace = build_research_agent_trace(settings=settings, input_context={"services": ["Amazon Lex"]}, provider=ExplodingProvider())

    assert settings.enable_agentic_research is False
    assert trace.enabled is False
    assert trace.provider == "disabled"
    assert trace.synthesis.findings[0].status == "skipped"
    assert trace.evidence_items == []


def test_research_contracts_and_fixture_provider_are_deterministic(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.setenv("ARCHWAY_ENABLE_AGENTIC_RESEARCH", "true")
    get_settings.cache_clear()
    context = {
        "services": ["Amazon Lex", "Amazon Connect"],
        "pricing_evidence_gap": True,
        "compliance_context": True,
        "signals": ["unit_test"],
    }
    provider = DeterministicFixtureResearchProvider()

    trace = build_research_agent_trace(settings=get_settings(), input_context=context, provider=provider)
    trace_again = build_research_agent_trace(settings=get_settings(), input_context=context, provider=provider)

    assert trace.enabled is True
    assert trace.provider == "deterministic_fixture"
    assert trace.input_hash == trace_again.input_hash
    assert trace.output_hash == trace_again.output_hash
    assert trace.query_plan.deterministic_hash == trace_again.query_plan.deterministic_hash
    assert [item.question_id for item in trace.query_plan.questions] == sorted(item.question_id for item in trace.query_plan.questions)
    assert all(finding.status == "grounded" for finding in trace.synthesis.findings)


def test_live_research_provider_degrades_without_live_demo():
    provider = LiveResearchProvider()
    plan = provider.plan_queries({})
    synthesis = provider.synthesize(plan, [])
    assert provider.last_call is not None
    assert provider.last_call.status == "not_attempted"
    assert synthesis.gaps


def test_research_claim_rules_require_source_kind_appropriate_evidence():
    aws_docs_evidence = [ResearchEvidenceItem(evidence_id="ev_docs", source_type="aws_docs", title="Docs", claim_kinds=["aws_docs"])]
    pricing_evidence = [ResearchEvidenceItem(evidence_id="ev_price", source_type="aws_pricing", title="Pricing", claim_kinds=["aws_pricing"])]
    catalog_evidence = [ResearchEvidenceItem(evidence_id="ev_catalog", source_type="catalog", title="Catalog", claim_kinds=["architecture_rationale"])]
    contradictory_docs = [ResearchEvidenceItem(evidence_id="ev_no", source_type="aws_docs", title="Docs", claim_kinds=["aws_docs"], stance="contradicts")]

    assert classify_research_status("aws_docs", "aws_docs", aws_docs_evidence) == "grounded"
    assert classify_research_status("aws_docs", "aws_docs", catalog_evidence) == "gap"
    assert classify_research_status("aws_pricing", "aws_pricing", pricing_evidence) == "grounded"
    assert classify_research_status("aws_pricing", "aws_pricing", aws_docs_evidence) == "gap"
    assert classify_research_status("architecture_rationale", "catalog", catalog_evidence) == "grounded"
    assert classify_research_status("aws_docs", "aws_docs", contradictory_docs) == "conflict"
    assert classify_research_status("security", "aws_docs", []) == "unsupported"


def test_research_synthesis_lists_conflicting_evidence():
    provider = DeterministicFixtureResearchProvider()
    plan = ResearchQueryPlan(
        run_id="research_run_conflict",
        questions=[
            ResearchQuestion(
                question_id="rq_conflict_1",
                claim_kind="aws_docs",
                question="Which AWS documentation supports the service claim?",
                required_source_type="aws_docs",
                priority="high",
                reason="AWS claims require AWS Docs evidence.",
            )
        ],
    )
    evidence = [
        ResearchEvidenceItem(
            evidence_id="ev_conflict",
            source_type="aws_docs",
            title="Conflicting docs fixture",
            citation="fixture:conflict",
            claim_kinds=["aws_docs"],
            stance="contradicts",
        )
    ]

    synthesis = provider.synthesize(plan, evidence)

    assert synthesis.findings[0].status == "conflict"
    assert synthesis.conflicts == ["rq_conflict_1 has conflicting aws_docs evidence."]
    assert synthesis.unsupported_claims == ["Which AWS documentation supports the service claim?"]


def test_research_input_context_uses_existing_signals_only():
    context = build_research_input_context(
        brief={"title": "Use case", "use_case_profile": {"domain": "contact_center", "workload_families": ["chatbot"]}},
        report={"metadata": {"evidence_quality": {"aws_docs_available": False, "aws_pricing_available": False}}},
        pricing={"metadata": {"pricing_driver_closure": {"missing_drivers": ["monthly_text_requests"]}}},
        architectures=[{"components": [{"service": "Amazon Lex"}, {"name": "Amazon Connect"}]}],
        diagrams=[{"diagrams": [{"view_id": "logical"}]}],
        reviewer_findings=[{"finding_id": "rev_1"}],
    )

    assert context["services"] == ["Amazon Connect", "Amazon Lex"]
    assert context["pricing_evidence_gap"] is True
    assert context["docs_evidence_gap"] is True
    assert context["pricing_missing_drivers"] == ["monthly_text_requests"]
    assert context["reviewer_findings"] == ["rev_1"]


def test_export_emits_research_trace_raw_and_audit_only(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.delenv("ARCHWAY_ENABLE_AGENTIC_RESEARCH", raising=False)
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
        trace = json.loads(archive.read("raw/agent_research_trace.json").decode("utf-8"))
        evidence = json.loads(archive.read("raw/agent_research_evidence.json").decode("utf-8"))

    assert "raw/agent_research_trace.json" in names
    assert "raw/agent_research_evidence.json" in names
    assert "audit_pack/agentic-research-summary.md" in names
    assert "client_pack/agentic-research-summary.md" not in names
    assert trace["enabled"] is False
    assert trace["provider"] == "disabled"
    assert evidence == []

    manifest = json.loads((export_dir / "dossier_manifest.json").read_text(encoding="utf-8"))
    inventory_paths = {item["path"] for item in manifest["artifact_inventory"]}
    assert "raw/agent_research_trace.json" in inventory_paths

    (export_dir / "raw/agent_research_trace.json").write_text("[]\n", encoding="utf-8")
    from tests.test_d21_agentic_foundation import _load_verifier

    ok, errors, _ = _load_verifier().verify(export_dir)
    assert not ok
    assert any("hash mismatch: raw/agent_research_trace.json" in error for error in errors)


def test_evaluation_battery_scores_research_lane_safety():
    scenario = thin_evaluation_scenarios()[0]
    observation = ScenarioObservation(
        scenario_id=scenario.scenario_id,
        aws_claims_have_evidence=False,
        missing_evidence_labeled=True,
        pricing_labels=["scenario_assumed"],
        diagram_fallback_recorded=True,
        repair_actions=["Ask for volume"],
        research_source_kind_correct=False,
        research_unsupported_claims_labeled=False,
        research_trace_hash_present=False,
    )

    metrics, findings = score_scenario(scenario, observation)
    failed = {metric.metric_id.rsplit(".", 1)[1] for metric in metrics if not metric.passed and metric.score_type == "auto"}

    assert "research_source_kind" in failed
    assert "research_unsupported_labeling" in failed
    assert "research_trace_reproducibility" in failed
    assert any(finding.lane == "research" and finding.severity == "critical" for finding in findings)
    result = run_evaluation_battery([scenario])
    research_score = next(score for score in result.lane_scores if score.lane == "research")
    assert research_score.score_type == "mixed"
    assert research_score.confidence_label == "requires_human_review"
