"""Tests for Reviewer Mode, the Unified Uncertainty Map, and Scenario Simulation.

All three must be deterministic, model-free, and must never mutate pricing,
architecture, or readiness. Reuses the ADR test fixtures for export payload
shapes; uses the REAL pricing engine (offline, deterministic) for recompute.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
from pathlib import Path

import pytest

from app.services.reviewer_mode import (
    build_reviewer_report,
    build_uncertainty_map,
    reviewer_summary_markdown,
)
from app.services.scenario_simulation import (
    ScenarioOverride,
    known_driver_values,
    scenario_summary,
    simulate_scenarios,
)
from tests.test_architecture_decision_records import (
    _diagrams,
    _load_verifier,
    _pricing,
    _report,
    _seed_export_dir,
    _spec,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _brief(*, capability_status="directional", assumptions=2):
    return {
        "use_case_profile": {
            "capability_decision": {
                "status": capability_status,
                "reason": "Recognized workload shape without high-confidence deep support.",
                "generic_fallback_family": "document_rag_assistant",
                "fallback_family_source": "deterministic",
                "next_best_questions": ["How many documents should be modeled?"],
            }
        },
        "assumptions": [{"text": f"assumption {i}"} for i in range(assumptions)],
    }


def _adrs(*, missing_facts=True):
    return [
        {
            "decision_id": "adr_component_amazon_dynamodb",
            "title": "Service selection: Amazon DynamoDB",
            "confidence": "medium",
            "evidence_class": "catalog_backed",
            "missing_facts": [],
            "reviewer_questions": ["Confirm DynamoDB over Aurora."],
            "related_components": ["state"],
        },
        {
            "decision_id": "adr_pricing_readiness",
            "title": "Pricing readiness (global vs SKU pilot)",
            "confidence": "directional",
            "evidence_class": "missing_evidence" if missing_facts else "pricing_backed",
            "missing_facts": ["operating_room_count"] if missing_facts else [],
            "reviewer_questions": [],
        },
    ]


def _clean_inputs():
    """Inputs with NO deterministic finding signals -> reviewer must emit nothing."""
    pricing = {
        "low_monthly_usd": 100, "expected_monthly_usd": 150, "high_monthly_usd": 200,
        "unknown_variables": [],
        "metadata": {
            "pricing_can_be_displayed_as_headline": True,
            "pricing_ledger": {"summary": {"headline_safe": True, "procurement_ready": True}, "lines": []},
            "pricing_driver_closure": {"status": "closed", "missing_drivers": []},
        },
    }
    report = {
        "evidence_items": [{"id": f"ev_{i}"} for i in range(4)],
        "citation_coverage": {"passed": True},
        "metadata": {"research_quality": {"label": "Validated", "reason": "ok"}},
    }
    spec = {
        "mode": "production",
        "selected_services": [],
        "components": [],
        "flows": [{"id": "f1", "source": "a", "target": "b", "metadata": {"classification": "data_read"}}],
        "governance_controls": [],
    }
    brief = {"use_case_profile": {"capability_decision": {"status": "supported"}}, "assumptions": []}
    return brief, report, pricing, [spec], _diagrams(degraded=False), []


def _default_report():
    return build_reviewer_report(
        _brief(), _report(), _pricing(missing_drivers=("operating_room_count",),
                                       pilot={"rate_authoritative": True, "quantities_confirmed": False,
                                              "sku_pilot_estimate_ready": True, "sku_pilot_procurement_ready": False,
                                              "status": "completed", "not_estimated": ["Amazon EventBridge:eventbridge_custom_events"]}),
        [_spec()], [_diagrams()], _adrs(),
    )


def _ids(report):
    return {finding.finding_id for finding in report.findings}


# ---------------------------------------------------------------- reviewer mode
def test_reviewer_report_deterministic():
    first = json.dumps(_default_report().model_dump(mode="json"), sort_keys=True)
    second = json.dumps(_default_report().model_dump(mode="json"), sort_keys=True)
    assert first == second


def test_pricing_directional_creates_pricing_warning():
    report = _default_report()
    ids = _ids(report)
    assert "rev_pricing_headline_not_safe" in ids
    assert "rev_pricing_missing_drivers" in ids
    headline = next(f for f in report.findings if f.finding_id == "rev_pricing_headline_not_safe")
    assert headline.severity == "warning" and headline.blocks_customer_ready


def test_sku_rates_real_quantities_assumed_creates_warning():
    finding = next(f for f in _default_report().findings if f.finding_id == "rev_sku_rates_real_quantities_assumed")
    assert finding.severity == "warning" and finding.blocks_procurement_ready
    assert "rate_authoritative=True" in finding.explanation


def test_research_limited_and_citation_failure_create_findings():
    ids = _ids(_default_report())
    assert "rev_research_quality_limited" in ids
    assert "rev_citation_coverage_failed" in ids


def test_adr_missing_facts_creates_architecture_decision_warning():
    finding = next(f for f in _default_report().findings if f.finding_id == "rev_adr_adr_pricing_readiness")
    assert finding.category == "architecture_decision" and finding.severity == "warning"
    assert "operating_room_count" in finding.explanation


def test_governance_effectful_writeback_creates_governance_finding():
    finding = next(f for f in _default_report().findings if f.finding_id == "rev_governance_effectful_flows")
    assert finding.related_flows == ["f2"]
    assert finding.category == "governance"


def test_diagram_qa_warning_creates_diagram_finding():
    finding = next(f for f in _default_report().findings if f.finding_id == "rev_diagram_degraded")
    assert "too_many_edge_crossings" in finding.explanation


def test_directional_capability_creates_capability_finding_and_over_patterning():
    report = _default_report()
    assert "rev_capability_directional" in _ids(report)
    assert report.over_patterning_score is not None
    if report.over_patterning_score >= 0.5:
        assert "rev_over_patterning" in _ids(report)


def test_blocker_makes_status_blocked():
    report = build_reviewer_report(
        _brief(capability_status="unsupported_or_blocked"), _report(), _pricing(), [_spec()], [_diagrams()], [],
    )
    assert "rev_capability_blocked" in _ids(report)
    assert report.overall_review_status == "blocked"


def test_no_findings_without_deterministic_signal_and_status_ready():
    brief, report, pricing, specs, diagrams, adrs = _clean_inputs()
    result = build_reviewer_report(brief, report, pricing, specs, diagrams, adrs)
    assert result.findings == []
    assert result.overall_review_status == "ready"


def test_uncertainty_map_separates_sections():
    report = _default_report()
    sections = report.uncertainty_map["by_section"]
    assert sections["pricing"] == "directional"
    assert sections["research_evidence"] == "limited"
    assert sections["governance"] == "warning"
    assert sections["diagrams"] == "warning"
    assert sections["export_integrity"] == "high"
    # Clean inputs flip independently.
    brief, clean_report, clean_pricing, specs, diagrams, adrs = _clean_inputs()
    clean = build_uncertainty_map(brief, clean_report, clean_pricing, specs, diagrams, adrs)
    assert clean["by_section"]["pricing"] == "high"
    assert clean["by_section"]["research_evidence"] == "high"


def test_reviewer_mode_does_not_mutate_inputs():
    brief = _brief()
    report = _report()
    pricing = _pricing(missing_drivers=("operating_room_count",))
    specs = [_spec()]
    diagrams = [_diagrams()]
    adrs = _adrs()
    snapshot = copy.deepcopy((brief, report, pricing, specs, diagrams, adrs))
    build_reviewer_report(brief, report, pricing, specs, diagrams, adrs)
    assert (brief, report, pricing, specs, diagrams, adrs) == snapshot


def test_no_llm_imports_in_reviewer_module():
    import app.services.reviewer_mode as module

    import_lines = [l.strip() for l in inspect.getsource(module).splitlines() if l.strip().startswith(("import ", "from "))]
    for line in import_lines:
        for forbidden in ("llm", "model_router", "bedrock", "ollama", "tavily", "discovery_planner"):
            assert forbidden not in line.lower(), line


# ---------------------------------------------------------------- scenario simulation
LEGAL_TEXT = (
    "Law firm needs retrieval augmented generation over legal documents with citations, "
    "private data, and audit trail. 50,000 historical contracts."
)


@pytest.fixture(scope="module")
def legal_baseline():
    from app.services.pattern_catalog import service_recommendations
    from app.services.pricing import PricingEngine
    from app.services.synthesis import SynthesisEngine
    from app.services.use_case_profile import profile_use_case

    brief_obj = SynthesisEngine().create_initial_brief(LEGAL_TEXT)
    plan = service_recommendations(profile_use_case(LEGAL_TEXT), evidence_ids=["ev"])
    baseline = asyncio.run(PricingEngine().estimate(brief_obj, plan))
    spec = {"mode": "production", "selected_services": [s.model_dump(mode="json") for s in plan]}
    return brief_obj.model_dump(mode="json"), baseline.model_dump(mode="json"), [spec]


def test_pricing_driver_multiplier_recomputes_delta(legal_baseline):
    brief, pricing, specs = legal_baseline
    results = simulate_scenarios(
        [ScenarioOverride(override_id="s1", override_type="pricing_driver_multiplier",
                          payload={"driver": "rag_queries_per_day", "multiplier": 10})],
        brief=brief, baseline_pricing=pricing, report=_report(), architectures=specs,
    )
    result = results[0]
    assert result.status == "completed"
    assert result.pricing_delta["delta"]["expected_monthly_usd"] > 0
    affected = result.pricing_delta["affected_drivers"][0]
    assert affected["driver"] == "rag_queries_per_day"
    assert affected["new"] == pytest.approx(affected["old"] * 10)
    # Determinism: same input, same output bytes.
    again = simulate_scenarios(
        [ScenarioOverride(override_id="s1", override_type="pricing_driver_multiplier",
                          payload={"driver": "rag_queries_per_day", "multiplier": 10})],
        brief=brief, baseline_pricing=pricing, report=_report(), architectures=specs,
    )
    assert json.dumps(result.model_dump(mode="json"), sort_keys=True) == json.dumps(again[0].model_dump(mode="json"), sort_keys=True)
    # Deltas include reviewer/uncertainty changes.
    assert result.reviewer_findings_delta["baseline_counts"]
    assert "simulated_pricing_confidence" in result.uncertainty_delta


def test_missing_driver_override_is_not_applied(legal_baseline):
    brief, pricing, specs = legal_baseline
    results = simulate_scenarios(
        [{"override_id": "s2", "override_type": "pricing_driver_override",
          "payload": {"driver": "nonexistent_driver", "value": 999}}],
        brief=brief, baseline_pricing=pricing, architectures=specs,
    )
    assert results[0].status == "not_applied"
    assert "not a recognized pricing driver" in results[0].not_applied_overrides[0]["reason"]
    assert results[0].pricing_delta == {}


def test_retention_override_not_applied_without_retention_driver(legal_baseline):
    brief, pricing, specs = legal_baseline
    assert not any(d in known_driver_values(pricing) for d in ("audit_retention_years", "retention_years"))
    results = simulate_scenarios(
        [{"override_id": "s3", "override_type": "retention_constraint", "payload": {"retention_days": 2555}}],
        brief=brief, baseline_pricing=pricing, architectures=specs,
    )
    assert results[0].status == "not_applied"
    assert "retention" in results[0].not_applied_overrides[0]["reason"]


def test_region_and_rto_constraints_are_honest_not_applied():
    results = simulate_scenarios(
        [
            {"override_id": "s4", "override_type": "region_constraint", "payload": {"region": "eu-west-1", "data_residency": "EU-only"}},
            {"override_id": "s5", "override_type": "resilience_constraint", "payload": {"rto_minutes": 15, "rpo_minutes": 5}},
        ],
        brief={}, baseline_pricing={},
    )
    by_id = {r.scenario_id: r for r in results}
    assert by_id["s4"].status == "not_applied"
    assert "region-aware recomputation not supported" in by_id["s4"].not_applied_overrides[0]["reason"]
    assert by_id["s5"].status == "not_applied"
    assert "DR architecture review" in by_id["s5"].not_applied_overrides[0]["reason"]
    assert by_id["s5"].architecture_delta["status"] == "unchanged"


def test_quantity_confirmation_affects_sku_pilot_only():
    pilot = {"rate_authoritative": True, "quantities_confirmed": False, "sku_pilot_estimate_ready": True,
             "sku_pilot_procurement_ready": False, "status": "completed"}
    pricing = _pricing(pilot=pilot)
    results = simulate_scenarios(
        [{"override_id": "s6", "override_type": "quantity_confirmation", "payload": {"confirmed": True}}],
        brief={}, baseline_pricing=pricing,
    )
    result = results[0]
    assert result.status == "completed"
    assert result.readiness_delta["scope"] == "sku_pilot_only"
    assert result.readiness_delta["simulated"]["sku_pilot_procurement_ready"] is True
    assert "unchanged" in result.readiness_delta["global_readiness"]
    assert any("simulation-only" in w for w in result.warnings)
    # Original pricing payload untouched.
    assert pricing["metadata"]["sku_pricing_pilot"]["quantities_confirmed"] is False


def test_simulation_does_not_mutate_inputs(legal_baseline):
    brief, pricing, specs = legal_baseline
    brief_copy, pricing_copy = copy.deepcopy(brief), copy.deepcopy(pricing)
    simulate_scenarios(
        [{"override_id": "s7", "override_type": "pricing_driver_multiplier",
          "payload": {"driver": "rag_queries_per_day", "multiplier": 2}}],
        brief=brief, baseline_pricing=pricing, architectures=specs,
    )
    assert brief == brief_copy
    assert pricing == pricing_copy


def test_no_llm_imports_in_simulation_module():
    import app.services.scenario_simulation as module

    import_lines = [l.strip() for l in inspect.getsource(module).splitlines() if l.strip().startswith(("import ", "from "))]
    for line in import_lines:
        for forbidden in ("llm", "model_router", "bedrock", "ollama", "tavily", "discovery_planner"):
            assert forbidden not in line.lower(), line


# ---------------------------------------------------------------- export integration
class _Session:
    id = "sess_review"
    initial_use_case = "Test use case"


def _export(tmp_path, *, scenario_overrides=None):
    from app.services.export_package import ExportPackageService

    export_dir = _seed_export_dir(tmp_path)
    ExportPackageService()._write_dossier_layer(
        export_dir, "pkg-review", _Session(), _brief(), _report(),
        _pricing(missing_drivers=("operating_room_count",),
                 pilot={"rate_authoritative": True, "quantities_confirmed": False,
                        "sku_pilot_estimate_ready": True, "sku_pilot_procurement_ready": False,
                        "status": "completed", "snapshot_id": "aws-price-list-us-east-1-test",
                        "source_hash": "sha256:testhash", "snapshot_source": "local_cache"}),
        [_spec()], [], [_diagrams()], None, [], [],
        scenario_overrides=scenario_overrides,
    )
    return export_dir


def test_reviewer_and_uncertainty_artifacts_exported_and_in_manifest(tmp_path):
    export_dir = _export(tmp_path)
    for rel in ("reviewer/reviewer_findings.json", "reviewer/reviewer_summary.md",
                "reviewer/uncertainty_map.json", "reviewer/uncertainty_map.md",
                "raw/reviewer_findings.json", "raw/uncertainty_map.json"):
        assert (export_dir / rel).is_file(), rel
    manifest = json.loads((export_dir / "dossier_manifest.json").read_text(encoding="utf-8"))
    inventory = {item["path"] for item in manifest["artifact_inventory"]}
    assert "reviewer/reviewer_findings.json" in inventory
    assert manifest["reviewer_mode"]["finding_count"] >= 4
    assert manifest["uncertainty_map"]["overall_confidence"]
    assert "pricing" in manifest["uncertainty_map"]["low_confidence_sections"]
    # Scenario artifacts absent without explicit overrides (flag is default-off).
    assert not (export_dir / "scenarios").exists()
    assert "scenario_simulation" not in manifest
    # Existing dossier/ADR artifacts still present; fail-closed pricing preserved.
    assert (export_dir / "architecture" / "decision_records.json").is_file()
    assert manifest["pricing"]["global"]["headline_safe"] is False
    assert manifest["pricing"]["global"]["procurement_ready"] is False


def test_scenario_artifacts_exported_with_explicit_overrides(tmp_path):
    export_dir = _export(tmp_path, scenario_overrides=[
        {"override_id": "q1", "override_type": "quantity_confirmation", "payload": {"confirmed": True}},
        {"override_id": "r1", "override_type": "region_constraint", "payload": {"region": "eu-west-1"}},
    ])
    for rel in ("scenarios/scenario_simulations.json", "scenarios/scenario_simulations.md", "raw/scenario_simulations.json"):
        assert (export_dir / rel).is_file(), rel
    manifest = json.loads((export_dir / "dossier_manifest.json").read_text(encoding="utf-8"))
    assert manifest["scenario_simulation"]["scenario_count"] == 2
    assert manifest["scenario_simulation"]["completed_count"] == 1
    assert manifest["scenario_simulation"]["not_applied_count"] == 1
    inventory = {item["path"] for item in manifest["artifact_inventory"]}
    assert "scenarios/scenario_simulations.json" in inventory


def test_verifier_detects_reviewer_and_scenario_tampering(tmp_path):
    export_dir = _export(tmp_path, scenario_overrides=[
        {"override_id": "q1", "override_type": "quantity_confirmation", "payload": {"confirmed": True}},
    ])
    verifier = _load_verifier()
    ok, errors, _ = verifier.verify(export_dir)
    assert ok, errors
    target = export_dir / "reviewer" / "reviewer_findings.json"
    target.write_text(target.read_text(encoding="utf-8") + "\n// tampered", encoding="utf-8")
    ok, errors, _ = verifier.verify(export_dir)
    assert not ok and any("reviewer_findings.json" in e for e in errors)
    # Restore and tamper the scenario artifact instead.
    export_dir2 = _export(tmp_path / "second", scenario_overrides=[
        {"override_id": "q1", "override_type": "quantity_confirmation", "payload": {"confirmed": True}},
    ])
    target2 = export_dir2 / "scenarios" / "scenario_simulations.json"
    target2.write_text(target2.read_text(encoding="utf-8") + "\n// tampered", encoding="utf-8")
    ok2, errors2, _ = verifier.verify(export_dir2)
    assert not ok2 and any("scenario_simulations.json" in e for e in errors2)


def test_reviewer_summary_markdown_renders():
    text = reviewer_summary_markdown(_default_report())
    assert "# Reviewer Summary" in text and "Overall review status" in text
    summary = scenario_summary([])
    assert summary["scenario_count"] == 0
