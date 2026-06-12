"""Tests for the additive client/audit pack split (Branch 3).

Covers the client-facing copy contract, golden-style fixtures for the three
golden scenarios, non-divergence from root/audit source data, manifest and
verifier behavior, and 0 linter findings on client-facing markdown.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

from app.services.architecture_decision_records import build_decision_records
from app.services.artifact_linter import lint_markdown
from app.services.client_pack import (
    audit_pack_files,
    client_pack_files,
    front_door_readme,
)
from app.services.deep_dossier import DeepDossierService, _cost_range
from app.services.dossier_manifest import MANIFEST_FILENAME, build_dossier_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
TRAILING_STOPWORDS = ("with", "for", "of", "and", "to", "the", "a", "an", "in", "on", "by")
SNAKE_CASE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
RAW_ENUM = re.compile(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")
BROADER_CAVEATS = ("represented through", "represented by", "broader supported view", "compiler view")


def _scenario(name: str) -> dict:
    base = {
        "legal": {
            "title": "AI-Assisted Legal Contract Review and Obligation-Tracking Platform",
            "industry": "legal",
            "families": ["document_intelligence", "rag_assistant"],
            "service": "Amazon API Gateway",
            "purpose": "Controlled API entry point",
            "driver": "assumed_rag_queries_per_day=200",
            "missing": "historical_contract_count",
            "question": "How many historical contracts should Archway model?",
        },
        "healthcare": {
            "title": "A Hospital Needs Operating Room Delay Prediction with Epic Schedule",
            "industry": "healthcare",
            "families": ["healthcare_operations_scheduling"],
            "service": "Amazon EventBridge",
            "purpose": "Decoupled OR event routing",
            "driver": "schedule_events_per_day=1152",
            "missing": "operating_room_count",
            "question": "Which OR source feeds are authoritative, and how fresh are they?",
        },
        "telecom": {
            "title": "Migrate a Telecom HBase HDFS Real-Time Analytics Platform",
            "industry": "telecommunications",
            "families": ["telecom_network_analytics"],
            "service": "Amazon Kinesis Data Streams",
            "purpose": "Durable hot buffer for CDR telemetry",
            "driver": "cdrs_per_day=1440000",
            "missing": "cell_tower_count",
            "question": "What HBase access patterns should Archway preserve?",
        },
    }[name]
    profile = {
        "domain": base["industry"],
        "workload_families": base["families"],
        "capabilities": ["predictive_ml"],
        "deployment_posture": ["hybrid"],
    }
    brief = {
        "title": base["title"],
        "industry": base["industry"],
        "refined_problem_statement": f"Design an AWS architecture for a {base['industry']} workload: representative use case.",
        "poc_scope": "Validate the core path with representative data.",
        "production_scope": "Production deployment with governed operations.",
        "assumptions": [{"text": "Representative volume assumption", "impact": "pricing", "confidence": "medium"}],
        "open_questions": [{"text": base["question"]}],
        "use_case_profile": profile,
    }
    report = {
        "metadata": {
            "use_case_profile": profile,
            "customer_readiness": {"status": "directional_only", "warnings": [], "blockers": []},
            "evidence_quality": {"evidence_authority": "mixed", "citation_coverage": {"passed": True}},
        },
        "citation_coverage": {"coverage_percent": 100.0, "passed": True},
        "evidence_items": [{"id": "ev1", "source_type": "aws_docs"}, {"id": "ev2", "source_type": "local_policy"}],
        "recommended_production_direction": "A production-grade AWS-native platform with governed operations.",
    }
    pricing = {
        "region": "us-east-1",
        "low_monthly_usd": 625.9,
        "expected_monthly_usd": 2940.5,
        "high_monthly_usd": 10570.0,
        "line_items": [],
        "main_cost_drivers": [base["driver"]],
        "unknown_variables": ["availability_target"],
        "metadata": {
            "pricing_can_be_displayed_as_headline": False,
            "pricing_ledger": {"summary": {"headline_safe": False, "procurement_ready": False}},
            "pricing_driver_closure": {
                "missing_drivers": [{"display_name": base["missing"], "why_needed": "scales cost"}],
                "procurement_ready": False,
            },
        },
    }
    architectures = [{
        "mode": "production",
        "title": "Production Architecture",
        "summary": "Event-driven AWS-native platform for this workload.",
        "metadata": {"expected_views": []},
        "selected_services": [{
            "service": base["service"],
            "purpose": base["purpose"],
            "rationale": "It owns this integration boundary.",
            "alternatives_considered": ["Amazon SQS"],
        }],
    }]
    diagrams = [{
        "mode": "production",
        "diagrams": [{
            "view_id": "production_logical_service_flow",
            "format_paths": {"svg": "diagrams/production/arch_1/production_logical_service_flow/diagram.svg"},
        }],
        "view_rendering_ledger": {
            "rendered_via_broader_supported_view": [{
                "view_id": "approval_workflow_view",
                "compiler_view_id": "ai_security_governance_view",
                "reason": "Semantic view is represented through ai_security_governance_view.",
            }],
        },
    }]
    return {"brief": brief, "report": report, "pricing": pricing,
            "architectures": architectures, "diagrams": diagrams, "title": base["title"]}


def _packs(scenario: dict):
    dossier = DeepDossierService().build(
        session_id="sess_test",
        brief=scenario["brief"],
        report=scenario["report"],
        pricing=scenario["pricing"],
        architectures=scenario["architectures"],
        diagrams=scenario["diagrams"],
    )
    records = build_decision_records(
        scenario["architectures"], scenario["pricing"], scenario["report"], scenario["diagrams"],
    )
    client = client_pack_files(
        session_name=scenario["title"],
        brief=scenario["brief"],
        report=scenario["report"],
        pricing=scenario["pricing"],
        architectures=scenario["architectures"],
        diagrams=scenario["diagrams"],
        deep_dossier=dossier,
        decision_records=records,
    )
    audit = audit_pack_files(diagrams=scenario["diagrams"])
    return dossier, records, client, audit


def _prose_lines(content: str) -> list[str]:
    # Exclude inline code spans and table rows, mirroring the linter contract.
    lines = []
    for line in content.split("\n"):
        if line.strip().startswith("|"):
            continue
        lines.append(re.sub(r"`[^`]*`", "", line))
    return lines


# --------------------------------------------------------------------------- #
# Golden client-pack fixtures: copy contract per scenario
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["legal", "healthcare", "telecom"])
def test_client_pack_copy_contract(name):
    scenario = _scenario(name)
    dossier, _records, client, _audit = _packs(scenario)

    # Complete title on the front door, no truncation indicators.
    start = client["START_HERE.md"]
    title_line = start.split("\n", 1)[0]
    assert title_line == f"# {scenario['title']}"
    assert not title_line.lower().rstrip().endswith(TRAILING_STOPWORDS)
    assert not title_line.rstrip().split()[-1].isdigit()

    for path, content in client.items():
        h1 = re.findall(r"^# .*$", content, flags=re.MULTILINE)
        assert len(h1) == 1, f"{path}: expected one H1, got {h1}"
        prose = "\n".join(_prose_lines(content))
        assert not SNAKE_CASE.search(prose), f"{path}: snake_case leaked: {SNAKE_CASE.search(prose).group(0)}"
        assert not RAW_ENUM.search(prose), f"{path}: raw enum leaked: {RAW_ENUM.search(prose).group(0)}"
        lowered = content.lower()
        for caveat in BROADER_CAVEATS:
            assert caveat not in lowered, f"{path}: compiler caveat leaked: {caveat}"

    # Statuses human-readable: the dossier readiness appears as its display
    # label, never as the raw enum.
    from app.services.display_labels import display_label
    memo = client["01-executive-memo.md"]
    assert display_label(dossier.quality_score.readiness_status.value) in memo
    assert dossier.quality_score.readiness_status.value not in memo
    pricing_summary = client["04-pricing-summary.md"]
    assert "not headline-safe" in pricing_summary or "not procurement-ready" in pricing_summary
    assert "**Procurement-ready:** No" in pricing_summary

    # Linter: 0 findings on every client-facing file.
    for path, content in client.items():
        findings = lint_markdown(content, f"client_pack/{path}")
        assert findings == [], f"{path}: {[f.rule_id for f in findings]}"


def test_front_door_readme_contract():
    readme = front_door_readme("AI-Assisted Legal Contract Review and Obligation-Tracking Platform")
    assert readme.startswith("# AI-Assisted Legal Contract Review and Obligation-Tracking Platform")
    assert "client_pack/START_HERE.md" in readme
    assert "audit_pack/README.md" in readme
    assert "compatibility" in readme
    assert lint_markdown(readme, "README.md") == []


# --------------------------------------------------------------------------- #
# Non-divergence: client pack derives from the same source data
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["legal", "healthcare", "telecom"])
def test_client_pack_does_not_diverge_from_source(name):
    scenario = _scenario(name)
    dossier, records, client, _audit = _packs(scenario)

    # Pricing wording is the dossier's own cost-range string (same function,
    # same inputs as root artifacts) — no independent numbers.
    assert dossier.estimated_monthly_cost_range == _cost_range(scenario["pricing"])
    assert dossier.estimated_monthly_cost_range.rstrip(".") in client["01-executive-memo.md"]
    assert dossier.estimated_monthly_cost_range.rstrip(".") in client["04-pricing-summary.md"]
    # No dollar figures other than those in the dossier cost range.
    source_dollars = set(re.findall(r"\$[\d,]+(?:\.\d+)?", dossier.estimated_monthly_cost_range))
    for path in ("01-executive-memo.md", "04-pricing-summary.md"):
        assert set(re.findall(r"\$[\d,]+(?:\.\d+)?", client[path])) <= source_dollars, path

    # Readiness state matches the dossier readiness exactly (display-labeled).
    from app.services.display_labels import display_label
    assert display_label(dossier.quality_score.readiness_status.value) in client["01-executive-memo.md"]

    # Risk content comes from dossier risks only.
    for risk in dossier.risks:
        assert str(risk.risk).rstrip(".") in client["05-risks-and-gates.md"]

    # Architecture services match the spec's selected services exactly.
    for selection in scenario["architectures"][0]["selected_services"]:
        assert selection["service"] in client["03-architecture-summary.md"]
    component_count = sum(1 for r in records if r.decision_id.startswith("adr_component_"))
    if component_count:
        assert f"{component_count} service-selection decisions" in client["03-architecture-summary.md"]

    # Validation gates are the dossier's gates (display-labeled), not new ones.
    for gate in dossier.top_validation_gates[:3]:
        from app.services.display_labels import gate_display
        assert gate_display(gate) in client["01-executive-memo.md"]


# --------------------------------------------------------------------------- #
# Audit pack: honesty preserved
# --------------------------------------------------------------------------- #
def test_audit_pack_preserves_view_fallback_caveats():
    scenario = _scenario("healthcare")
    _dossier, _records, _client, audit = _packs(scenario)
    notes = audit["view-fallback-notes.md"]
    assert "approval_workflow_view" in notes
    assert "represented by" in notes
    guide = audit["README.md"]
    assert "../02B-deep-research-dossier.md" in guide
    assert "../dossier_manifest.md" in guide
    # Audit surface lints clean structurally too.
    for path, content in audit.items():
        assert lint_markdown(content, f"audit_pack/{path}") == []


def test_audit_pack_honest_when_no_fallbacks():
    notes = audit_pack_files(diagrams=[])["view-fallback-notes.md"]
    assert "None recorded." in notes


# --------------------------------------------------------------------------- #
# Manifest inventory + verifier remain VALID with the new directories
# --------------------------------------------------------------------------- #
def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_solution_dossier_cp", REPO_ROOT / "scripts/verify_solution_dossier.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_solution_dossier_cp"] = module
    spec.loader.exec_module(module)
    return module


def test_manifest_inventories_packs_and_verifier_stays_valid(tmp_path):
    scenario = _scenario("legal")
    _dossier, _records, client, audit = _packs(scenario)

    export = tmp_path / "export"
    (export / "raw").mkdir(parents=True)
    for rel in ("README.md", "manifest.json", "01-solution-brief.md", "03-pricing.md", "raw/pricing.json", "raw/session.json"):
        (export / rel).write_text(f"content {rel}\n", encoding="utf-8")
    (export / "client_pack").mkdir()
    for rel, content in client.items():
        (export / "client_pack" / rel).write_text(content, encoding="utf-8")
    (export / "audit_pack").mkdir()
    for rel, content in audit.items():
        (export / "audit_pack" / rel).write_text(content, encoding="utf-8")

    manifest = build_dossier_manifest(
        export, session_id="s", export_name="pkg", generated_at="2026-06-12T00:00:00+00:00",
        session_input="x", brief=scenario["brief"], report=scenario["report"], pricing=scenario["pricing"],
        architectures=scenario["architectures"], architecture_revisions=[], diagrams=[], warnings=[],
        feature_flags={}, convergence_status="passed",
    )
    inventory_paths = {item["path"] for item in manifest["artifact_inventory"]}
    assert "client_pack/START_HERE.md" in inventory_paths
    assert "client_pack/01-executive-memo.md" in inventory_paths
    assert "audit_pack/README.md" in inventory_paths
    assert "audit_pack/view-fallback-notes.md" in inventory_paths

    (export / MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    verifier = _load_verifier()
    ok, errors, _ = verifier.verify(export)
    assert ok, errors

    # Tampering with a client-pack file is detected — the packs are inside the
    # verification boundary, not beside it.
    (export / "client_pack" / "START_HERE.md").write_text("tampered\n", encoding="utf-8")
    ok_after, errors_after, _ = verifier.verify(export)
    assert not ok_after
    assert any("client_pack/START_HERE.md" in str(error) for error in errors_after)
