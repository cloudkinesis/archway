from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from zipfile import ZipFile

from app.core.config import get_settings
from app.db.session_store import SessionStore
from app.services.agentic.evaluation import (
    EvaluationScenario,
    ScenarioObservation,
    evaluation_gate_payload,
    is_client_agent_output_allowed,
    run_evaluation_battery,
    score_scenario,
)
from app.services.agentic.evaluation_scenarios import thin_evaluation_scenarios
from app.services.export_package import ExportPackageService
from app.services.synthesis import SynthesisEngine

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_runner():
    spec = importlib.util.spec_from_file_location("d21_eval_battery_test", REPO_ROOT / "scripts/d21_eval_battery.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["d21_eval_battery_test"] = module
    spec.loader.exec_module(module)
    return module


def test_thin_evaluation_scenarios_are_complete_and_unique():
    scenarios = thin_evaluation_scenarios()
    ids = [scenario.scenario_id for scenario in scenarios]

    assert len(scenarios) == 10
    assert len(set(ids)) == 10
    assert ids == [
        "lex_contact_center",
        "connect_analytics",
        "sap_migration_modernization",
        "eks_saas_multitenant",
        "iot_cold_chain",
        "insurance_claims_docs",
        "public_permitting",
        "pharma_trial_matching",
        "bank_aml_triage",
        "media_streaming_qoe",
    ]
    for scenario in scenarios:
        assert scenario.use_case
        assert scenario.required_lanes
        assert scenario.expected_claim_kinds
        assert scenario.expected_pricing_labels
        assert scenario.expected_diagram_behavior in {"rendered", "fallback_disclosed", "omitted_disclosed", "human_review"}
        assert scenario.architecture_soundness_score_type == "human"


def test_evaluation_models_serialize_deterministically():
    scenario = thin_evaluation_scenarios()[0]
    clone = EvaluationScenario.model_validate(scenario.model_dump(mode="json"))

    assert scenario.scenario_hash == clone.scenario_hash
    result = run_evaluation_battery([scenario])
    result_again = run_evaluation_battery([clone])
    assert result.reproducibility_hash == result_again.reproducibility_hash
    assert any(score.score_type == "mixed" for score in result.lane_scores if score.lane == "architecture")


def test_scorers_pass_labeled_diagnostics_and_human_architecture_placeholder():
    scenario = thin_evaluation_scenarios()[0]
    observation = ScenarioObservation(
        scenario_id=scenario.scenario_id,
        aws_claims_have_evidence=False,
        missing_evidence_labeled=True,
        pricing_labels=["scenario_assumed"],
        diagram_fallback_recorded=True,
        repair_actions=["Ask for monthly text and voice request volume."],
    )

    metrics, findings = score_scenario(scenario, observation)

    assert next(metric for metric in metrics if metric.metric_id.endswith("citation_coverage")).passed
    assert next(metric for metric in metrics if metric.metric_id.endswith("pricing_label")).passed
    assert next(metric for metric in metrics if metric.metric_id.endswith("diagram_render_or_disclose")).passed
    architecture_metric = next(metric for metric in metrics if metric.metric_id.endswith("architecture_soundness"))
    assert architecture_metric.score_type == "human"
    assert not architecture_metric.passed
    assert all(finding.severity != "critical" for finding in findings)


def test_scorers_fail_unlabeled_evidence_silent_pricing_and_silent_diagram_gap():
    scenario = thin_evaluation_scenarios()[0]
    observation = ScenarioObservation(
        scenario_id=scenario.scenario_id,
        aws_claims_have_evidence=False,
        missing_evidence_labeled=False,
        pricing_labels=["heuristic"],
        procurement_pricing_presented=True,
        silent_generic_nonzero_pricing=True,
        diagram_rendered=False,
        diagram_fallback_recorded=False,
        diagram_omission_recorded=False,
        repair_actions=[],
        model_proposed_unlocks_readiness=True,
    )

    metrics, findings = score_scenario(scenario, observation)
    failed = {metric.metric_id.rsplit(".", 1)[1] for metric in metrics if not metric.passed and metric.score_type == "auto"}

    assert "citation_coverage" in failed
    assert "pricing_label" in failed
    assert "diagram_render_or_disclose" in failed
    assert "repair_plan" in failed
    assert "model_proposed_readiness" in failed
    assert any(finding.severity == "critical" for finding in findings)


def test_client_agent_output_gate_stays_closed_without_passing_battery_and_human_review():
    assert not is_client_agent_output_allowed(None).client_agent_output_allowed

    result = run_evaluation_battery(thin_evaluation_scenarios())
    gate = is_client_agent_output_allowed(result)

    assert not gate.client_agent_output_allowed
    assert "architecture" in gate.required_human_lanes
    assert "Human-scored lanes" in gate.reason
    assert not evaluation_gate_payload()["client_agent_output_allowed"]


def test_battery_runner_all_and_single_scenario_outputs(tmp_path, capsys):
    runner = _load_runner()
    out = tmp_path / "battery"

    assert runner.main(["--output-dir", str(out)]) == 0
    payload = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert payload["battery_id"] == "d21-thin-open-world-v1"
    assert len(payload["scenarios"]) == 10
    assert (out / "report.md").is_file()
    capsys.readouterr()

    assert runner.main(["--output-dir", str(tmp_path / "single"), "--scenario", "lex_contact_center", "--json"]) == 0
    printed = capsys.readouterr().out
    single = json.loads(printed)
    assert [scenario["scenario_id"] for scenario in single["scenarios"]] == ["lex_contact_center"]
    assert runner.main(["--scenario", "does_not_exist"]) == 2


def test_export_records_evaluation_gate_in_raw_and_audit_only(tmp_path, monkeypatch):
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
        gate = json.loads(archive.read("raw/agent_evaluation_battery.json").decode("utf-8"))

    assert "raw/agent_evaluation_battery.json" in names
    assert "audit_pack/agentic-evaluation-summary.md" in names
    assert "client_pack/agentic-evaluation-summary.md" not in names
    assert gate["status"] == "not_run_for_package"
    assert gate["client_agent_output_allowed"] is False

    manifest = json.loads((export_dir / "dossier_manifest.json").read_text(encoding="utf-8"))
    inventory_paths = {item["path"] for item in manifest["artifact_inventory"]}
    assert "raw/agent_evaluation_battery.json" in inventory_paths
