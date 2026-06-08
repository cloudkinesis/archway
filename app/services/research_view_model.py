from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class StatusBadge(BaseModel):
    label: str
    value: str
    tone: Literal["success", "warning", "danger", "neutral"] = "neutral"


class ExecutiveBriefingView(BaseModel):
    headline: str
    one_minute_read: list[str] = Field(default_factory=list)
    aws_direction: list[str] = Field(default_factory=list)
    governance_boundary: list[str] = Field(default_factory=list)
    top_risks: list[str] = Field(default_factory=list)
    validate_next: list[str] = Field(default_factory=list)


class OverviewView(BaseModel):
    use_case_interpretation: list[str] = Field(default_factory=list)
    understood: list[str] = Field(default_factory=list)
    confirmed: list[str] = Field(default_factory=list)
    assumed: list[str] = Field(default_factory=list)
    open_items: list[str] = Field(default_factory=list)
    poc_path: list[str] = Field(default_factory=list)
    production_path: list[str] = Field(default_factory=list)


class ServiceRationaleView(BaseModel):
    group: str
    service: str
    role: str
    why_selected: str
    alternatives: list[str] = Field(default_factory=list)
    validation_needed: str = "Validate service limits, regional availability, and pricing before procurement."
    evidence_summary: str = "Evidence available in Evidence tab."


class ArchitectureRationaleView(BaseModel):
    pattern: str
    poc_recommendation: list[str] = Field(default_factory=list)
    production_recommendation: list[str] = Field(default_factory=list)
    service_groups: list[ServiceRationaleView] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    do_not_build_first: list[str] = Field(default_factory=list)


class PricingAssumptionView(BaseModel):
    assumption: str
    value: str
    unit: str = ""
    source: Literal["user confirmed", "interview inferred", "policy default", "model inferred", "missing"] = "model inferred"
    confidence: str = "medium"
    used_by: str = "pricing"
    notes: str = ""


class PricingLineView(BaseModel):
    service: str
    architecture_role: str
    cost_category: str
    quantity: str
    unit: str
    rate: str
    monthly_subtotal: str
    pricing_basis: Literal["SKU-backed", "AWS catalog-referenced", "heuristic", "excluded"]
    confidence: str
    trace_summary: str
    trace: dict[str, Any] = Field(default_factory=dict)


class PricingView(BaseModel):
    phase: Literal["poc", "production"]
    headline_safe: bool
    procurement_ready: bool
    monthly_low: str
    monthly_expected: str
    monthly_high: str
    confidence: str
    sku_backed_subtotal: str = "$0"
    directional_subtotal: str = "$0"
    heuristic_subtotal: str = "$0"
    excluded_costs: list[str] = Field(default_factory=list)
    last_refreshed: str
    assumptions: list[PricingAssumptionView] = Field(default_factory=list)
    line_items: list[PricingLineView] = Field(default_factory=list)
    readiness_findings: list[str] = Field(default_factory=list)


class CompetitorItemView(BaseModel):
    name: str
    type: str
    relevance: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    impact: str
    source: str


class CompetitorScanView(BaseModel):
    status: Literal["completed", "not_run", "skipped", "failed"]
    tavily_enabled: bool
    scan_enabled: bool
    budget: int
    queries_attempted: int = 0
    queries_executed: int
    results_returned: int
    results_used: int
    query_plan: list[str] = Field(default_factory=list)
    analysis_summary: list[str] = Field(default_factory=list)
    aws_positioning_implications: list[str] = Field(default_factory=list)
    skipped_reason: str | None = None
    failure_reason: str | None = None
    competitors: list[CompetitorItemView] = Field(default_factory=list)


class RiskValidationView(BaseModel):
    group: str
    title: str
    severity: str
    why_it_matters: str
    basis: str
    mitigation: str
    validation_owner: str
    blocks_procurement: bool
    blocks_diagram_finalization: bool


class EvidenceItemView(BaseModel):
    title: str
    source_type: str
    confidence: str
    used_for: str
    url: str | None = None
    debug_id: str | None = None


class EvidenceSummaryView(BaseModel):
    top_sources: list[EvidenceItemView] = Field(default_factory=list)
    source_counts: dict[str, int] = Field(default_factory=dict)
    confidence_distribution: dict[str, int] = Field(default_factory=dict)
    claim_coverage: str
    evidence_authority: str
    last_refreshed: str
    evidence_items_for_debug: list[EvidenceItemView] = Field(default_factory=list)


class ResearchViewModel(BaseModel):
    session_id: str
    revision_id: str = "active"
    generated_at: str
    model: str
    verdict: StatusBadge
    readiness: StatusBadge
    pricing_confidence: StatusBadge
    evidence_quality: StatusBadge
    competitor_scan_status: StatusBadge
    executive_briefing: ExecutiveBriefingView
    overview: OverviewView
    architecture_rationale: ArchitectureRationaleView
    pricing_poc: PricingView
    pricing_production: PricingView
    competitor_scan: CompetitorScanView
    risks: list[RiskValidationView] = Field(default_factory=list)
    validation_items: list[str] = Field(default_factory=list)
    evidence_summary: EvidenceSummaryView
    raw_debug_refs: dict[str, str] = Field(default_factory=dict)


@dataclass(frozen=True)
class ResearchPresentationProfile:
    id: str
    architecture_pattern: str
    understood_prefix: str
    confirmed_points: list[str]
    tradeoffs: list[str]
    do_not_build_first: list[str]
    excluded_costs: list[str]
    pricing_assumptions: list[tuple[str, str, str, str, str]] = field(default_factory=list)


def build_research_view_model(session_id: str, report: dict | None, digest: dict | None, pricing: dict | None, narrative: dict | None) -> ResearchViewModel | None:
    if not report:
        return None
    pricing = pricing or report.get("pricing_analysis") or {}
    digest = digest or {}
    profile = _presentation_profile(report)
    metadata = report.get("metadata") or {}
    readiness = metadata.get("customer_readiness") or {}
    evidence_quality = metadata.get("evidence_quality") or {}
    competitor_status = metadata.get("competitor_scan") or {}
    generated_at = str(report.get("generated_at") or datetime.now(timezone.utc).isoformat())
    model = str(digest.get("generated_by") or "deterministic")
    executive = ExecutiveBriefingView(
        headline=_domain_clean(digest.get("headline") or _headline(report)),
        one_minute_read=_domain_clean_list(digest.get("one_minute_read") or []),
        aws_direction=_domain_clean_list(digest.get("aws_direction") or []),
        governance_boundary=_domain_clean_list(digest.get("governance_boundaries") or []),
        top_risks=_domain_clean_list(digest.get("top_risks") or []),
        validate_next=_domain_clean_list(digest.get("validate_next") or []),
    )
    evidence = _evidence_summary(report, generated_at)
    competitor = _competitor_view(report)
    pricing_poc = _pricing_view("poc", pricing, report, generated_at)
    pricing_prod = _pricing_view("production", pricing, report, generated_at)
    risks = _risk_views(report, pricing)
    return ResearchViewModel(
        session_id=session_id,
        generated_at=generated_at,
        model=model,
        verdict=_badge("Research status", _decision_label(report.get("proceed_recommendation")), _tone_for_decision(report.get("proceed_recommendation"))),
        readiness=_badge("Customer readiness", _readiness_label(readiness.get("status")), "warning" if "directional" in str(readiness.get("status")) else "neutral"),
        pricing_confidence=_badge("Pricing confidence", _pricing_confidence(pricing), "warning"),
        evidence_quality=_badge("Evidence quality", _evidence_authority_label(evidence_quality), "success" if evidence_quality.get("evidence_authority") in {"strong", "official"} else "warning"),
        competitor_scan_status=_badge("Competitor scan", competitor.status.replace("_", " ").title(), "success" if competitor.status == "completed" else "warning"),
        executive_briefing=executive,
        overview=_overview(report, pricing, profile),
        architecture_rationale=_architecture_rationale(report, profile),
        pricing_poc=pricing_poc,
        pricing_production=pricing_prod,
        competitor_scan=competitor,
        risks=risks,
        validation_items=_domain_clean_list((digest.get("validate_next") or []) + [item.mitigation for item in risks[:3]]),
        evidence_summary=evidence,
        raw_debug_refs={"research_report": "research/report.json", "pricing": "pricing/estimate.json", "evidence_map": "exports/*/02D-evidence-map.md"},
    )


def _badge(label: str, value: str, tone: Literal["success", "warning", "danger", "neutral"] = "neutral") -> StatusBadge:
    return StatusBadge(label=label, value=value, tone=tone)


def _decision_label(value: Any) -> str:
    value = str(value or "proceed_with_caution").replace("_", " ").title()
    return value


def _tone_for_decision(value: Any) -> Literal["success", "warning", "danger", "neutral"]:
    text = str(value or "").lower()
    if "do_not" in text or "blocked" in text:
        return "danger"
    if "caution" in text:
        return "warning"
    if "proceed" in text:
        return "success"
    return "neutral"


def _readiness_label(value: Any) -> str:
    return str(value or "unknown").replace("_", " ").title()


def _pricing_confidence(pricing: dict) -> str:
    metadata = pricing.get("metadata") or {}
    maturity = str(metadata.get("pricing_maturity") or "directional").replace("_", " ").title()
    if metadata.get("pricing_can_be_displayed_as_headline") is False:
        return "Directional"
    return maturity


def _evidence_authority_label(value: dict) -> str:
    authority = str(value.get("evidence_authority") or "mixed").replace("_", " ").title()
    return "Official AWS" if authority.lower() in {"strong", "official"} else authority


def _headline(report: dict) -> str:
    return _domain_clean(str(report.get("executive_verdict") or "Research complete."))


def _overview(report: dict, pricing: dict, profile: ResearchPresentationProfile) -> OverviewView:
    interpretation = _domain_clean(str(report.get("use_case_interpretation") or ""))
    assumptions = [_domain_clean(item.get("text", "")) for item in report.get("assumptions", []) if item.get("text")]
    unknowns = [_domain_clean(item) for item in pricing.get("unknown_variables", [])]
    return OverviewView(
        use_case_interpretation=_split_summary(interpretation, 4),
        understood=[
            profile.understood_prefix if profile.understood_prefix else _first_sentence(interpretation),
            "The target design separates recommendation generation from approval and writeback.",
        ],
        confirmed=_confirmed_points(report, profile),
        assumed=assumptions[:5] or ["Sensitive data, auditability, and approval boundaries remain conservative defaults until confirmed."],
        open_items=unknowns[:5] or ["Confirm workload volumes, approval rules, and live pricing drivers before procurement."],
        poc_path=_split_summary(str(report.get("recommended_poc") or "Start with a scoped POC."), 4),
        production_path=_split_summary(str(report.get("recommended_production_direction") or "Harden the design for production."), 4),
    )


def _architecture_rationale(report: dict, profile: ResearchPresentationProfile) -> ArchitectureRationaleView:
    services = report.get("aws_service_recommendations") or []
    return ArchitectureRationaleView(
        pattern=profile.architecture_pattern,
        poc_recommendation=_split_summary(str(report.get("recommended_poc") or ""), 3),
        production_recommendation=_split_summary(str(report.get("recommended_production_direction") or ""), 3),
        service_groups=[_service_view(item) for item in services],
        tradeoffs=profile.tradeoffs,
        do_not_build_first=profile.do_not_build_first,
    )


def _service_view(item: dict) -> ServiceRationaleView:
    service = str(item.get("service") or "AWS service")
    purpose = _domain_clean(item.get("purpose") or "")
    return ServiceRationaleView(
        group=_service_group(service, purpose),
        service=service,
        role=purpose or "Architecture capability",
        why_selected=_domain_clean(item.get("rationale") or "Selected for the extracted workload capability."),
        alternatives=[_domain_clean(alt) for alt in item.get("alternatives_considered", [])[:3]],
        validation_needed=_validation_for_service(service),
        evidence_summary="Supported by source titles in the Evidence tab; refresh AWS Docs/Pricing evidence before procurement.",
    )


def _service_group(service: str, purpose: str) -> str:
    text = f"{service} {purpose}".lower()
    if any(x in text for x in ("epic", "ehr")):
        return "External healthcare systems"
    if "external" in text or "integration" in text:
        return "External systems and integration"
    if any(x in text for x in ("eventbridge", "kinesis", "api gateway", "appsync")):
        return "Integration and event ingestion"
    if any(x in text for x in ("step functions", "sqs", "workflow")):
        return "Workflow and approval"
    if any(x in text for x in ("dynamodb", "s3", "aurora", "rds")):
        return "Operational state and storage"
    if any(x in text for x in ("sagemaker", "bedrock", "ml")):
        return "ML and prediction"
    if any(x in text for x in ("kms", "iam", "cognito", "waf")):
        return "Security and governance"
    if any(x in text for x in ("cloudwatch", "cloudtrail", "audit")):
        return "Observability and audit"
    if any(x in text for x in ("direct connect", "vpn", "vpc")):
        return "Networking and private connectivity"
    return "Application services"


def _validation_for_service(service: str) -> str:
    lower = service.lower()
    if "step functions" in lower:
        return "Approval states, escalation paths, timeout policy, retries, and audit retention."
    if "sagemaker" in lower:
        return "Model quality, refresh cadence, drift controls, endpoint sizing, and rollback behavior."
    if "dynamodb" in lower:
        return "Access patterns, retention, encryption, point-in-time recovery, and query latency."
    if "eventbridge" in lower:
        return "Event schema, ordering/idempotency, retry policy, and partner/source integration limits."
    if "direct connect" in lower or "vpn" in lower:
        return "Connectivity ownership, bandwidth, failover, carrier lead time, and excluded circuit costs."
    return "Service limits, regional availability, security controls, and pricing basis."


def _pricing_view(phase: Literal["poc", "production"], pricing: dict, report: dict, generated_at: str) -> PricingView:
    metadata = pricing.get("metadata") or {}
    ledger = (metadata.get("pricing_ledger") or {}).get("summary") or {}
    headline_safe = bool(metadata.get("pricing_can_be_displayed_as_headline", False)) and phase == "poc"
    procurement = bool(ledger.get("procurement_ready") or False)
    lines = [_pricing_line(item) for item in pricing.get("line_items", [])]
    profile = _presentation_profile(report)
    assumptions = _pricing_assumptions(report, pricing, profile)
    return PricingView(
        phase=phase,
        headline_safe=headline_safe,
        procurement_ready=procurement,
        monthly_low=_money(pricing.get("low_monthly_usd")) if phase == "poc" else "Directional only",
        monthly_expected=_money(pricing.get("expected_monthly_usd")) if headline_safe else "Withheld from headline",
        monthly_high=_money(pricing.get("high_monthly_usd")) if phase == "poc" else "Directional only",
        confidence="Procurement-ready" if procurement else _pricing_confidence(pricing),
        sku_backed_subtotal=_money(ledger.get("sku_tier_backed_subtotal") or 0),
        directional_subtotal=_money(ledger.get("pricing_page_or_mcp_backed_subtotal") or pricing.get("expected_monthly_usd") or 0),
        heuristic_subtotal=_money(ledger.get("heuristic_subtotal") or 0),
        excluded_costs=profile.excluded_costs,
        last_refreshed=generated_at,
        assumptions=assumptions,
        line_items=lines,
        readiness_findings=_pricing_findings(pricing, assumptions),
    )


def _pricing_line(item: dict) -> PricingLineView:
    trace = item.get("pricing_trace") or {}
    basis = _pricing_basis(item, trace)
    return PricingLineView(
        service=str(item.get("service") or "AWS service"),
        architecture_role=_domain_clean(item.get("unit_basis") or "Architecture cost line"),
        cost_category=_category_for_service(str(item.get("service") or "")),
        quantity=str(trace.get("quantity") or trace.get("monthly_quantity") or "directional"),
        unit=str(trace.get("unit") or "monthly"),
        rate=str(trace.get("rate") or trace.get("unit_price") or "not SKU-bound"),
        monthly_subtotal=_money(item.get("expected_monthly_usd")),
        pricing_basis=basis,
        confidence="high" if basis == "SKU-backed" else "medium" if basis == "AWS catalog-referenced" else "low",
        trace_summary=_trace_summary(basis, trace),
        trace={
            "offer_code": trace.get("service_code") or trace.get("offer_code"),
            "region": trace.get("region"),
            "sku": trace.get("sku"),
            "usage_type": trace.get("usage_type"),
            "operation": trace.get("operation"),
            "price_dimension_id": trace.get("price_dimension_id"),
            "unit": trace.get("unit"),
            "rate": trace.get("rate") or trace.get("unit_price"),
            "quantity_formula": trace.get("quantity_formula"),
            "monthly_subtotal_formula": trace.get("monthly_subtotal_formula"),
            "retrieval_method": trace.get("source") or trace.get("calculation_source"),
            "retrieved_at": trace.get("retrieved_at"),
            "included_in_headline_estimate": basis == "SKU-backed",
            "warnings": trace.get("limitation") or trace.get("reason") or "Exact SKU/tier binding unavailable.",
        },
    )


def _pricing_basis(item: dict, trace: dict) -> Literal["SKU-backed", "AWS catalog-referenced", "heuristic", "excluded"]:
    evidence_class = str(item.get("evidence_class") or trace.get("evidence_class") or "").lower()
    if trace.get("procurement_ready") or "sku" in evidence_class:
        return "SKU-backed"
    if trace.get("price_list_evidence_id") or "catalog" in str(trace.get("calculation_source", "")).lower():
        return "AWS catalog-referenced"
    if "excluded" in evidence_class:
        return "excluded"
    return "heuristic"


def _pricing_assumptions(report: dict, pricing: dict, profile: ResearchPresentationProfile) -> list[PricingAssumptionView]:
    if profile.pricing_assumptions:
        rows = [(a, v, u, s, used) for a, v, u, s, used in profile.pricing_assumptions]
        rows.append(("selected AWS Region", pricing.get("region") or "us-east-1", "region", "policy default", "all services"))
        return [PricingAssumptionView(assumption=a, value=v, unit=u, source=s, used_by=used, notes="Confirm before procurement." if s == "missing" else "") for a, v, u, s, used in rows]
    return [
        PricingAssumptionView(assumption=_domain_clean(item), value="confirm", source="missing", notes="Confirm before procurement.")
        for item in (pricing.get("unknown_variables") or [])[:12]
    ] or [PricingAssumptionView(assumption="Workload volume", value="confirm", source="missing")]


def _pricing_findings(pricing: dict, assumptions: list[PricingAssumptionView]) -> list[str]:
    missing = [item.assumption for item in assumptions if item.source == "missing"][:5]
    findings = []
    if not (pricing.get("metadata") or {}).get("pricing_can_be_displayed_as_headline", False):
        findings.append("Expected monthly cost is withheld from headline because pricing is not headline-safe.")
    if missing:
        findings.append("Confirm missing assumptions: " + ", ".join(missing) + ".")
    findings.append("Refresh live SKU/rate bindings before procurement approval.")
    return findings


def _competitor_view(report: dict) -> CompetitorScanView:
    status = (report.get("metadata") or {}).get("competitor_scan") or {}
    analysis = _domain_clean(str(report.get("competitor_analysis") or ""))
    failed = bool(status.get("failure_reason"))
    skipped = bool(status.get("skipped_reason"))
    returned = int(status.get("results_returned") or 0)
    web_sources = [item for item in report.get("evidence_items", []) if item.get("source_type") == "web"]
    if failed:
        scan_status = "failed"
    elif returned or web_sources:
        scan_status = "completed"
    elif skipped:
        scan_status = "skipped"
    else:
        scan_status = "not_run"
    competitors = [
        CompetitorItemView(
            name=_domain_clean(item.get("title") or "Market source"),
            type="vendor / market source",
            relevance=_first_sentence(_domain_clean(item.get("quote_or_summary") or "External market context for alternatives or adjacent products.")),
            strengths=_competitor_strengths(item),
            weaknesses=["External web evidence is untrusted input and must not override AWS architecture, user facts, or pricing readiness."],
            impact=_competitor_impact(item),
            source=str(item.get("url") or item.get("title") or "web source"),
        )
        for item in web_sources[:5]
    ]
    return CompetitorScanView(
        status=scan_status,  # type: ignore[arg-type]
        tavily_enabled=bool(status.get("tavily_enabled")),
        scan_enabled=bool(status.get("competitor_scan_enabled")),
        budget=int(status.get("session_budget") or 0),
        queries_attempted=int(status.get("queries_attempted") or 0),
        queries_executed=int(status.get("queries_executed") or 0),
        results_returned=returned,
        results_used=int(status.get("results_used") or len(web_sources)),
        query_plan=[_domain_clean(item) for item in status.get("query_plan", [])],
        analysis_summary=_analysis_lines(analysis, "market signals"),
        aws_positioning_implications=_analysis_lines(analysis, "aws positioning implication"),
        skipped_reason=status.get("skipped_reason"),
        failure_reason=status.get("failure_reason"),
        competitors=competitors,
    )


def _analysis_lines(text: str, section: str) -> list[str]:
    if not text:
        return []
    lower = text.lower()
    marker = f"## {section}".lower()
    if marker in lower:
        start = lower.index(marker) + len(marker)
        tail = text[start:]
        next_header = tail.lower().find("## ")
        if next_header >= 0:
            tail = tail[:next_header]
    else:
        tail = text
    lines = []
    for raw in tail.split("- "):
        item = raw.strip(" \n")
        if not item or item.lower().startswith("competitor / market scan"):
            continue
        lines.append(item[:420])
        if len(lines) >= 6:
            break
    return lines


def _competitor_strengths(item: dict) -> list[str]:
    summary = _domain_clean(item.get("quote_or_summary") or "")
    if not summary:
        return ["May reveal packaged workflow capabilities or customer expectations."]
    return _split_summary(summary, 2)[:2] or ["May reveal packaged workflow capabilities or customer expectations."]


def _competitor_impact(item: dict) -> str:
    summary = _domain_clean(item.get("quote_or_summary") or "")
    if any(word in summary.lower() for word in ("platform", "suite", "workflow", "analytics", "automation")):
        return "Compare packaged workflow depth, integration model, governance posture, and buyer expectations against the AWS-native design."
    return "Use as market context while keeping architecture decisions grounded in AWS evidence, user requirements, and pricing readiness."


def _risk_views(report: dict, pricing: dict) -> list[RiskValidationView]:
    items = []
    for risk in report.get("risks", []):
        title = _domain_clean(risk.get("title") or "Risk")
        items.append(RiskValidationView(
            group=_risk_group(title),
            title=title,
            severity=str(risk.get("severity") or "medium").title(),
            why_it_matters=_why_risk_matters(title),
            basis="Research finding, user input, or conservative architecture assumption.",
            mitigation=_domain_clean(risk.get("mitigation") or "Validate before procurement."),
            validation_owner=_risk_owner(title),
            blocks_procurement=True,
            blocks_diagram_finalization="governance" in title.lower() or "automated" in title.lower(),
        ))
    for missing in (pricing.get("unknown_variables") or [])[:4]:
        items.append(RiskValidationView(
            group="Pricing and procurement",
            title=_domain_clean(missing),
            severity="Medium",
            why_it_matters="Pricing cannot be procurement-ready until this driver is confirmed.",
            basis="Pricing model missing driver.",
            mitigation="Confirm the driver and refresh pricing evidence.",
            validation_owner="Solution architect / customer finance owner",
            blocks_procurement=True,
            blocks_diagram_finalization=False,
        ))
    return items


def _risk_group(title: str) -> str:
    lower = title.lower()
    if any(x in lower for x in ("security", "sensitive", "phi", "compliance")):
        return "Security and compliance"
    if any(x in lower for x in ("approval", "automated", "action", "governance")):
        return "Governance and human approval"
    if "pricing" in lower or "cost" in lower:
        return "Pricing and procurement"
    if any(x in lower for x in ("prediction", "model", "data quality", "false")):
        return "Data quality and ML performance"
    if any(x in lower for x in ("integration", "source", "ehr", "epic")):
        return "Integration and source systems"
    return "Architecture and operations"


def _evidence_summary(report: dict, generated_at: str) -> EvidenceSummaryView:
    items = report.get("evidence_items") or []
    counts: dict[str, int] = {}
    confidence: dict[str, int] = {}
    for item in items:
        counts[str(item.get("source_type") or "unknown")] = counts.get(str(item.get("source_type") or "unknown"), 0) + 1
        confidence[str(item.get("confidence") or "unknown")] = confidence.get(str(item.get("confidence") or "unknown"), 0) + 1
    coverage = report.get("citation_coverage") or {}
    authority = ((report.get("metadata") or {}).get("evidence_quality") or {}).get("evidence_authority") or "mixed"
    evidence_items = [
        EvidenceItemView(
            title=_domain_clean(item.get("title") or "Source"),
            source_type=str(item.get("source_type") or "unknown").replace("_", " ").title(),
            confidence=str(item.get("confidence") or "unknown"),
            used_for=_used_for(item),
            url=str(item.get("url")) if item.get("url") else None,
            debug_id=item.get("id"),
        )
        for item in items
    ]
    return EvidenceSummaryView(
        top_sources=[item.model_copy(update={"debug_id": None}) for item in evidence_items[:8]],
        source_counts=counts,
        confidence_distribution=confidence,
        claim_coverage=f"{coverage.get('coverage_percent', 0)}%",
        evidence_authority=str(authority).replace("_", " ").title(),
        last_refreshed=generated_at,
        evidence_items_for_debug=evidence_items,
    )


def _used_for(item: dict) -> str:
    source = str(item.get("source_type") or "")
    if source == "aws_pricing":
        return "Pricing basis"
    if source == "aws_docs":
        return "AWS service capability"
    if source == "user_input":
        return "Customer facts"
    if source == "web":
        return "Competitor / market context"
    if source == "local_policy":
        return "Archway safety policy"
    return "Research context"


def _confirmed_points(report: dict, profile: ResearchPresentationProfile) -> list[str]:
    if profile.confirmed_points:
        return profile.confirmed_points
    return _split_summary(str(report.get("use_case_interpretation") or ""), 4)


def _presentation_profile(report: dict) -> ResearchPresentationProfile:
    families = set((report.get("metadata") or {}).get("workload_families") or [])
    domain = str(((report.get("metadata") or {}).get("use_case_profile") or {}).get("domain") or "").lower()
    if domain == "healthcare" or "healthcare_operations_scheduling" in families:
        return ResearchPresentationProfile(
            id="healthcare_operations_scheduling",
            architecture_pattern="AWS-native healthcare operations scheduling with governed event ingestion, approval workflow, PHI-safe operational state, ML prediction, audit, and private integration.",
            understood_prefix="Archway understood this as a perioperative command-center workflow for OR readiness, delay prediction, and approval-gated schedule recommendations.",
            confirmed_points=[
                "POC starts with one hospital, one surgical service line, and 4-8 operating rooms.",
                "Schedule-changing actions require charge nurse or authorized clinical operations approval.",
                "Room sensing must arrive as non-identifying operational signals; no patient-identifiable video storage.",
                "US-only data residency, encryption, least privilege, audit logging, and graceful degradation are required.",
            ],
            tradeoffs=[
                "Managed workflow and storage reduce operational burden but still need hospital-specific integration validation.",
                "Private connectivity improves control for EHR/scheduling integration but may add implementation lead time and external carrier cost.",
                "ML recommendations should remain approval-gated until model quality, drift, and clinical operations impact are measured.",
            ],
            do_not_build_first=[
                "Do not build autonomous schedule-changing writeback in the POC.",
                "Do not store patient-identifiable video or perform facial recognition.",
                "Do not make the platform the system of record for clinical scheduling.",
            ],
            excluded_costs=[
                "External Epic/EHR licensing excluded.",
                "External OR command-center vendor costs excluded.",
                "Hospital network/carrier/cross-connect costs excluded unless explicitly priced.",
                "Implementation/professional services excluded.",
                "Enterprise discounts/private pricing, taxes, support plan costs, and unmodeled data transfer excluded.",
            ],
            pricing_assumptions=[
                ("hospital sites", "1", "site", "user confirmed", "POC scope"),
                ("surgical service lines", "1", "service line", "user confirmed", "POC scope"),
                ("operating rooms", "4-8", "rooms", "user confirmed", "POC scale"),
                ("OR readiness events/day", "confirm", "events/day", "missing", "EventBridge, storage, logs"),
                ("patient check-in events/day", "confirm", "events/day", "missing", "integration and state updates"),
                ("case start/end events/day", "confirm", "events/day", "missing", "workflow state updates"),
                ("room turnover events/day", "confirm", "events/day", "missing", "readiness analytics"),
                ("anesthesia readiness events/day", "confirm", "events/day", "missing", "readiness analytics"),
                ("sterile processing readiness events/day", "confirm", "events/day", "missing", "readiness analytics"),
                ("staffing readiness events/day", "confirm", "events/day", "missing", "readiness analytics"),
                ("recommendation scoring events/day", "confirm", "events/day", "missing", "SageMaker/Lambda sizing"),
                ("approval workflow executions/day", "confirm", "executions/day", "missing", "Step Functions/SQS"),
                ("EHR writeback attempts/day", "confirm", "attempts/day", "missing", "approval-gated integration"),
                ("active coordinator users/month", "confirm", "users/month", "missing", "identity and UI usage"),
                ("audit retention duration", "7", "years", "interview inferred", "audit storage"),
            ],
        )
    if domain == "telecommunications" or "telecom_network_analytics" in families:
        return ResearchPresentationProfile(
            id="telecom_enterprise",
            architecture_pattern="AWS-native telecom analytics with governed network-event ingestion, OSS/BSS integration, scalable stream processing, analytics storage, QoS reporting, audit, and controlled cutover/rollback.",
            understood_prefix="Archway understood this as a telecom network analytics workload for CDR/network-event ingestion, congestion prediction, OSS/BSS integration, and governed operational reporting.",
            confirmed_points=[
                "Telecom source systems, OSS/BSS boundaries, and network-event feeds must be confirmed before migration or production cutover.",
                "Network analytics and QoS workflows require explicit retention, regulatory, and rollback requirements.",
                "HBase/HDFS/Spark migrations require access-pattern validation before selecting a target store.",
                "Parallel-run duration, cutover plan, and rollback gates are production readiness items.",
            ],
            tradeoffs=[
                "Managed streaming and analytics reduce platform operations but require event-rate, retention, and partition-key validation.",
                "Migrating HBase/HDFS/Spark workloads needs access-pattern discovery before choosing DynamoDB, Keyspaces, EMR, S3/Iceberg, or OpenSearch.",
                "OSS/BSS integration improves operational usefulness but increases dependency, cutover, and rollback complexity.",
            ],
            do_not_build_first=[
                "Do not assume OSS means telecom unless OSS/BSS, network operations, or telecom context is explicit.",
                "Do not map HBase directly to DynamoDB or Keyspaces without row-key, QPS, consistency, and scan-pattern validation.",
                "Do not cut over production analytics until parallel-run accuracy and rollback gates pass.",
            ],
            excluded_costs=[
                "External OSS/BSS vendor licensing and integration services excluded.",
                "Carrier network equipment, probes, and data-center cross-connect costs excluded unless explicitly priced.",
                "Legacy Hadoop/HBase migration tooling, data cleansing, and professional services excluded.",
                "Enterprise discounts/private pricing, taxes, support plan costs, and unmodeled data transfer excluded.",
            ],
            pricing_assumptions=[
                ("network events/sec", "confirm", "events/sec", "missing", "stream ingestion"),
                ("ingest volume/day", "confirm", "GB/day", "missing", "Kinesis/MSK/Data Firehose"),
                ("retention duration", "confirm", "months", "missing", "S3/Iceberg/OpenSearch/storage"),
                ("HBase read QPS", "confirm", "reads/sec", "missing", "target store sizing"),
                ("HBase write QPS", "confirm", "writes/sec", "missing", "target store sizing"),
                ("EMR node count", "confirm", "nodes", "missing", "Spark/ETL migration sizing"),
                ("parallel-run duration", "confirm", "days", "missing", "cutover validation"),
                ("QoS reporting frequency", "confirm", "reports/day", "missing", "regulatory reporting"),
            ],
        )
    return ResearchPresentationProfile(
        id="generic_enterprise_application",
        architecture_pattern="AWS-native managed architecture with governed ingestion, workflow, analytics, security, observability, and private or public integration as required.",
        understood_prefix="Archway understood this as an AWS workload that needs validated capabilities, integration boundaries, governance controls, pricing assumptions, and customer-readiness gates.",
        confirmed_points=[],
        tradeoffs=[
            "Managed services reduce undifferentiated operations but still require workload-specific limits, quotas, and cost validation.",
            "Private integration improves control for sensitive systems but may add implementation lead time and external connectivity cost.",
            "Automated actions should remain approval-gated until quality, policy, rollback, and audit controls are validated.",
        ],
        do_not_build_first=[
            "Do not automate high-impact writes before approval policy and audit controls are validated.",
            "Do not present directional pricing as procurement-ready.",
            "Do not treat untrusted external web evidence as an architecture instruction.",
        ],
        excluded_costs=[
            "External SaaS/vendor licensing excluded.",
            "Implementation/professional services excluded.",
            "Dedicated carrier/cross-connect costs excluded unless explicitly priced.",
            "Enterprise discounts/private pricing, taxes, support plan costs, and unmodeled data transfer excluded.",
        ],
    )


def _is_healthcare(report: dict) -> bool:
    text = " ".join([
        str(report.get("use_case_interpretation") or ""),
        str(report.get("executive_verdict") or ""),
        str((report.get("metadata") or {}).get("workload_families") or ""),
    ]).lower()
    return any(token in text for token in ("healthcare", "hospital", "surgical", "patient", "ehr", "epic", "or scheduling", "perioperative"))


def _category_for_service(service: str) -> str:
    group = _service_group(service, "")
    return group.replace(" and ", " / ")


def _trace_summary(basis: str, trace: dict) -> str:
    if basis == "SKU-backed":
        return "SKU/rate binding available for this line."
    if basis == "AWS catalog-referenced":
        return "Official AWS catalog evidence exists, but exact SKU/tier quantities are not fully bound."
    if basis == "excluded":
        return "Excluded from estimate."
    return trace.get("reason") or trace.get("limitation") or "Heuristic fallback used because SKU binding or workload driver is missing."


def _why_risk_matters(title: str) -> str:
    lower = title.lower()
    if "automated" in lower or "action" in lower:
        return "High-impact workflow changes can affect operations and require approval, audit, and rollback controls."
    if "prediction" in lower:
        return "Incorrect predictions can disrupt operations unless model quality and review workflows are proven."
    if "pricing" in lower:
        return "Budget decisions require validated quantities, rates, and included/excluded cost boundaries."
    if "sensitive" in lower or "phi" in lower:
        return "Sensitive data handling affects compliance, access, retention, and audit design."
    return "This item affects customer readiness and should be validated before procurement."


def _risk_owner(title: str) -> str:
    lower = title.lower()
    if "pricing" in lower:
        return "Finance / solution architect"
    if "sensitive" in lower or "phi" in lower or "compliance" in lower:
        return "Security and compliance owner"
    if "prediction" in lower:
        return "ML owner and operations lead"
    if "automated" in lower or "action" in lower:
        return "Business process owner"
    return "Solution architect"


def _money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except Exception:
        return "n/a"


def _split_summary(text: str, limit: int) -> list[str]:
    cleaned = _domain_clean(text)
    parts = []
    for raw in cleaned.replace("; ", ". ").split(". "):
        item = raw.strip(" .")
        if item:
            parts.append(item + ".")
        if len(parts) >= limit:
            break
    return parts or [cleaned] if cleaned else []


def _first_sentence(text: str) -> str:
    return (_split_summary(text, 1) or [""])[0]


def _domain_clean_list(items: list[Any]) -> list[str]:
    return [_domain_clean(item) for item in items if _domain_clean(item)][:5]


def _domain_clean(value: Any) -> str:
    text = " ".join(str(value or "").replace("\n", " ").split())
    replacements = {
        "OPEN_VALIDATION_ITEM:": "",
        "No Reason:": "",
        "directional_only": "directional only",
        "proceed_with_caution": "proceed with caution",
        "telemetry streams": "operational event feeds",
        "telemetry": "operational events",
        "asset_count": "operating room scope",
        "asset count": "operating room scope",
        "candidate anomalies": "recommendation candidates",
        "confirmed incidents": "approved workflow outcomes",
        "dispatch": "approval workflow",
        "depot": "hospital operations",
        "hot-path": "time-sensitive workflow",
        "hot path": "time-sensitive workflow",
    }
    for before, after in replacements.items():
        text = text.replace(before, after)
    text = text.replace("_", " ")
    return text.strip()
