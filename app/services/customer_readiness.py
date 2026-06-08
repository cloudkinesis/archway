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
