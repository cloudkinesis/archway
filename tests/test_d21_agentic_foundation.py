from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.core.config import get_settings
from app.db.session_store import SessionStore
from app.services.agentic.contracts import AgentDecision, AgentEvidenceRef, AgentProposal, AgentRun, AgentTask
from app.services.agentic.provenance import MODEL_PROPOSED, can_unlock_readiness, can_write_surface
from app.services.agentic.repair_planner import (
    DeterministicRepairPlanner,
    agentic_feature_flags,
    authority_matrix,
)
from app.services.export_package import ExportPackageService
from app.services.synthesis import SynthesisEngine

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_solution_dossier_d21", REPO_ROOT / "scripts/verify_solution_dossier.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_solution_dossier_d21"] = module
    spec.loader.exec_module(module)
    return module


def test_d21_decision_doc_is_frozen_for_phase0_only():
    doc = (REPO_ROOT / "docs/rc2/D21_AGENTIC_PROPOSAL_LANES.md").read_text(encoding="utf-8")

    assert "APPROVED DESIGN CANDIDATE / IMPLEMENTATION PHASE 0 AUTHORIZED" in doc
    assert "The full D21 agentic system is not implemented by this status." in doc
    assert "app/services/source_truth_pricing_compiler.py:95" in doc
    assert "app/services/source_truth_pricing_compiler.py:117" in doc
    assert "app/services/export_package.py:187" in doc


def test_agentic_flags_default_false_and_llm_stays_deterministic(monkeypatch, tmp_path):
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

    settings = get_settings()

    assert settings.llm_provider == "deterministic"
    assert agentic_feature_flags(settings) == {
        "enable_agentic_repair_planner": False,
        "enable_agentic_research": False,
        "enable_agentic_use_case_analyst": False,
        "enable_agentic_pricing": False,
        "enable_agentic_narrative": False,
        "enable_agentic_reviewer": False,
        "enable_agentic_diagram_planner": False,
        "enable_agentic_architecture": False,
    }
    repair_row = next(row for row in authority_matrix(settings) if row["component"] == "repair_planner")
    assert repair_row["default_enabled"] is False
    assert repair_row["can_affect_readiness"] is False
    assert repair_row["can_affect_pricing_math"] is False
    assert repair_row["can_affect_diagram_compiler_output"] is False


def test_model_proposed_is_raw_audit_only_and_cannot_unlock_readiness():
    assert MODEL_PROPOSED == "model_proposed"
    assert can_write_surface(MODEL_PROPOSED, "raw")
    assert can_write_surface(MODEL_PROPOSED, "audit_pack")
    assert not can_write_surface(MODEL_PROPOSED, "client_pack")
    assert can_write_surface(MODEL_PROPOSED, "client_pack", upgraded=True)
    assert not can_unlock_readiness(MODEL_PROPOSED)

    with pytest.raises(ValueError):
        AgentProposal(
            proposal_id="p1",
            lane="pricing",
            claim_kind="pricing",
            content={"claim": "Use Lex text request scenarios."},
            target_surface="client_pack",
        )


def test_agentic_contract_hashes_are_stable():
    evidence = AgentEvidenceRef(source_type="deterministic_ledger", source_id="pricing_driver_closure", claim_kind="repair")
    proposal = AgentProposal(
        proposal_id="p1",
        lane="repair_planner",
        claim_kind="repair",
        content={"action": "Confirm monthly Lex text request volume."},
        evidence_refs=[evidence],
    )
    proposal_again = AgentProposal.model_validate(proposal.model_dump(mode="json"))
    run = AgentRun(
        run_id="agent_run_test",
        input_hash="sha256:test",
        tasks=[AgentTask(task_id="t1", lane="repair_planner", purpose="Plan repairs.", status="accepted")],
        decisions=[AgentDecision(proposal_id="p1", decision="accepted", reason="deterministic", deterministic_gate="repair_planner")],
    )

    assert proposal.content_hash == proposal_again.content_hash
    assert run.trace_hash == AgentRun.model_validate(run.model_dump(mode="json")).trace_hash


def test_deterministic_repair_planner_uses_existing_signals_only():
    report = {
        "metadata": {
            "evidence_quality": {"aws_docs_available": False, "aws_pricing_available": False},
            "citation_coverage": {"passed": False},
        }
    }
    pricing = {
        "metadata": {
            "pricing_driver_closure": {
                "missing_drivers": [{"name": "monthly_text_requests"}],
                "assumed_drivers": ["average_session_duration"],
            }
        }
    }
    diagrams = [{"mode": "poc", "diagrams": [{"view_id": "semantic_context", "fallback_reason": "unsupported semantic view"}]}]

    state = DeterministicRepairPlanner().plan(
        report=report,
        pricing=pricing,
        architectures=[],
        diagrams=diagrams,
        diagram_fidelity={"missing_requested_views": [{"mode": "poc", "view_id": "trust_boundary", "reason": "not rendered"}]},
    )
    actions = [item.action for item in state.repair_plan.actions]

    assert any("Confirm missing pricing driver: monthly_text_requests" in item for item in actions)
    assert any("Validate assumed pricing driver: average_session_duration" in item for item in actions)
    assert any("Refresh authoritative AWS Docs/Pricing evidence" in item for item in actions)
    assert any("Resolve uncited or weakly cited dossier claims" in item for item in actions)
    assert any("Review diagram fallback" in item for item in actions)


def test_export_emits_agentic_raw_and_audit_traces_and_verifier_hashes_them(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
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
        agent_run = json.loads(archive.read("raw/agent_runs.json").decode("utf-8"))[0]

    assert "raw/agent_runs.json" in names
    assert "raw/agent_proposals.json" in names
    assert "raw/agent_repair_plan.json" in names
    assert "audit_pack/agentic-repair-plan.md" in names
    assert "client_pack/agentic-repair-plan.md" not in names
    assert agent_run["model_provider"] == "deterministic"
    assert all(task["status"] == "skipped" for task in agent_run["tasks"])

    manifest = json.loads((export_dir / "dossier_manifest.json").read_text(encoding="utf-8"))
    inventory_paths = {item["path"] for item in manifest["artifact_inventory"]}
    assert "raw/agent_runs.json" in inventory_paths
    assert manifest["identity"]["feature_flags"]["enable_agentic_repair_planner"] is False

    verifier = _load_verifier()
    ok, errors, _ = verifier.verify(export_dir)
    assert ok, errors

    (export_dir / "raw/agent_runs.json").write_text("[]\n", encoding="utf-8")
    ok, errors, _ = verifier.verify(export_dir)
    assert not ok
    assert any("hash mismatch: raw/agent_runs.json" in error for error in errors)
