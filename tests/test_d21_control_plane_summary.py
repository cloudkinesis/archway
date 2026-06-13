from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from zipfile import ZipFile

from app.core.config import get_settings
from app.db.session_store import SessionStore
from app.services.agentic.evaluation import is_client_agent_output_allowed, run_evaluation_battery
from app.services.agentic.evaluation_scenarios import thin_evaluation_scenarios
from app.services.agentic.provenance import MODEL_PROPOSED, can_unlock_readiness
from app.services.agentic.repair_planner import agentic_feature_flags
from app.services.dossier_manifest import REQUIRED_ARTIFACTS
from app.services.export_package import ExportPackageService
from app.services.synthesis import SynthesisEngine

from tests.test_d21_agentic_foundation import _load_verifier

REPO_ROOT = Path(__file__).resolve().parents[1]

RAW_AGENT_ARTIFACTS = {
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
}

AUDIT_AGENT_ARTIFACTS = {
    "audit_pack/agentic-repair-plan.md",
    "audit_pack/agentic-evaluation-summary.md",
    "audit_pack/agentic-research-summary.md",
    "audit_pack/agentic-use-case-analysis.md",
    "audit_pack/agentic-pricing-dimensions.md",
}

CLIENT_FORBIDDEN_TERMS = {
    "agentic research",
    "agentic use-case analysis",
    "agentic pricing",
    "model_proposed",
    "raw proposal",
    "prompt_hash",
    "response_hash",
    "agentrun",
    "agentproposal",
    "archway_enable_agentic",
    "agent_research",
    "agent_use_case_analyst",
    "agent_pricing_dimension",
}


def _load_status_script():
    spec = importlib.util.spec_from_file_location("d21_agentic_status", REPO_ROOT / "scripts/d21_agentic_status.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["d21_agentic_status"] = module
    spec.loader.exec_module(module)
    return module


def _generate_package(tmp_path, monkeypatch):
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
    brief = SynthesisEngine().create_initial_brief("Build a retail support assistant for order questions.")
    session = store.create("Build a retail support assistant for order questions.", brief)
    service = ExportPackageService()
    bundle = service.generate(session.id)
    return service.artifacts.session_root(session.id) / "exports" / bundle.name, service.artifacts.resolve(session.id, bundle.artifact_id)


def test_control_plane_status_doc_and_script_pin_current_d21_checkpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.delenv("ARCHWAY_LLM_PROVIDER", raising=False)
    get_settings.cache_clear()
    doc = (REPO_ROOT / "docs/rc2/D21_AGENTIC_CONTROL_PLANE_STATUS.md").read_text(encoding="utf-8")
    status = _load_status_script().build_status()
    matrix = {row["component"]: row for row in status["authority_matrix"]}

    assert "d9878ae75f02730688abfc4d121c890e258ff324" in doc
    assert "archway-v2-d21-pricing-dimension-audit" in doc
    assert "Client-facing agent output" in doc
    assert status["baseline_commit"] == "d9878ae75f02730688abfc4d121c890e258ff324"
    assert status["client_pack_agent_output_enabled"] is False
    assert all(value is False for value in status["feature_flags"].values())
    assert status["llm_provider"] == "deterministic"

    assert matrix["deterministic baseline"]["writes_client_pack"] is True
    assert matrix["deterministic baseline"]["can_affect_readiness"] is True
    for component in ("repair planner", "research agent", "use-case analyst agent", "pricing-dimension agent"):
        assert matrix[component]["default_enabled"] is False
        assert matrix[component]["writes_raw"] is True
        assert matrix[component]["writes_audit_pack"] is True
        assert matrix[component]["writes_client_pack"] is False
        assert matrix[component]["can_affect_readiness"] is False
        assert matrix[component]["can_affect_pricing_math"] is False
        assert matrix[component]["can_affect_headline_pricing"] is False
        assert matrix[component]["can_affect_architecture_compiler_truth"] is False
        assert matrix[component]["can_affect_diagram_rendering"] is False

    for component in ("future narrative agent", "future reviewer agent", "future diagram planning agent", "future architecture candidate agent"):
        assert matrix[component]["default_enabled"] is False
        assert matrix[component]["writes_client_pack"] is False


def test_current_agentic_lanes_are_default_off_raw_audit_only_and_manifest_verified(tmp_path, monkeypatch):
    export_dir, zip_path = _generate_package(tmp_path, monkeypatch)

    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        agent_run = json.loads(archive.read("raw/agent_runs.json").decode("utf-8"))[0]
        research_trace = json.loads(archive.read("raw/agent_research_trace.json").decode("utf-8"))
        use_case_trace = json.loads(archive.read("raw/agent_use_case_analyst_trace.json").decode("utf-8"))
        pricing_trace = json.loads(archive.read("raw/agent_pricing_dimension_trace.json").decode("utf-8"))
        evaluation_gate = json.loads(archive.read("raw/agent_evaluation_battery.json").decode("utf-8"))

    assert RAW_AGENT_ARTIFACTS.issubset(names)
    assert AUDIT_AGENT_ARTIFACTS.issubset(names)
    assert not any(name.startswith("client_pack/agentic-") for name in names)
    assert agent_run["enabled_lanes"] == []
    assert agent_run["model_provider"] == "deterministic"
    assert all(task["status"] == "skipped" for task in agent_run["tasks"])
    assert research_trace["enabled"] is False and research_trace["provider"] == "disabled"
    assert use_case_trace["enabled"] is False and use_case_trace["provider"] == "disabled"
    assert pricing_trace["enabled"] is False and pricing_trace["provider"] == "disabled"
    assert research_trace["output_hash"].startswith("sha256:")
    assert use_case_trace["output_hash"].startswith("sha256:")
    assert pricing_trace["output_hash"].startswith("sha256:")
    assert evaluation_gate["client_agent_output_allowed"] is False

    manifest = json.loads((export_dir / "dossier_manifest.json").read_text(encoding="utf-8"))
    inventory_paths = {item["path"] for item in manifest["artifact_inventory"]}
    assert RAW_AGENT_ARTIFACTS.issubset(inventory_paths)
    assert AUDIT_AGENT_ARTIFACTS.issubset(inventory_paths)
    assert manifest["identity"]["feature_flags"]["enable_agentic_research"] is False
    assert manifest["identity"]["feature_flags"]["enable_agentic_use_case_analyst"] is False
    assert manifest["identity"]["feature_flags"]["enable_agentic_pricing"] is False

    ok, errors, _ = _load_verifier().verify(export_dir)
    assert ok, errors

    raw_path = export_dir / "raw/agent_research_trace.json"
    raw_original = raw_path.read_text(encoding="utf-8")
    raw_path.write_text("[]\n", encoding="utf-8")
    ok, errors, _ = _load_verifier().verify(export_dir)
    assert not ok
    assert any("hash mismatch: raw/agent_research_trace.json" in error for error in errors)
    raw_path.write_text(raw_original, encoding="utf-8")

    audit_path = export_dir / "audit_pack/agentic-pricing-dimensions.md"
    audit_path.write_text(audit_path.read_text(encoding="utf-8") + "\nTampered.\n", encoding="utf-8")
    ok, errors, _ = _load_verifier().verify(export_dir)
    assert not ok
    assert any("hash mismatch: audit_pack/agentic-pricing-dimensions.md" in error for error in errors)


def test_client_pack_has_no_current_agentic_lane_leakage(tmp_path, monkeypatch):
    export_dir, _ = _generate_package(tmp_path, monkeypatch)
    client_dir = export_dir / "client_pack"
    assert client_dir.exists()

    client_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in sorted(client_dir.rglob("*"))
        if path.is_file()
    ).lower()
    leaked = sorted(term for term in CLIENT_FORBIDDEN_TERMS if term in client_text)

    assert leaked == []


def test_control_plane_evaluation_and_authority_invariants(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    settings = get_settings()
    flags = agentic_feature_flags(settings)
    result = run_evaluation_battery(thin_evaluation_scenarios())
    lane_scores = {score.lane: score for score in result.lane_scores}
    architecture_metrics = {metric.metric_id: metric for metric in lane_scores["architecture"].metrics}

    assert all(value is False for value in flags.values())
    assert len(result.scenarios) == 10
    assert not result.has_critical_findings
    assert sum(1 for finding in result.findings if finding.severity == "advisory") == 30
    assert lane_scores["research"].confidence_label == "requires_human_review"
    assert lane_scores["use_case_analyst"].confidence_label == "requires_human_review"
    assert lane_scores["pricing_dimension"].confidence_label == "auto_passed"
    assert any(metric.score_type == "human" and not metric.passed for metric in architecture_metrics.values())
    assert is_client_agent_output_allowed(result).client_agent_output_allowed is False
    assert MODEL_PROPOSED == "model_proposed"
    assert not can_unlock_readiness(MODEL_PROPOSED)
    assert REQUIRED_ARTIFACTS == (
        "README.md",
        "manifest.json",
        "01-solution-brief.md",
        "03-pricing.md",
        "raw/pricing.json",
        "raw/session.json",
    )
