from __future__ import annotations

import asyncio
import json
from pathlib import Path
from zipfile import ZipFile

import app.api.routes as routes
from app.api.routes import _latest_live_agent_status
from app.core.config import get_settings
from app.db.session_store import SessionStore
from app.services.agentic.architecture_candidate_agent import ArchitectureCandidateProposal
from app.services.agentic.diagram_planning_agent import DiagramViewPlanProposal
from app.services.agentic.live_bedrock_harness import (
    LiveRunContext,
    live_call,
    live_demo_sensitivity_reason,
    reset_live_budget,
)
from app.services.agentic.narrative_agent import NarrativeRewriteProposal
from app.services.agentic.pricing_dimension_agent import PricingDimensionProposal
from app.services.agentic.research_agent import ResearchSynthesis
from app.services.agentic.reviewer_agent import ReviewerFindingProposal, ReviewerFindingSet
from app.services.agentic.use_case_analyst import UseCaseAnalystProposal
from app.services.export_package import ExportPackageService
from app.services.llm.base import LLMMessage, LLMResult, LLMTaskType
from app.services.llm.model_router import SONNET_TASKS
from app.services.synthesis import SynthesisEngine


_D22_TASKS = {
    LLMTaskType.live_use_case_analyst,
    LLMTaskType.live_pricing_dimension,
    LLMTaskType.live_research_synthesis,
    LLMTaskType.live_architecture_candidate,
    LLMTaskType.live_diagram_planning,
    LLMTaskType.live_narrative_synthesis,
    LLMTaskType.live_reviewer_critique,
}


def _configure_live_demo(monkeypatch, tmp_path, *, max_calls: int = 12) -> None:
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.setenv("ARCHWAY_AGENTIC_MODE", "live_demo")
    monkeypatch.setenv("ARCHWAY_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("ARCHWAY_BEDROCK_MODEL_ID", "anthropic.test-model")
    monkeypatch.setenv("ARCHWAY_AGENTIC_MAX_BEDROCK_CALLS", str(max_calls))
    for key in (
        "ARCHWAY_ENABLE_AGENTIC_RESEARCH",
        "ARCHWAY_ENABLE_AGENTIC_USE_CASE_ANALYST",
        "ARCHWAY_ENABLE_AGENTIC_PRICING",
        "ARCHWAY_ENABLE_AGENTIC_NARRATIVE",
        "ARCHWAY_ENABLE_AGENTIC_REVIEWER",
        "ARCHWAY_ENABLE_AGENTIC_DIAGRAM_PLANNER",
        "ARCHWAY_ENABLE_AGENTIC_ARCHITECTURE",
    ):
        monkeypatch.setenv(key, "true")
    get_settings.cache_clear()
    reset_live_budget()


def _parsed_for_schema(response_schema):
    common = {"input_hash": "sha256:test-input", "output_hash": "sha256:test-output"}
    if response_schema is UseCaseAnalystProposal:
        return UseCaseAnalystProposal(
            proposal_id="live_use_case",
            domain_candidates=[],
            workload_family_candidates=[],
            follow_up_questions=["Confirm expected monthly usage and data sensitivity."],
            **common,
        )
    if response_schema is PricingDimensionProposal:
        return PricingDimensionProposal(
            proposal_id="live_pricing",
            ambiguities=["Confirm service-specific usage quantities before pricing promotion."],
            not_estimated_reasons=["Live proposal remains audit-only until deterministic binding confirms rates and quantities."],
            **common,
        )
    if response_schema is ResearchSynthesis:
        return ResearchSynthesis(
            synthesis_id="live_research",
            summary="Live research synthesis proposes gaps only; deterministic evidence remains authoritative.",
            gaps=["Fresh AWS Docs/Pricing citations still require authoritative retrieval."],
            provenance="model_proposed",
        )
    if response_schema is ArchitectureCandidateProposal:
        return ArchitectureCandidateProposal(
            proposal_id="live_architecture",
            title="Live candidate architecture",
            open_questions=["Human review must approve architecture soundness."],
            **common,
        )
    if response_schema is DiagramViewPlanProposal:
        return DiagramViewPlanProposal(
            proposal_id="live_diagram",
            rationale="Live diagram plan remains an audit-only candidate.",
            **common,
        )
    if response_schema is NarrativeRewriteProposal:
        return NarrativeRewriteProposal(
            proposal_id="live_narrative",
            target_artifact="audit_pack",
            target_section="executive_summary",
            original_text_hash="sha256:original",
            proposed_text="Audit-only narrative proposal; deterministic claims remain authoritative.",
            unsupported_sentence_ids=["live_narrative_audit_only"],
            **common,
        )
    if response_schema is ReviewerFindingSet:
        return ReviewerFindingSet(findings=[
            ReviewerFindingProposal(
                finding_id="live_reviewer_audit_only",
                severity="advisory",
                target_artifact="audit_pack",
                message="Live reviewer output remains audit-only.",
            )
        ])
    raise AssertionError(f"unhandled schema: {response_schema}")


async def _fake_complete(self, task, messages, response_schema=None, **kwargs):  # noqa: ARG001
    parsed = _parsed_for_schema(response_schema)
    return LLMResult(
        provider="bedrock",
        model_id="anthropic.test-model",
        text=parsed.model_dump_json(),
        parsed=parsed,
        validated=True,
        duration_ms=7,
        retry_count=0,
        token_usage=None,
    )


async def _unexpected_complete(self, *args, **kwargs):  # noqa: ARG001
    raise AssertionError("Bedrock should not be called")


async def _malformed_complete(self, task, messages, response_schema=None, **kwargs):  # noqa: ARG001
    return LLMResult(
        provider="bedrock",
        model_id="anthropic.test-model",
        text='{"not": "the expected schema"}',
        parsed=None,
        validated=False,
        duration_ms=5,
        retry_count=0,
        token_usage={"input_tokens": 10, "output_tokens": 4},
    )


async def _failing_complete(self, task, messages, response_schema=None, **kwargs):  # noqa: ARG001
    raise RuntimeError("synthetic Bedrock failure")


def test_d22_spec_is_committed_with_live_demo_completion_invariant():
    doc = Path("docs/rc2/D22_LIVE_BEDROCK_AGENTIC_DEMO.md").read_text(encoding="utf-8")
    assert "ARCHWAY_AGENTIC_MODE=live_demo" in doc
    assert "raw/live_agent_calls.json" in doc
    assert "setup-required" in doc
    assert "Every submitted use case completes with artifacts" in doc


def test_live_task_types_are_routed_to_sonnet():
    assert _D22_TASKS <= SONNET_TASKS


def test_live_call_setup_required_does_not_invoke_bedrock(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.setenv("ARCHWAY_AGENTIC_MODE", "live_demo")
    monkeypatch.setenv("ARCHWAY_LLM_PROVIDER", "bedrock")
    monkeypatch.delenv("ARCHWAY_BEDROCK_MODEL_ID", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr("app.services.agentic.live_bedrock_harness.ModelRouter.complete", _unexpected_complete)

    result = live_call(
        LLMTaskType.live_use_case_analyst,
        [LLMMessage(role="user", content="Build a workflow app.")],
        UseCaseAnalystProposal,
        session_id="sess_test",
        lane="use_case_analyst",
        run_context=LiveRunContext(session_id="sess_test"),
    )

    assert result.audit.status == "setup_required"
    assert result.audit.error_type == "bedrock_not_configured"
    assert result.parsed is None


def test_live_call_setup_required_when_provider_is_not_bedrock(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.setenv("ARCHWAY_AGENTIC_MODE", "live_demo")
    monkeypatch.setenv("ARCHWAY_LLM_PROVIDER", "deterministic")
    monkeypatch.setenv("ARCHWAY_BEDROCK_MODEL_ID", "anthropic.test-model")
    get_settings.cache_clear()
    monkeypatch.setattr("app.services.agentic.live_bedrock_harness.ModelRouter.complete", _unexpected_complete)

    result = live_call(
        LLMTaskType.live_use_case_analyst,
        [LLMMessage(role="user", content="Build a workflow app.")],
        UseCaseAnalystProposal,
        session_id="sess_wrong_provider",
        lane="use_case_analyst",
        run_context=LiveRunContext(session_id="sess_wrong_provider"),
    )

    assert result.audit.status == "setup_required"
    assert result.audit.provider == "setup_required"
    assert result.audit.error_type == "bedrock_not_configured"


def test_live_call_sensitivity_skips_without_blocking_hipaa_topics(monkeypatch, tmp_path):
    _configure_live_demo(monkeypatch, tmp_path)
    monkeypatch.setattr("app.services.agentic.live_bedrock_harness.ModelRouter.complete", _unexpected_complete)

    assert live_demo_sensitivity_reason("Build a HIPAA care coordination assistant for diagnosis coding.") is None
    result = live_call(
        LLMTaskType.live_use_case_analyst,
        [LLMMessage(role="user", content="Build a workflow app.")],
        UseCaseAnalystProposal,
        session_id="sess_sensitive",
        lane="use_case_analyst",
        run_context=LiveRunContext(session_id="sess_sensitive"),
        sensitivity_text="Patient MRN: 123456 needs follow-up.",
    )

    assert result.audit.status == "skipped"
    assert result.audit.skip_reason == "sensitive_value:medical_record_number"


def test_live_call_budget_zero_records_not_attempted(monkeypatch, tmp_path):
    _configure_live_demo(monkeypatch, tmp_path, max_calls=0)
    monkeypatch.setattr("app.services.agentic.live_bedrock_harness.ModelRouter.complete", _unexpected_complete)

    result = live_call(
        LLMTaskType.live_use_case_analyst,
        [LLMMessage(role="user", content="Build a workflow app.")],
        UseCaseAnalystProposal,
        session_id="sess_budget",
        lane="use_case_analyst",
        run_context=LiveRunContext(session_id="sess_budget"),
    )

    assert result.audit.status == "not_attempted"
    assert result.audit.skip_reason == "budget_exhausted"
    assert result.audit.budget_state.state == "budget_exhausted"


def test_live_call_malformed_response_rejected_and_hash_recorded(monkeypatch, tmp_path):
    _configure_live_demo(monkeypatch, tmp_path)
    monkeypatch.setattr("app.services.agentic.live_bedrock_harness.ModelRouter.complete", _malformed_complete)

    result = live_call(
        LLMTaskType.live_use_case_analyst,
        [LLMMessage(role="user", content="Build a workflow app.")],
        UseCaseAnalystProposal,
        session_id="sess_malformed",
        lane="use_case_analyst",
        run_context=LiveRunContext(session_id="sess_malformed"),
    )

    assert result.audit.provider == "bedrock"
    assert result.audit.status == "rejected"
    assert result.audit.error_type == "structured_output_invalid"
    assert result.audit.response_hash
    assert result.parsed is None


def test_live_call_failure_records_failed_and_continues(monkeypatch, tmp_path):
    _configure_live_demo(monkeypatch, tmp_path)
    monkeypatch.setattr("app.services.agentic.live_bedrock_harness.ModelRouter.complete", _failing_complete)

    result = live_call(
        LLMTaskType.live_use_case_analyst,
        [LLMMessage(role="user", content="Build a workflow app.")],
        UseCaseAnalystProposal,
        session_id="sess_failed",
        lane="use_case_analyst",
        run_context=LiveRunContext(session_id="sess_failed"),
    )

    assert result.audit.provider == "bedrock"
    assert result.audit.status == "failed"
    assert result.audit.error_type == "RuntimeError"
    assert "synthetic Bedrock failure" in (result.audit.error_message or "")
    assert result.parsed is None


def test_live_call_bridge_works_inside_running_event_loop(monkeypatch, tmp_path):
    _configure_live_demo(monkeypatch, tmp_path)
    monkeypatch.setattr("app.services.agentic.live_bedrock_harness.ModelRouter.complete", _fake_complete)

    async def _inside_loop():
        return live_call(
            LLMTaskType.live_use_case_analyst,
            [LLMMessage(role="user", content="Build a workflow app.")],
            UseCaseAnalystProposal,
            session_id="sess_async",
            lane="use_case_analyst",
            run_context=LiveRunContext(session_id="sess_async"),
        )

    result = asyncio.run(_inside_loop())

    assert result.audit.status == "accepted"
    assert isinstance(result.parsed, UseCaseAnalystProposal)


def test_export_completes_without_starting_setup_required_live_records(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.setenv("ARCHWAY_AGENTIC_MODE", "live_demo")
    monkeypatch.setenv("ARCHWAY_LLM_PROVIDER", "deterministic")
    monkeypatch.setenv("ARCHWAY_BEDROCK_MODEL_ID", "anthropic.test-model")
    for key in (
        "ARCHWAY_ENABLE_AGENTIC_RESEARCH",
        "ARCHWAY_ENABLE_AGENTIC_USE_CASE_ANALYST",
        "ARCHWAY_ENABLE_AGENTIC_PRICING",
        "ARCHWAY_ENABLE_AGENTIC_NARRATIVE",
        "ARCHWAY_ENABLE_AGENTIC_REVIEWER",
        "ARCHWAY_ENABLE_AGENTIC_DIAGRAM_PLANNER",
        "ARCHWAY_ENABLE_AGENTIC_ARCHITECTURE",
    ):
        monkeypatch.setenv(key, "true")
    get_settings.cache_clear()
    reset_live_budget()
    monkeypatch.setattr("app.services.agentic.live_bedrock_harness.ModelRouter.complete", _unexpected_complete)
    store = SessionStore()
    brief = SynthesisEngine().create_initial_brief("Build an AWS support assistant for field teams.")
    session = store.create("Build an AWS support assistant for field teams.", brief)
    service = ExportPackageService()

    bundle = service.generate(session.id)
    zip_path = service.artifacts.resolve(session.id, bundle.artifact_id)

    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        live_calls = json.loads(archive.read("raw/live_agent_calls.json").decode("utf-8"))

    assert "manifest.json" in names
    assert "raw/live_agent_calls.json" in names
    assert "audit_pack/live-agent-calls.md" in names
    assert live_calls == []


def test_live_status_endpoint_summarizes_latest_export(monkeypatch, tmp_path):
    _configure_live_demo(monkeypatch, tmp_path)
    monkeypatch.setattr("app.services.agentic.live_bedrock_harness.ModelRouter.complete", _unexpected_complete)
    store = SessionStore()
    brief = SynthesisEngine().create_initial_brief("Build an AWS support assistant for field teams.")
    session = store.create("Build an AWS support assistant for field teams.", brief)
    service = ExportPackageService()
    service.generate(session.id)
    monkeypatch.setattr(routes, "artifacts", service.artifacts)

    status = _latest_live_agent_status(session.id)

    assert status["has_export_trace"] is True
    assert status["bedrock_accepted"] == 0
    assert status["setup_required"] == 0
    assert status["failed"] == 0
    assert "audit-only or skipped" in status["message"]


def test_export_writes_live_call_file_raw_and_audit_only_without_fresh_bedrock(monkeypatch, tmp_path):
    _configure_live_demo(monkeypatch, tmp_path)
    monkeypatch.setattr("app.services.agentic.live_bedrock_harness.ModelRouter.complete", _unexpected_complete)
    store = SessionStore()
    brief = SynthesisEngine().create_initial_brief("Build a claims intake assistant for a healthcare operations team.")
    session = store.create("Build a claims intake assistant for a healthcare operations team.", brief)
    service = ExportPackageService()

    bundle = service.generate(session.id)
    zip_path = service.artifacts.resolve(session.id, bundle.artifact_id)
    export_dir = service.artifacts.session_root(session.id) / "exports" / bundle.name

    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        live_calls = json.loads(archive.read("raw/live_agent_calls.json").decode("utf-8"))

    assert "raw/live_agent_calls.json" in names
    assert "audit_pack/live-agent-calls.md" in names
    assert "client_pack/live-agent-calls.md" not in names
    assert live_calls == []

    manifest = json.loads((export_dir / "dossier_manifest.json").read_text(encoding="utf-8"))
    flags = manifest["identity"]["feature_flags"]
    assert flags["agentic_mode"] == "live_demo"
    assert flags["live_bedrock_call_count"] == 0
    assert "raw/live_agent_calls.json" in {item["path"] for item in manifest["artifact_inventory"]}
