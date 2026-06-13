from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from app.core.config import get_settings
from app.db.session_store import SessionStore
from app.services.agentic.contracts import AGENTIC_LANES, AgentRepairAction
from app.services.agentic.evaluation import is_client_agent_output_allowed, run_evaluation_battery
from app.services.agentic.evaluation_scenarios import thin_evaluation_scenarios
from app.services.agentic.provenance import MODEL_PROPOSED, can_unlock_readiness
from app.services.agentic.repair_planner import _outcome, agentic_feature_flags
from app.services.artifact_linter import lint_export_zip, summarize_findings
from app.services.capability_router import CapabilityRouter
from app.services.dossier_manifest import REQUIRED_ARTIFACTS
from app.services.export_package import ExportPackageService
from app.services.synthesis import SynthesisEngine
from scripts.d21_agentic_status import build_status
from scripts.d21_demo_readiness_check import build_report as build_demo_readiness_report
from tests.test_d21_agentic_foundation import _load_verifier

REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_CLIENT_FILES = {
    "client_pack/START_HERE.md",
    "client_pack/01-executive-memo.md",
    "client_pack/02-solution-brief.md",
    "client_pack/03-architecture-summary.md",
    "client_pack/04-pricing-summary.md",
    "client_pack/05-risks-and-gates.md",
    "client_pack/06-evidence-summary.md",
    "client_pack/07-diagrams-index.md",
}

EXPECTED_AUDIT_FILES = {
    "audit_pack/README.md",
    "audit_pack/view-fallback-notes.md",
    "audit_pack/agentic-repair-plan.md",
    "audit_pack/agentic-evaluation-summary.md",
    "audit_pack/agentic-research-summary.md",
    "audit_pack/agentic-use-case-analysis.md",
    "audit_pack/agentic-pricing-dimensions.md",
    "audit_pack/agentic-narrative-proposals.md",
    "audit_pack/agentic-reviewer-findings.md",
    "audit_pack/agentic-diagram-plan.md",
    "audit_pack/agentic-architecture-candidates.md",
}

EXPECTED_RAW_AGENT_FILES = {
    "raw/agent_runs.json",
    "raw/agent_proposals.json",
    "raw/agent_repair_plan.json",
    "raw/agent_evaluation_battery.json",
    "raw/agent_research_trace.json",
    "raw/agent_research_evidence.json",
    "raw/agent_use_case_analyst_trace.json",
    "raw/agent_use_case_analyst_proposal.json",
    "raw/agent_pricing_dimension_trace.json",
    "raw/agent_pricing_dimension_proposal.json",
    "raw/agent_narrative_trace.json",
    "raw/agent_narrative_proposals.json",
    "raw/agent_reviewer_trace.json",
    "raw/agent_reviewer_findings.json",
    "raw/agent_diagram_plan_trace.json",
    "raw/agent_diagram_plan_proposal.json",
    "raw/agent_architecture_candidate_trace.json",
    "raw/agent_architecture_candidate_proposal.json",
}

CLIENT_FORBIDDEN = {
    "agentic research",
    "agentic use-case analysis",
    "agentic pricing dimensions",
    "agentic narrative",
    "agentic reviewer",
    "agentic diagram plan",
    "agentic architecture candidate",
    "model_proposed",
    "agentproposal",
    "agentrun",
    "prompt_hash",
    "response_hash",
    "raw proposal",
    "notimplementederror",
    "archway_enable_agentic",
}


def _generate_package(tmp_path, monkeypatch, use_case: str):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    for key in (
        "ARCHWAY_ENABLE_AGENTIC_REPAIR_PLANNER",
        "ARCHWAY_ENABLE_AGENTIC_RESEARCH",
        "ARCHWAY_ENABLE_AGENTIC_USE_CASE_ANALYST",
        "ARCHWAY_ENABLE_AGENTIC_PRICING",
        "ARCHWAY_ENABLE_AGENTIC_NARRATIVE",
        "ARCHWAY_ENABLE_AGENTIC_REVIEWER",
        "ARCHWAY_ENABLE_AGENTIC_DIAGRAM_PLANNER",
        "ARCHWAY_ENABLE_AGENTIC_ARCHITECTURE",
        "ARCHWAY_LLM_PROVIDER",
    ):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    store = SessionStore()
    brief = SynthesisEngine().create_initial_brief(use_case)
    session = store.create(use_case, brief)
    service = ExportPackageService()
    bundle = service.generate(session.id)
    export_dir = service.artifacts.session_root(session.id) / "exports" / bundle.name
    zip_path = service.artifacts.resolve(session.id, bundle.artifact_id)
    return export_dir, zip_path


def test_final_d21_docs_freeze_story_and_do_not_claim_procurement_for_all():
    freeze = (REPO_ROOT / "docs/rc2/D21_AGENTIC_DEMO_READINESS_FREEZE.md").read_text(encoding="utf-8")
    decisions = (REPO_ROOT / "docs/rc2/DECISIONS.md").read_text(encoding="utf-8")
    normalized_decisions = " ".join(decisions.split())

    assert "9001b20581a39a950eef5b6bb8cd2c2c3e2fd57b" in freeze
    assert "final D21 audit-only demo freeze" in freeze
    assert "Solution package" in freeze
    assert "Directional / diagnostic package" in freeze
    assert "Unsupported / refusal package" in freeze
    assert "not every artifact is procurement-ready" in freeze.lower()
    assert "Agents propose; deterministic gates decide." in freeze
    assert "It does not add another agent lane" in decisions
    assert "Full client-facing agent output remains disabled" in normalized_decisions


def test_final_outcome_taxonomy_and_unsupported_routing_are_explicit():
    assert _outcome("workshop_ready", []) == "solution_package"
    assert _outcome("demo_ready", [AgentRepairAction(action_id="a", action="Confirm drivers", source_signal="pricing")]) == "directional_diagnostic_package"
    assert _outcome("internal_only", []) == "unsupported_refusal_package"

    unsupported = CapabilityRouter().route(
        SimpleNamespace(confidence="high", workload_families=[], domain=None),
        raw_use_case="Build for on-premises only, no cloud and do not use AWS.",
    )

    assert unsupported.status == "unsupported_or_blocked"
    assert unsupported.expected_artifact_level == "unsupported_explanation"
    assert unsupported.safe_to_generate_architecture is False
    assert unsupported.safe_to_generate_pricing is False
    assert unsupported.safe_to_generate_diagrams is False


def test_final_package_completeness_authority_and_tamper_guard(tmp_path, monkeypatch):
    export_dir, zip_path = _generate_package(
        tmp_path,
        monkeypatch,
        "Design a novel AWS-based carbon accounting data workflow with ingestion, review, dashboards, and retention controls.",
    )

    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        client_text = "\n".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in sorted(names)
            if name.startswith("client_pack/") and not name.endswith("/")
        ).lower()
        agent_run = json.loads(archive.read("raw/agent_runs.json").decode("utf-8"))[0]
        traces = {
            "research": json.loads(archive.read("raw/agent_research_trace.json").decode("utf-8")),
            "use_case": json.loads(archive.read("raw/agent_use_case_analyst_trace.json").decode("utf-8")),
            "pricing": json.loads(archive.read("raw/agent_pricing_dimension_trace.json").decode("utf-8")),
            "narrative": json.loads(archive.read("raw/agent_narrative_trace.json").decode("utf-8")),
            "reviewer": json.loads(archive.read("raw/agent_reviewer_trace.json").decode("utf-8")),
            "diagram": json.loads(archive.read("raw/agent_diagram_plan_trace.json").decode("utf-8")),
            "architecture": json.loads(archive.read("raw/agent_architecture_candidate_trace.json").decode("utf-8")),
        }

    assert EXPECTED_CLIENT_FILES.issubset(names)
    assert EXPECTED_AUDIT_FILES.issubset(names)
    assert EXPECTED_RAW_AGENT_FILES.issubset(names)
    assert agent_run["enabled_lanes"] == []
    assert all(trace["enabled"] is False for trace in traces.values())
    assert all(trace["provider"] == "disabled" for trace in traces.values())
    assert traces["architecture"]["human_review_gate"]["status"] == "not_reviewed"
    assert traces["architecture"]["proposal"]["procurement_cap"] is True

    leaked = sorted(term for term in CLIENT_FORBIDDEN if term in client_text)
    assert leaked == []

    manifest = json.loads((export_dir / "dossier_manifest.json").read_text(encoding="utf-8"))
    inventory_paths = {item["path"] for item in manifest["artifact_inventory"]}
    assert EXPECTED_CLIENT_FILES.issubset(inventory_paths)
    assert EXPECTED_AUDIT_FILES.issubset(inventory_paths)
    assert EXPECTED_RAW_AGENT_FILES.issubset(inventory_paths)
    assert all(value is False for key, value in manifest["identity"]["feature_flags"].items() if key.startswith("enable_agentic_"))

    ok, errors, _ = _load_verifier().verify(export_dir)
    assert ok, errors
    assert summarize_findings(lint_export_zip(zip_path))["total"] == 0

    raw_path = export_dir / "raw/agent_architecture_candidate_trace.json"
    raw_original = raw_path.read_text(encoding="utf-8")
    raw_path.write_text("[]\n", encoding="utf-8")
    ok, errors, _ = _load_verifier().verify(export_dir)
    assert not ok
    assert any("hash mismatch: raw/agent_architecture_candidate_trace.json" in error for error in errors)
    raw_path.write_text(raw_original, encoding="utf-8")

    audit_path = export_dir / "audit_pack/agentic-architecture-candidates.md"
    audit_path.write_text(audit_path.read_text(encoding="utf-8") + "\nTampered.\n", encoding="utf-8")
    ok, errors, _ = _load_verifier().verify(export_dir)
    assert not ok
    assert any("hash mismatch: audit_pack/agentic-architecture-candidates.md" in error for error in errors)

    report = build_demo_readiness_report([zip_path])
    assert report["passed"] is True


def test_final_authority_matrix_and_evaluation_battery_freeze(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.delenv("ARCHWAY_LLM_PROVIDER", raising=False)
    get_settings.cache_clear()

    status = build_status()
    matrix = {row["component"]: row for row in status["authority_matrix"]}
    result = run_evaluation_battery(thin_evaluation_scenarios())
    lane_scores = {score.lane: score for score in result.lane_scores}
    metric_ids = {metric.metric_id for score in result.lane_scores for metric in score.metrics}

    assert set(AGENTIC_LANES) == {
        "repair_planner",
        "research",
        "use_case_analyst",
        "pricing_dimension",
        "pricing",
        "narrative",
        "reviewer",
        "diagram_planner",
        "architecture",
    }
    assert all(value is False for value in agentic_feature_flags(get_settings()).values())
    assert status["client_pack_agent_output_enabled"] is False
    assert status["live_agent_providers_enabled"] is False
    assert status["next_recommended_mode"] == "demo/readiness freeze"

    for component, row in matrix.items():
        if component == "deterministic baseline":
            assert row["writes_client_pack"] is True
            assert row["can_affect_readiness"] is True
            assert row["can_affect_pricing_math"] is True
            assert row["can_affect_architecture_compiler_truth"] is True
            assert row["can_affect_diagram_rendering"] is True
            continue
        assert row["default_enabled"] is False
        assert row["writes_client_pack"] is False
        assert row["can_affect_readiness"] is False
        assert row["can_affect_pricing_math"] is False
        assert row["can_affect_headline_pricing"] is False
        assert row["can_affect_architecture_compiler_truth"] is False
        assert row["can_affect_diagram_rendering"] is False

    assert len(result.scenarios) == 10
    assert not result.has_critical_findings
    assert sum(1 for finding in result.findings if finding.severity == "advisory") == 70
    assert is_client_agent_output_allowed(result).client_agent_output_allowed is False
    assert lane_scores["research"].confidence_label == "requires_human_review"
    assert lane_scores["use_case_analyst"].confidence_label == "requires_human_review"
    assert lane_scores["pricing_dimension"].confidence_label == "auto_passed"
    assert lane_scores["narrative"].confidence_label == "requires_human_review"
    assert lane_scores["reviewer"].confidence_label == "requires_human_review"
    assert lane_scores["diagram_planner"].confidence_label == "requires_human_review"
    assert lane_scores["architecture"].confidence_label == "requires_human_review"
    assert any(".architecture_candidate_schema_valid" in metric_id for metric_id in metric_ids)
    assert any(".architecture_candidate_no_semantic_spec_mutation" in metric_id for metric_id in metric_ids)
    assert any(".architecture_candidate_procurement_cap" in metric_id for metric_id in metric_ids)
    assert any(".architecture_candidate_design_soundness" in metric_id for metric_id in metric_ids)
    assert not can_unlock_readiness(MODEL_PROPOSED)
    assert REQUIRED_ARTIFACTS == (
        "README.md",
        "manifest.json",
        "01-solution-brief.md",
        "03-pricing.md",
        "raw/pricing.json",
        "raw/session.json",
    )
