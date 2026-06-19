"""Tests for readiness tiers and the evidence-on gate (Branch 4).

Tiers grade audience readiness from existing signals only; they never alter
pricing math, governance, or manifest/verifier semantics, and procurement
readiness stays hard to reach by design.
"""

from __future__ import annotations

from app.services.artifact_linter import lint_markdown
from app.services.customer_readiness import (
    ESTIMATE_CLASS_DISPLAY,
    READINESS_TIERS,
    TIER_DISPLAY,
    compute_readiness_tier,
)
from app.services.display_labels import display_label, status_display


def _report(*, citation_passed=True, docs=True, pricing_evidence=True, status="customer_demo_ready_with_caveats", blockers=()):
    return {
        "citation_coverage": {"coverage_percent": 100.0 if citation_passed else 40.0, "passed": citation_passed},
        "metadata": {
            "customer_readiness": {"status": status, "blockers": list(blockers), "warnings": []},
            "evidence_quality": {
                "aws_docs_available": docs,
                "aws_pricing_available": pricing_evidence,
                "evidence_authority": "mixed" if (docs or pricing_evidence) else "limited",
            },
        },
    }


def _pricing(*, headline=False, procurement=False, missing=(), unknowns=(), scenario=False, status=None):
    metadata = {
        "pricing_can_be_displayed_as_headline": headline,
        "pricing_ledger": {"summary": {"headline_safe": headline, "procurement_ready": procurement}},
        "pricing_driver_closure": {
            "missing_drivers": [{"display_name": name, "why_needed": "scales cost"} for name in missing],
            "procurement_ready": procurement,
            "directional_scenario_allowed": scenario,
        },
    }
    if status:
        metadata["status"] = status
    return {
        "region": "us-east-1",
        "low_monthly_usd": 100, "expected_monthly_usd": 200, "high_monthly_usd": 400,
        "unknown_variables": list(unknowns),
        "main_cost_drivers": [],
        "metadata": metadata,
    }


_ARCH = [{"mode": "production", "selected_services": [{"service": "Amazon SQS"}]}]


def _tier(report=None, pricing=None, architectures=_ARCH):
    return compute_readiness_tier(
        report=report if report is not None else _report(),
        pricing=pricing if pricing is not None else _pricing(),
        architectures=architectures,
    )


# --------------------------------------------------------------------------- #
# Tier model
# --------------------------------------------------------------------------- #
def test_tier_ordering_and_display_labels():
    assert READINESS_TIERS == ("internal_only", "directional_only", "demo_ready", "workshop_ready", "procurement_ready")
    assert TIER_DISPLAY["internal_only"] == "Internal only"
    assert TIER_DISPLAY["directional_only"] == "Directional only"
    assert TIER_DISPLAY["demo_ready"] == "Demo ready"
    assert TIER_DISPLAY["workshop_ready"] == "Workshop ready"
    assert TIER_DISPLAY["procurement_ready"] == "Procurement ready"
    assert set(ESTIMATE_CLASS_DISPLAY.values()) == {"Planning estimate", "Budgetary range", "Rate-backed estimate"}


def test_internal_only_reserved_for_hard_failures():
    # internal_only is only for HARD failures — never for evidence/citation.
    assert _tier(architectures=[])["tier"] == "internal_only"          # incoherent
    assert _tier(pricing={})["tier"] == "internal_only"                # incoherent
    assert _tier(report=_report(status="failed"))["tier"] == "internal_only"
    assert _tier(report=_report(status="internal_demo_only"))["tier"] == "internal_only"
    assert _tier(pricing=_pricing(status="invalid_extracted_scale_not_applied"))["tier"] == "internal_only"
    assert _tier(pricing=_pricing(status="directional_only_missing_core_compute_drivers"))["tier"] == "internal_only"
    result = _tier(architectures=[])
    assert result["reasons"]
    assert result["estimate_display"] == "Planning estimate"


def test_evidence_failure_does_not_collapse_coherent_package_to_internal_only():
    # The Codex-discovered regression: a coherent package whose citation gate
    # has not passed must NOT collapse to internal_only.
    capped = _tier(report=_report(citation_passed=False, docs=False, pricing_evidence=True))
    assert capped["tier"] == "demo_ready"
    assert capped["tier"] != "internal_only"


def test_codex_fresh_metadata_case_is_demo_ready():
    # Exact fresh metadata Codex observed: citation not passed, AWS Docs MCP
    # unavailable, AWS Pricing evidence present, otherwise coherent.
    result = _tier(report=_report(citation_passed=False, docs=False, pricing_evidence=True))
    assert result["tier"] == "demo_ready"
    assert result["tier"] not in {"internal_only", "workshop_ready", "procurement_ready"}
    assert any("Evidence/citation gate incomplete" in reason for reason in result["reasons"])
    assert all("capped at Demo ready" in reason for reason in result["reasons"])
    assert result["estimate_display"] == "Planning estimate"


def test_demo_ready_not_over_promoted_without_evidence():
    no_citation = _tier(report=_report(citation_passed=False))
    assert no_citation["tier"] == "demo_ready"
    assert any("citation coverage has not passed" in reason for reason in no_citation["reasons"])
    no_sources = _tier(report=_report(docs=False, pricing_evidence=False))
    assert no_sources["tier"] == "demo_ready"
    assert any("no authoritative AWS documentation or pricing evidence" in reason for reason in no_sources["reasons"])
    weak = _tier(report=_report())
    weak_report = _report()
    weak_report["metadata"]["evidence_quality"]["evidence_authority"] = "limited"
    assert _tier(report=weak_report)["tier"] == "demo_ready"


def test_quality_internal_status_caps_at_internal_only():
    # An explicit internal-only/internal-demo quality grade is a HARD cap.
    capped = _tier(report=_report(status="internal_demo_only"))
    assert capped["tier"] == "internal_only"
    assert any("not suitable even for a controlled demo" in reason for reason in capped["reasons"])


def test_quality_directional_status_caps_client_pack_below_workshop():
    capped = _tier(report=_report(status="directional_only"))
    assert capped["tier"] == "directional_only"
    assert capped["display"] == "Directional only"
    assert capped["estimate_display"] == "Planning estimate"
    assert any("Golden convergence capped" in reason for reason in capped["reasons"])


def test_workshop_ready_requires_evidence_and_citation():
    assert _tier()["tier"] == "workshop_ready"
    # Either authoritative source satisfies the evidence gate.
    assert _tier(report=_report(docs=False, pricing_evidence=True))["tier"] == "workshop_ready"
    # Both failing caps the tier.
    assert _tier(report=_report(docs=False, pricing_evidence=False))["tier"] == "demo_ready"
    assert _tier(report=_report(citation_passed=False))["tier"] == "demo_ready"


def test_procurement_ready_is_hard_to_reach():
    full = _tier(pricing=_pricing(headline=True, procurement=True))
    assert full["tier"] == "procurement_ready"
    assert full["reasons"] == []
    assert full["estimate_display"] == "Rate-backed estimate"
    # Each missing requirement keeps the package at workshop_ready.
    assert _tier(pricing=_pricing(headline=True, procurement=False))["tier"] == "workshop_ready"
    assert _tier(pricing=_pricing(headline=False, procurement=True))["tier"] == "workshop_ready"
    assert _tier(pricing=_pricing(headline=True, procurement=True, missing=("driver_x",)))["tier"] == "workshop_ready"
    assert _tier(pricing=_pricing(headline=True, procurement=True, unknowns=("variable_y",)))["tier"] == "workshop_ready"
    # And never without the evidence gate.
    capped = compute_readiness_tier(
        report=_report(citation_passed=False),
        pricing=_pricing(headline=True, procurement=True),
        architectures=_ARCH,
    )
    assert capped["tier"] == "demo_ready"


# --------------------------------------------------------------------------- #
# Pricing copy vocabulary
# --------------------------------------------------------------------------- #
def test_estimate_class_by_tier():
    assert _tier(architectures=[])["estimate_display"] == "Planning estimate"
    assert _tier(report=_report(citation_passed=False))["estimate_display"] == "Planning estimate"
    # Workshop-ready without a supporting basis stays a planning estimate.
    assert _tier()["estimate_display"] == "Planning estimate"
    # Workshop-ready with a sanctioned directional scenario supports a range.
    assert _tier(pricing=_pricing(scenario=True))["estimate_display"] == "Budgetary range"
    # Workshop-ready with a headline-safe ledger supports a range.
    assert _tier(pricing=_pricing(headline=True))["estimate_display"] == "Budgetary range"
    assert _tier(pricing=_pricing(headline=True, procurement=True))["estimate_display"] == "Rate-backed estimate"


def test_status_display_business_vocabulary():
    assert status_display("invalid_placeholder") == "Pricing basis incomplete"
    assert status_display("pricing_directional_with_assumptions") == "Directional with assumptions"
    assert status_display("pricing_customer_demo_ready") == "Scenario-based planning estimate"
    assert status_display("pricing_procurement_ready") == "Rate-backed estimate"
    # Fallback stays the generic display label.
    assert status_display("missing_critical_drivers") == "Missing critical drivers"


def test_active_or_count_poc_display_override():
    assert display_label("active_or_count_poc") == "Active OR count POC"
    assert display_label("active_or_count_poc", capitalize=False) == "active OR count POC"
    # No global "or" uppercasing: other keys keep the conjunction lowercase.
    assert display_label("payments_or_trades") == "Payments or trades"


# --------------------------------------------------------------------------- #
# Surfaces: client pack copy and linter scope
# --------------------------------------------------------------------------- #
def test_pricing_summary_copy_matches_tier(monkeypatch):
    from app.services.client_pack import client_pack_files
    from app.services.deep_dossier import DeepDossierService

    report = _report()
    pricing = _pricing(headline=True, scenario=True)
    dossier = DeepDossierService().build(
        session_id="s", brief={"title": "Tier Test", "use_case_profile": {}},
        report=report, pricing=pricing, architectures=_ARCH, diagrams=[],
    )
    client = client_pack_files(
        session_name="Tier Test", brief={"title": "Tier Test"}, report=report, pricing=pricing,
        architectures=_ARCH, diagrams=[], deep_dossier=dossier, decision_records=[],
    )
    summary = client["04-pricing-summary.md"]
    assert "**Readiness tier:** Workshop ready" in summary
    assert "**Estimate class:** Budgetary range" in summary
    assert "budgetary range" in summary  # guidance paragraph matches the class
    assert "## To advance beyond this tier" in summary
    memo = client["01-executive-memo.md"]
    assert "**Readiness tier:** Workshop ready" in memo
    assert "budgetary range at the workshop ready tier" in memo
    # No raw tier enums or statuses leak into client prose.
    for content in (summary, memo):
        assert "workshop_ready" not in content
        assert "budgetary_range" not in content
        assert lint_markdown(content, "client_pack/x.md") == []


def test_client_memo_uses_planning_estimate_when_headline_pricing_is_blocked():
    from app.services.client_pack import client_pack_files
    from app.services.deep_dossier import DeepDossierService

    report = _report()
    pricing = _pricing(headline=False, scenario=True)
    dossier = DeepDossierService().build(
        session_id="s", brief={"title": "Tier Test", "use_case_profile": {}},
        report=report, pricing=pricing, architectures=_ARCH, diagrams=[],
    )
    client = client_pack_files(
        session_name="Tier Test", brief={"title": "Tier Test"}, report=report, pricing=pricing,
        architectures=_ARCH, diagrams=[], deep_dossier=dossier, decision_records=[],
    )

    memo = client["01-executive-memo.md"]

    assert "**Readiness tier:** Workshop ready" in memo
    assert "planning estimate at the workshop ready tier" in memo
    assert "budgetary range at the workshop ready tier" not in memo


def test_rendered_client_pack_matches_codex_fresh_metadata():
    # End to end: under the exact fresh metadata Codex observed, the rendered
    # client pack must claim Demo ready — never Workshop/Procurement/Internal.
    from app.services.client_pack import client_pack_files
    from app.services.deep_dossier import DeepDossierService

    report = _report(citation_passed=False, docs=False, pricing_evidence=True)
    pricing = _pricing()
    dossier = DeepDossierService().build(
        session_id="s", brief={"title": "Codex Case", "use_case_profile": {}},
        report=report, pricing=pricing, architectures=_ARCH, diagrams=[],
    )
    client = client_pack_files(
        session_name="Codex Case", brief={"title": "Codex Case"}, report=report, pricing=pricing,
        architectures=_ARCH, diagrams=[], deep_dossier=dossier, decision_records=[],
    )
    for path in ("01-executive-memo.md", "04-pricing-summary.md", "05-risks-and-gates.md"):
        content = client[path]
        assert "**Readiness tier:** Demo ready" in content, path
        assert "Workshop ready" not in content, path
        assert "Procurement ready" not in content, path
        assert "Internal only" not in content, path
        assert lint_markdown(content, f"client_pack/{path}") == [], path
    # The cap reason is rendered in business language on the memo.
    assert "Evidence/citation gate incomplete" in client["01-executive-memo.md"]


def test_rendered_directional_convergence_status_stays_directional():
    from app.services.client_pack import client_pack_files
    from app.services.deep_dossier import DeepDossierService

    report = _report(status="directional_only")
    pricing = _pricing(scenario=True)
    dossier = DeepDossierService().build(
        session_id="s", brief={"title": "Directional Case", "use_case_profile": {}},
        report=report, pricing=pricing, architectures=_ARCH, diagrams=[],
    )
    client = client_pack_files(
        session_name="Directional Case", brief={"title": "Directional Case"}, report=report, pricing=pricing,
        architectures=_ARCH, diagrams=[], deep_dossier=dossier, decision_records=[],
    )

    assert "**Readiness tier:** Directional only" in client["01-executive-memo.md"]
    assert "**Readiness tier:** Directional only" in client["04-pricing-summary.md"]
    assert "Workshop ready" not in client["01-executive-memo.md"]
    assert "workshop ready tier" not in client["01-executive-memo.md"].lower()


def test_rendered_internal_only_package_has_no_enum_leak():
    # An explicit internal-only quality grade must render lint-clean — the raw
    # status enum must never reach client prose via a cap reason.
    from app.services.client_pack import client_pack_files
    from app.services.deep_dossier import DeepDossierService

    report = _report(status="internal_demo_only")
    pricing = _pricing()
    dossier = DeepDossierService().build(
        session_id="s", brief={"title": "Internal Case", "use_case_profile": {}},
        report=report, pricing=pricing, architectures=_ARCH, diagrams=[],
    )
    client = client_pack_files(
        session_name="Internal Case", brief={"title": "Internal Case"}, report=report, pricing=pricing,
        architectures=_ARCH, diagrams=[], deep_dossier=dossier, decision_records=[],
    )
    for path in ("01-executive-memo.md", "04-pricing-summary.md", "05-risks-and-gates.md"):
        content = client[path]
        assert "**Readiness tier:** Internal only" in content, path
        assert "internal_demo_only" not in content and "internal_only" not in content, path
        assert lint_markdown(content, f"client_pack/{path}") == [], path


def test_strict_linting_never_applies_to_audit_or_machine_surfaces():
    text = "# A\n\ncontent\n\n# B\n\nstatus INTERNAL_ONLY..\n"
    audit = lint_markdown(text, "audit_pack/notes.md", strict=True)
    assert audit and all(f.severity == "advisory" for f in audit)
    assert lint_markdown(text, "raw/pricing.json", strict=True) == []
    assert lint_markdown(text, "11-pricing-trace.md", strict=True) == []
