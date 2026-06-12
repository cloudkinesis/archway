from enum import Enum

from pydantic import BaseModel, Field


class CustomerReadinessStatus(str, Enum):
    CUSTOMER_READY = "customer_ready"
    CUSTOMER_DEMO_READY_WITH_CAVEATS = "customer_demo_ready_with_caveats"
    DIRECTIONAL_ONLY = "directional_only"
    INTERNAL_DEMO_ONLY = "internal_demo_only"
    FAILED = "failed"


class CustomerReadinessReport(BaseModel):
    status: CustomerReadinessStatus
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    passed_checks: list[str] = Field(default_factory=list)


GENERIC_RAG_LANES = {"Source Documents", "Request Path", "Model Invocation", "Fulfillment Flow"}


def assess_customer_readiness(
    *,
    evidence_quality: dict,
    citation_passed: bool,
    service_decisions: list[dict],
    pricing_unknowns: list[str],
    pricing_status: str | None = None,
    pricing_metadata: dict | None = None,
    expected_views: list[str] | None = None,
) -> CustomerReadinessReport:
    blockers: list[str] = []
    warnings: list[str] = []
    passed: list[str] = []
    if not citation_passed:
        blockers.append("Citation/evidence gate did not pass.")
    if evidence_quality.get("evidence_authority") in {"limited", "weak"}:
        blockers.append("Evidence authority is limited; authoritative AWS documentation and pricing refresh is required.")
    elif not evidence_quality.get("customer_ready", False):
        warnings.append("Evidence is citable but not procurement-grade; refresh through authoritative AWS Docs and Pricing MCP before customer approval.")
    if not evidence_quality.get("aws_docs_available"):
        blockers.append("AWS Docs MCP unavailable for current AWS recommendations.")
    if not evidence_quality.get("aws_pricing_available"):
        blockers.append("AWS Pricing MCP unavailable for detailed pricing.")
    critical_unknowns = [item for item in pricing_unknowns if item in {"confirmed device telemetry frequency", "confirmed payload size", "measured candidate anomaly rate", "measured confirmed incident rate"}]
    if critical_unknowns:
        warnings.append(f"Pricing still depends on critical workload assumptions: {', '.join(critical_unknowns)}.")
    if pricing_status == "directional_only_missing_core_compute_drivers":
        blockers.append("Pricing is directional only because core compute/SKU drivers remain unknown.")
    if pricing_status == "invalid_extracted_scale_not_applied":
        blockers.append("Pricing scale validation failed; explicit workload metrics were not applied.")
    pricing_ledger = (pricing_metadata or {}).get("pricing_ledger") or {}
    ledger_summary = pricing_ledger.get("summary") or {}
    pricing_maturity = (pricing_metadata or {}).get("pricing_maturity")
    if ledger_summary and not ledger_summary.get("procurement_ready", False):
        warnings.append("Pricing ledger is not procurement-ready because one or more line items lack exact SKU/tier rate binding.")
    if ledger_summary and not ledger_summary.get("headline_safe", False):
        warnings.append("Pricing ledger is not headline-safe; show costs as directional placeholders only.")
    for decision in service_decisions:
        if decision.get("required_validation"):
            warnings.append(f"Service decision {decision.get('decision_id')} requires validation before customer/procurement use.")
    if expected_views and any(view.startswith("rag_") for view in expected_views):
        warnings.append("RAG views are present; confirm this is intentional for the workload.")
    if not blockers:
        passed.extend(["citation coverage", "evidence authority", "pricing evidence"])
    if blockers:
        status = CustomerReadinessStatus.DIRECTIONAL_ONLY
    elif pricing_maturity == "pricing_customer_demo_ready":
        status = CustomerReadinessStatus.CUSTOMER_DEMO_READY_WITH_CAVEATS
    elif pricing_maturity == "pricing_procurement_ready" and not warnings:
        status = CustomerReadinessStatus.CUSTOMER_READY
    else:
        status = CustomerReadinessStatus.CUSTOMER_READY if not warnings else CustomerReadinessStatus.DIRECTIONAL_ONLY
    return CustomerReadinessReport(status=status, blockers=blockers, warnings=warnings, passed_checks=passed)


# --------------------------------------------------------------------------- #
# Readiness tiers (Branch 4 — additive presentation-grade audience tiers).
#
# Tiers grade WHO a package is ready for, derived from existing signals only
# (citation gate, evidence availability, quality readiness, pricing ledger,
# driver closure). They never alter pricing math, the CustomerReadinessStatus
# machinery above, governance, or manifest/verifier semantics — and a tier can
# never promote pricing numbers beyond what their evidence class supports.
# --------------------------------------------------------------------------- #
READINESS_TIERS = ("internal_only", "demo_ready", "workshop_ready", "procurement_ready")

TIER_DISPLAY = {
    "internal_only": "Internal only",
    "demo_ready": "Demo ready",
    "workshop_ready": "Workshop ready",
    "procurement_ready": "Procurement ready",
}

ESTIMATE_CLASS_DISPLAY = {
    "planning_estimate": "Planning estimate",
    "budgetary_range": "Budgetary range",
    "rate_backed_estimate": "Rate-backed estimate",
}

# Quality-machinery readiness statuses that cap a package below workshop use.
_DEMO_CAP_STATUSES = {"internal_only", "internal_demo_only"}
_BLOCKING_STATUSES = {"failed", "failed_validation"}


def compute_readiness_tier(*, report: dict | None, pricing: dict | None, architectures: list | None) -> dict:
    """Grade the package into an audience tier from existing signals only.

    Returns a dict with ``tier``, ``display``, ``estimate_class``,
    ``estimate_display``, and ``reasons`` (why the package is capped at this
    tier — empty only at procurement_ready). Deterministic and fail-closed:
    missing signals always read as "not satisfied".
    """
    report = report or {}
    pricing = pricing or {}
    metadata = report.get("metadata") or {}
    readiness = metadata.get("customer_readiness") or {}
    evidence_quality = metadata.get("evidence_quality") or {}
    pricing_metadata = pricing.get("metadata") or {}
    closure = pricing_metadata.get("pricing_driver_closure") or {}
    ledger_summary = (pricing_metadata.get("pricing_ledger") or {}).get("summary") or {}
    coverage = report.get("citation_coverage") or {}

    reasons: list[str] = []

    # --- internal_only: package not coherent, or explicitly blocked ---------
    coherent = bool(architectures) and bool(pricing)
    blockers = [str(item) for item in readiness.get("blockers") or []]
    quality_status = str(readiness.get("status") or "")
    if not coherent:
        reasons.append("Architecture or pricing output is missing; the package is not yet coherent.")
    reasons.extend(blockers)
    if quality_status in _BLOCKING_STATUSES:
        reasons.append("Quality validation failed for this package.")
    if pricing_metadata.get("status") == "invalid_extracted_scale_not_applied":
        reasons.append("Pricing scale validation failed; extracted workload metrics were not applied.")
    if reasons:
        return _tier_result("internal_only", pricing_metadata, closure, ledger_summary, reasons)

    # --- demo_ready and the evidence-on gate for workshop_ready -------------
    citation_passed = bool(coverage.get("passed", False))
    authoritative_evidence = bool(
        evidence_quality.get("aws_docs_available") or evidence_quality.get("aws_pricing_available")
    )
    if not citation_passed:
        reasons.append("Citation coverage has not passed; claims are not fully evidence-backed yet.")
    if not authoritative_evidence:
        reasons.append("Authoritative AWS documentation or pricing evidence is not present for this run.")
    if quality_status in _DEMO_CAP_STATUSES:
        reasons.append("Quality review currently grades this package for internal demo use; resolve its findings first.")
    if reasons:
        return _tier_result("demo_ready", pricing_metadata, closure, ledger_summary, reasons)

    # --- procurement_ready gates (hard to reach by design) ------------------
    missing_drivers = closure.get("missing_drivers") or []
    unknowns = pricing.get("unknown_variables") or []
    if not ledger_summary.get("procurement_ready", False):
        reasons.append("Pricing line items are not yet rate-backed to exact SKU/tier rates.")
    if pricing_metadata.get("pricing_can_be_displayed_as_headline") is not True:
        reasons.append("Pricing is not yet headline-safe.")
    if missing_drivers:
        reasons.append("Required pricing drivers remain unconfirmed.")
    if unknowns:
        reasons.append("Workload variables remain unconfirmed.")
    if reasons:
        return _tier_result("workshop_ready", pricing_metadata, closure, ledger_summary, reasons)

    return _tier_result("procurement_ready", pricing_metadata, closure, ledger_summary, [])


def _tier_result(tier: str, pricing_metadata: dict, closure: dict, ledger_summary: dict, reasons: list[str]) -> dict:
    estimate_class = _estimate_class(tier, pricing_metadata, closure, ledger_summary)
    return {
        "tier": tier,
        "display": TIER_DISPLAY[tier],
        "estimate_class": estimate_class,
        "estimate_display": ESTIMATE_CLASS_DISPLAY[estimate_class],
        "reasons": reasons,
    }


def _estimate_class(tier: str, pricing_metadata: dict, closure: dict, ledger_summary: dict) -> str:
    """Tier-appropriate pricing vocabulary. Wording only — never math."""
    if tier == "procurement_ready":
        return "rate_backed_estimate"
    # Budgetary range only when the pricing basis supports showing a range:
    # an explicitly headline-safe ledger or a sanctioned directional scenario.
    basis_supports_range = (
        pricing_metadata.get("pricing_can_be_displayed_as_headline") is True
        or bool(closure.get("directional_scenario_allowed"))
    )
    if tier == "workshop_ready" and basis_supports_range:
        return "budgetary_range"
    return "planning_estimate"
