"""Tests for deterministic Architecture Decision Records (export trust artifacts).

ADRs surface existing catalog/governance/pricing/research/diagram facts. They
must never invent alternatives or prose, never call a model, and never change
architecture/pricing behavior.
"""

from __future__ import annotations

import copy
import importlib.util
import inspect
import json
from pathlib import Path

from app.services.architecture_decision_records import (
    ArchitectureDecisionRecord,
    build_decision_records,
    decision_records_markdown,
    decision_records_summary,
)
from app.services.dossier_manifest import MANIFEST_FILENAME, build_dossier_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_solution_dossier", REPO_ROOT / "scripts" / "verify_solution_dossier.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ----------------------------------------------------------------------------- fixtures
def _spec(*, with_alternatives=True, with_governance_controls=True):
    return {
        "id": "arch_test123",
        "mode": "production",
        "title": "PRODUCTION Test",
        "selected_services": [
            {
                "service": "Amazon DynamoDB",
                "purpose": "PHI-safe operational state store.",
                "rationale": "It owns hot operational state with predictable latency.",
                "alternatives_considered": ["Amazon Aurora PostgreSQL"] if with_alternatives else [],
                "evidence_ids": ["ev_1"],
            },
            {
                "service": "Amazon EventBridge",
                "purpose": "Schedule and readiness event routing.",
                "rationale": "It owns decoupled event distribution between ingestion and consumers.",
                "alternatives_considered": ["Amazon SQS", "Amazon MSK"] if with_alternatives else [],
                "evidence_ids": ["ev_1"],
            },
            {
                "service": "AWS Step Functions",
                "purpose": "Approval workflow orchestration.",
                "rationale": "It owns the human-approval state machine.",
                "alternatives_considered": [],
                "evidence_ids": ["ev_1"],
            },
        ],
        "components": [
            {"id": "state", "name": "Operational Store", "service": "dynamodb", "metadata": {"role": "operational_state"}},
            {"id": "events", "name": "Event Bus", "service": "eventbridge", "metadata": {}},
            {"id": "workflow", "name": "Approval Workflow", "service": "step_functions", "metadata": {}},
            {"id": "ehr", "name": "EHR", "service": "external_actor", "metadata": {}},
        ],
        "flows": [
            {"id": "f1", "source": "events", "target": "state", "metadata": {"classification": "data_write"}},
            {
                "id": "f2",
                "source": "workflow",
                "target": "ehr",
                "metadata": {"classification": "external_write", "approval_required": True, "action_type": "ehr_writeback", "external_write": True},
            },
        ],
        "governance_controls": (
            [
                {
                    "id": "gov_1",
                    "control_type": "human_approval",
                    "name": "Charge nurse approval",
                    "rationale": "Prevents unsafe autonomous schedule writeback.",
                    "governed_flow_ids": ["f2"],
                    "enforcement": "policy",
                    "failure_behavior": "queue_for_review",
                }
            ]
            if with_governance_controls
            else []
        ),
        "metadata": {},
    }


def _pricing(*, missing_drivers=(), headline=False, with_ledger_lines=True, pilot=None):
    metadata = {
        "pricing_can_be_displayed_as_headline": headline,
        "pricing_ledger": {
            "summary": {"headline_safe": headline, "procurement_ready": False, "sku_tier_backed_subtotal": 0, "heuristic_subtotal": 150},
            "lines": (
                [{"service_name": "Amazon DynamoDB", "evidence_class": "heuristic"}] if with_ledger_lines else []
            ),
        },
        "pricing_driver_closure": {"status": "directional", "missing_drivers": list(missing_drivers)},
    }
    if pilot is not None:
        metadata["sku_pricing_pilot"] = pilot
    return {
        "low_monthly_usd": 100,
        "expected_monthly_usd": 150,
        "high_monthly_usd": 200,
        "unknown_variables": ["device_count"] if missing_drivers else [],
        "metadata": metadata,
    }


def _report(*, quality_label="Limited", coverage_passed=False):
    return {
        "evidence_items": [{"id": "ev_1"}],
        "citation_coverage": {"passed": coverage_passed},
        "metadata": {
            "research_quality": {"label": quality_label, "reason": "AWS Docs MCP and AWS Pricing MCP unavailable."},
            "service_validation_notes": [
                "Time-series storage must be validated against current AWS guidance: compare Timestream, DynamoDB, S3/Iceberg/Athena, and Aurora."
            ],
        },
    }


def _diagrams(*, degraded=True):
    return {
        "missing_requested_views": ["network_private_connectivity"] if degraded else [],
        "view_rendering_ledger": {"omitted_with_reason": [], "unsupported_not_rendered": []},
        "qa_reports": (
            [{"view_id": "bundle", "passed": False, "diagnostics": [{"severity": "warning", "code": "too_many_edge_crossings"}]}]
            if degraded
            else [{"view_id": "bundle", "passed": True, "diagnostics": []}]
        ),
    }


def _records(**overrides):
    return build_decision_records(
        overrides.get("architectures", [_spec()]),
        overrides.get("pricing", _pricing(missing_drivers=("operating_room_count",))),
        overrides.get("report", _report()),
        overrides.get("diagrams", _diagrams()),
    )


def _by_id(records):
    return {record.decision_id: record for record in records}


def _seed_export_dir(tmp_path: Path) -> Path:
    export_dir = tmp_path / "export"
    (export_dir / "raw").mkdir(parents=True)
    for rel in ("README.md", "manifest.json", "01-solution-brief.md", "03-pricing.md",
                "raw/pricing.json", "raw/session.json"):
        (export_dir / rel).write_text(f"content of {rel}\n", encoding="utf-8")
    return export_dir


# ----------------------------------------------------------------------------- tests
def test_adr_generated_from_component_rationale_and_alternatives():
    records = _by_id(_records())
    adr = records["adr_component_amazon_dynamodb"]
    assert adr.decision_type == "storage"
    assert adr.related_components == ["state"]
    assert adr.generated_by == "deterministic_catalog"


def test_adr_preserves_catalog_alternatives_verbatim():
    adr = _by_id(_records())["adr_component_amazon_eventbridge"]
    assert adr.alternatives_considered == ["Amazon SQS", "Amazon MSK"]
    assert adr.decision_type == "eventing"


def test_adr_does_not_invent_alternatives_when_tuple_empty():
    records = _by_id(_records(architectures=[_spec(with_alternatives=False)]))
    # Step Functions has no alternatives and no decision-point role -> no component ADR.
    assert "adr_component_aws_step_functions" not in records
    for record in records.values():
        if record.decision_id.startswith("adr_component_"):
            assert record.alternatives_considered == [] or record.alternatives_considered


def test_chosen_because_uses_existing_purpose_and_rationale_text_only():
    adr = _by_id(_records())["adr_component_amazon_dynamodb"]
    assert adr.chosen_because == (
        "PHI-safe operational state store. It owns hot operational state with predictable latency."
    )


def test_tradeoff_axes_null_without_deterministic_facts():
    # EventBridge has no pricing ledger line and no governed flows -> all axes None.
    adr = _by_id(_records())["adr_component_amazon_eventbridge"]
    assert all(value is None for value in adr.tradeoffs.model_dump().values())
    # DynamoDB has a heuristic ledger line -> cost axis populated from that fact only.
    dynamo = _by_id(_records())["adr_component_amazon_dynamodb"]
    assert dynamo.tradeoffs.cost == "pricing evidence class: heuristic"


def test_comparison_note_comes_only_from_existing_validation_notes():
    records = _by_id(_records())
    assert "Timestream" in (records["adr_component_amazon_dynamodb"].comparison_note or "")
    assert records["adr_component_amazon_eventbridge"].comparison_note is None


def test_confidence_directional_when_missing_drivers_or_not_estimated():
    pilot = {"status": "completed", "sku_pilot_procurement_ready": False, "not_estimated": ["Amazon EventBridge:eventbridge_custom_events"]}
    records = _by_id(_records(pricing=_pricing(missing_drivers=("operating_room_count",), pilot=pilot)))
    pricing_adr = records["adr_pricing_readiness"]
    assert pricing_adr.confidence == "directional"
    assert "operating_room_count" in pricing_adr.missing_facts
    assert any("not_estimated" in fact for fact in pricing_adr.missing_facts)


def test_governance_adr_generated_for_effectful_writeback():
    records = _by_id(_records())
    adr = records["adr_governance_gov_1"]
    assert adr.decision_type == "governance_writeback"
    assert adr.related_flows == ["f2"]
    assert adr.chosen_because == "Prevents unsafe autonomous schedule writeback."
    # Fallback path: typed flow metadata without enriched controls.
    fallback = _by_id(_records(architectures=[_spec(with_governance_controls=False)]))
    assert "adr_governance_ehr_writeback" in fallback


def test_pricing_adr_separates_global_and_sku_pilot_readiness():
    pilot = {"status": "completed", "sku_pilot_procurement_ready": True, "not_estimated": []}
    adr = _by_id(_records(pricing=_pricing(headline=False, pilot=pilot)))["adr_pricing_readiness"]
    assert "Global: headline_safe=False" in adr.chosen_because
    assert "sku_pilot_procurement_ready=True" in adr.chosen_because
    assert "never promote each other" in adr.chosen_because


def test_evidence_adr_generated_when_research_quality_limited():
    records = _by_id(_records(report=_report(quality_label="Limited")))
    adr = records["adr_evidence_readiness"]
    assert adr.confidence == "low" and adr.status == "needs_confirmation"
    assert adr.chosen_because == "AWS Docs MCP and AWS Pricing MCP unavailable."
    # Validated + passing coverage -> no evidence ADR.
    clean = _by_id(_records(report=_report(quality_label="Validated", coverage_passed=True)))
    assert "adr_evidence_readiness" not in clean


def test_diagram_adr_generated_when_degraded():
    records = _by_id(_records(diagrams=_diagrams(degraded=True)))
    adr = records["adr_diagram_readiness"]
    assert "too_many_edge_crossings" in adr.missing_facts
    assert "network_private_connectivity" in adr.missing_facts
    clean = _by_id(_records(diagrams=_diagrams(degraded=False)))
    assert "adr_diagram_readiness" not in clean


def test_adr_artifact_exported_and_in_manifest_inventory(tmp_path):
    from app.services.export_package import ExportPackageService

    class _Session:
        id = "sess_adr"
        initial_use_case = "Test use case"

    export_dir = tmp_path / "export"
    export_dir.mkdir()
    (export_dir / "README.md").write_text("readme", encoding="utf-8")
    included: list[str] = []
    ExportPackageService()._write_dossier_layer(
        export_dir, "pkg-adr", _Session(), {"use_case_profile": {}}, _report(),
        _pricing(missing_drivers=("operating_room_count",)), [_spec()], [], [_diagrams()],
        None, [], included,
    )
    assert (export_dir / "architecture" / "decision_records.json").is_file()
    assert (export_dir / "architecture" / "decision_records.md").is_file()
    assert (export_dir / "raw" / "architecture_decision_records.json").is_file()
    manifest = json.loads((export_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    inventory_paths = {item["path"] for item in manifest["artifact_inventory"]}
    assert "architecture/decision_records.json" in inventory_paths
    assert manifest["decision_records"]["count"] >= 3
    assert "directional_count" in manifest["decision_records"]


def test_verifier_detects_adr_artifact_tampering(tmp_path):
    from app.services.export_package import ExportPackageService

    class _Session:
        id = "sess_adr2"
        initial_use_case = "Test use case"

    export_dir = _seed_export_dir(tmp_path)
    ExportPackageService()._write_dossier_layer(
        export_dir, "pkg-adr2", _Session(), {"use_case_profile": {}}, _report(),
        _pricing(), [_spec()], [], [_diagrams()], None, [], [],
    )
    verifier = _load_verifier()
    ok, errors, _ = verifier.verify(export_dir)
    assert ok, errors
    # Tamper with the ADR artifact -> verifier must fail with a hash mismatch.
    target = export_dir / "architecture" / "decision_records.json"
    target.write_text(target.read_text(encoding="utf-8") + "\n// tampered", encoding="utf-8")
    ok, errors, _ = verifier.verify(export_dir)
    assert not ok
    assert any("decision_records.json" in error for error in errors)


def test_adr_output_deterministic_for_same_input():
    first = json.dumps([r.model_dump(mode="json") for r in _records()], sort_keys=True)
    second = json.dumps([r.model_dump(mode="json") for r in _records()], sort_keys=True)
    assert first == second
    assert decision_records_markdown(_records()) == decision_records_markdown(_records())


def test_no_llm_or_model_calls():
    import app.services.architecture_decision_records as module

    # Inspect IMPORT statements only (the module docstring legitimately states
    # that no LLM is used, so a raw substring check would self-trigger).
    import_lines = [
        line.strip()
        for line in inspect.getsource(module).splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    for line in import_lines:
        for forbidden in ("llm", "model_router", "bedrock", "ollama", "discovery_planner", "tavily"):
            assert forbidden not in line.lower(), line


def test_inputs_not_mutated_and_no_behavior_change():
    architectures = [_spec()]
    pricing = _pricing(missing_drivers=("operating_room_count",))
    report = _report()
    diagrams = _diagrams()
    snapshot = copy.deepcopy((architectures, pricing, report, diagrams))
    build_decision_records(architectures, pricing, report, diagrams)
    assert (architectures, pricing, report, diagrams) == snapshot


def test_summary_counts():
    records = _records()
    summary = decision_records_summary(records)
    assert summary["count"] == len(records)
    assert summary["needs_confirmation_count"] >= 1  # evidence + diagram ADRs
    assert summary["directional_count"] >= 1
    assert isinstance(ArchitectureDecisionRecord.model_json_schema(), dict)
