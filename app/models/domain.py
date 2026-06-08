from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SessionStatus(str, Enum):
    shaping = "shaping"
    researching = "researching"
    architecture = "architecture"
    diagrams = "diagrams"
    complete = "complete"
    error = "error"


class SessionPhase(str, Enum):
    intake = "intake"
    synthesis = "synthesis"
    research = "research"
    architecture = "architecture"
    diagrams = "diagrams"
    diagnostics = "diagnostics"


class HealthStatus(str, Enum):
    ready = "ready"
    degraded = "degraded"
    failed = "failed"


class HealthCheckResult(BaseModel):
    id: str
    label: str
    status: HealthStatus
    required: bool
    reason: str
    details: dict[str, Any] = Field(default_factory=dict)


class HealthSummary(BaseModel):
    status: HealthStatus
    can_continue: bool
    limited_mode_available: bool
    checks: list[HealthCheckResult]
    generated_at: datetime = Field(default_factory=utc_now)


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancel_requested = "cancel_requested"
    cancelled = "cancelled"


class JobRun(BaseModel):
    id: str
    session_id: str
    operation: Literal["research", "architecture", "diagrams", "export"]
    status: JobStatus
    progress: int = 0
    message: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    error: str | None = None
    result_path: str | None = None
    # Additive lifecycle/cancellation metadata (in-memory only).
    expires_at: datetime | None = None
    cancellation_requested: bool = False
    cancellation_requested_at: datetime | None = None
    cancellation_status: str | None = None  # requested | accepted | completed | not_supported | already_terminal


class ExportBundle(BaseModel):
    session_id: str
    name: str
    created_at: datetime = Field(default_factory=utc_now)
    artifact_id: str
    manifest_artifact_id: str
    included_artifacts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class UserPersona(BaseModel):
    name: str
    description: str


class AICapability(BaseModel):
    name: str
    risk_level: Literal["low", "medium", "high"]
    human_approval_required: bool = False


class DataSource(BaseModel):
    name: str
    sensitivity: Literal["public", "internal", "confidential", "regulated", "unknown"] = "unknown"


class Integration(BaseModel):
    name: str
    direction: Literal["read", "write", "read_write", "unknown"] = "unknown"


class ScaleProfile(BaseModel):
    users_per_month: int | None = None
    requests_per_day: int | None = None
    documents_gb: float | None = None
    posture: Literal["poc", "pilot", "production", "unknown"] = "unknown"


class PerformanceProfile(BaseModel):
    latency_sensitivity: Literal["low", "medium", "high", "unknown"] = "unknown"
    availability_target: str = "POC best effort unless production is requested"


class SecurityProfile(BaseModel):
    handles_sensitive_data: bool | None = None
    requires_human_approval: bool = True
    identity_provider: str | None = None
    encryption_required: bool = True


class ComplianceProfile(BaseModel):
    regimes: list[str] = Field(default_factory=list)
    audit_required: bool = True
    data_residency: str | None = None


class BudgetProfile(BaseModel):
    posture: Literal["cost_optimized", "balanced", "performance_first", "unknown"] = "balanced"
    monthly_budget_usd: float | None = None


class Assumption(BaseModel):
    id: str = Field(default_factory=lambda: f"asm_{uuid4().hex[:10]}")
    text: str
    reason: str
    impact: Literal["pricing", "security", "architecture", "performance", "compliance", "scope"]
    confidence: Literal["low", "medium", "high"]
    user_confirmed: bool = False


class OpenQuestion(BaseModel):
    id: str = Field(default_factory=lambda: f"q_{uuid4().hex[:10]}")
    text: str
    impact: Literal["pricing", "security", "architecture", "performance", "compliance", "scope"]


class ResearchQuestion(BaseModel):
    text: str
    why: str


class ResearchDepth(str, Enum):
    quick_brief = "quick_brief"
    standard_research = "standard_research"
    deep_dossier = "deep_dossier"


class DossierClaimKind(str, Enum):
    fact = "FACT"
    assumption = "ASSUMPTION"
    derived_calculation = "DERIVED_CALCULATION"
    recommendation = "RECOMMENDATION"
    risk = "RISK"
    open_validation_item = "OPEN_VALIDATION_ITEM"
    heuristic_estimate = "HEURISTIC_ESTIMATE"


class ResearchClaimType(str, Enum):
    aws_service_capability = "aws_service_capability"
    aws_pricing = "aws_pricing"
    competitor = "competitor"
    compliance = "compliance"
    architecture_rationale = "architecture_rationale"
    performance = "performance"
    cost_estimate = "cost_estimate"
    assumption = "assumption"
    recommendation = "recommendation"
    risk = "risk"


class DossierPricingEvidenceClass(str, Enum):
    sku_tier_backed = "SKU_TIER_BACKED"
    price_list_catalog_backed = "PRICE_LIST_CATALOG_BACKED"
    pricing_mcp_backed = "PRICING_MCP_BACKED"
    official_pricing_page_backed = "OFFICIAL_PRICING_PAGE_BACKED"
    heuristic = "HEURISTIC"
    not_estimated = "NOT_ESTIMATED"


class DossierReadinessStatus(str, Enum):
    customer_ready = "CUSTOMER_READY"
    customer_demo_ready_with_caveats = "CUSTOMER_DEMO_READY_WITH_CAVEATS"
    directional_only = "DIRECTIONAL_ONLY"
    internal_only = "INTERNAL_ONLY"
    failed_validation = "FAILED_VALIDATION"


class DossierResearchQuestion(BaseModel):
    id: str = Field(default_factory=lambda: f"rq_{uuid4().hex[:10]}")
    question: str
    category: Literal[
        "aws_service_fit",
        "pricing",
        "competition",
        "compliance",
        "architecture_pattern",
        "quota_limit",
        "operational_risk",
        "security",
        "hybrid_deployment",
    ]
    required_source_types: list[str]
    priority: Literal["critical", "important", "optional"]


class ResearchClaim(BaseModel):
    id: str = Field(default_factory=lambda: f"rclaim_{uuid4().hex[:10]}")
    text: str
    claim_type: ResearchClaimType
    claim_kind: DossierClaimKind
    confidence: Literal["low", "medium", "high"]
    evidence_ids: list[str] = Field(default_factory=list)
    unsupported: bool = False
    requires_validation: bool = False
    section_ids: list[str] = Field(default_factory=list)


class AssumptionRecord(BaseModel):
    assumption: str
    confidence: Literal["low", "medium", "high"]
    why_needed: str
    impacts: list[str]
    if_wrong: str
    validation_method: str
    used_in_pricing: bool
    used_in_architecture: bool
    evidence_ids: list[str] = Field(default_factory=list)


class RequirementRecord(BaseModel):
    requirement: str
    value: str
    source: str
    architecture_impact: str
    pricing_impact: str
    confidence: Literal["low", "medium", "high"]


class FeasibilityRow(BaseModel):
    requirement: str
    candidate_design: str
    aws_capability: str
    feasibility_verdict: Literal["FEASIBLE", "CONDITIONALLY_FEASIBLE", "REQUIRES_VALIDATION", "HIGH_RISK", "NOT_RECOMMENDED"]
    key_risk: str
    validation_method: str
    evidence_ids: list[str] = Field(default_factory=list)


class PricingFormula(BaseModel):
    formula_text: str
    variables: dict[str, Any] = Field(default_factory=dict)
    unit_price: float | None = None
    quantity: float
    monthly_total: float | None = None
    evidence_class: DossierPricingEvidenceClass
    evidence_ids: list[str] = Field(default_factory=list)


class DossierPricingLine(BaseModel):
    service: str
    usage_driver: str
    quantity: str
    formula: PricingFormula
    unit_price: str
    monthly_estimate: float | None
    evidence_type: DossierPricingEvidenceClass
    sku_usage_rate: str
    confidence: Literal["low", "medium", "high"]
    validation_needed: str


class RiskRecord(BaseModel):
    severity: Literal["low", "medium", "high", "critical"]
    risk: str
    why_it_matters: str
    likelihood: Literal["low", "medium", "high"]
    impact: Literal["low", "medium", "high"]
    mitigation: str
    validation_owner: str
    blocking_status: Literal["blocking", "not_blocking", "watch"]
    evidence_ids: list[str] = Field(default_factory=list)


class DossierConsistencyCheck(BaseModel):
    passed: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DossierQualityScore(BaseModel):
    evidence_score: int
    pricing_score: int
    architecture_score: int
    feasibility_score: int
    risk_score: int
    competitor_score: int
    compliance_score: int
    consistency_score: int
    overall_score: int
    readiness_status: DossierReadinessStatus


class DeepResearchDossier(BaseModel):
    session_id: str
    research_depth: ResearchDepth = ResearchDepth.deep_dossier
    generated_at: datetime = Field(default_factory=utc_now)
    verdict: str
    title: str
    industry: str | None = None
    workload_family: list[str] = Field(default_factory=list)
    estimated_monthly_cost_range: str
    top_validation_gates: list[str]
    research_plan: list[DossierResearchQuestion]
    requirements: list[RequirementRecord]
    assumptions: list[AssumptionRecord]
    claims: list[ResearchClaim]
    feasibility: list[FeasibilityRow]
    pricing_lines: list[DossierPricingLine]
    risks: list[RiskRecord]
    consistency_check: DossierConsistencyCheck
    quality_score: DossierQualityScore
    sections: dict[str, str]


class UseCaseBrief(BaseModel):
    title: str
    raw_use_case: str
    refined_problem_statement: str
    industry: str | None = None
    business_goals: list[str] = Field(default_factory=list)
    users: list[UserPersona] = Field(default_factory=list)
    ai_capabilities: list[AICapability] = Field(default_factory=list)
    data_sources: list[DataSource] = Field(default_factory=list)
    integrations: list[Integration] = Field(default_factory=list)
    scale_profile: ScaleProfile = Field(default_factory=ScaleProfile)
    performance_profile: PerformanceProfile = Field(default_factory=PerformanceProfile)
    security_profile: SecurityProfile = Field(default_factory=SecurityProfile)
    compliance_profile: ComplianceProfile = Field(default_factory=ComplianceProfile)
    budget_profile: BudgetProfile = Field(default_factory=BudgetProfile)
    poc_scope: str = "Build a scoped assistant with read-only integrations first."
    production_scope: str = "Add governed action execution, private connectivity, resilience, and audit controls."
    assumptions: list[Assumption] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    research_questions: list[ResearchQuestion] = Field(default_factory=list)
    use_case_profile: dict[str, Any] = Field(default_factory=dict)


class Session(BaseModel):
    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    status: SessionStatus
    active_phase: SessionPhase
    initial_use_case: str
    current_summary: UseCaseBrief | None = None
    artifacts_path: str


class GapSeverity(str, Enum):
    critical = "critical"
    important = "important"
    optional = "optional"


class UseCaseGap(BaseModel):
    id: str
    text: str
    severity: GapSeverity
    impact: Literal["pricing", "security", "architecture", "performance", "compliance", "scope"]


class SynthesisQuestion(BaseModel):
    id: str
    prompt: str
    why_it_matters: str
    options: list[str]
    recommended_option: str
    assumption_if_skipped: Assumption


class SynthesisReadiness(BaseModel):
    can_proceed: bool
    confidence_score: float
    confidence_label: Literal["low", "medium", "high"]
    critical_gaps: list[UseCaseGap]
    important_gaps: list[UseCaseGap]
    optional_gaps: list[UseCaseGap]
    recommended_minimum_questions: list[SynthesisQuestion]
    assumptions_if_skipped: list[Assumption]


class SynthesisResponse(BaseModel):
    message: str
    brief: UseCaseBrief
    readiness: SynthesisReadiness


class EvidenceItem(BaseModel):
    id: str = Field(default_factory=lambda: f"ev_{uuid4().hex[:10]}")
    source_type: Literal["aws_docs", "aws_blog", "aws_pricing", "web", "mcp", "user_input", "local_policy"]
    title: str
    url: HttpUrl | None = None
    retrieved_at: datetime = Field(default_factory=utc_now)
    quote_or_summary: str
    tool_name: str | None = None
    confidence: Literal["low", "medium", "high"]


class EvidenceAssessment(BaseModel):
    evidence_id: str
    source_type: str
    trust_score: int
    trust_label: Literal["low", "medium", "high"]
    rationale: str
    use_limitations: str


class ReportClaim(BaseModel):
    id: str = Field(default_factory=lambda: f"claim_{uuid4().hex[:10]}")
    claim_type: Literal["fact", "recommendation", "uncertainty"]
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"]
    citation_status: Literal["cited", "assumption_only", "uncited"]


class CitationCoverageReport(BaseModel):
    total_claims: int
    cited_claims: int
    uncited_claims: int
    coverage_percent: float
    passed: bool
    warnings: list[str] = Field(default_factory=list)


class AWSServiceSelection(BaseModel):
    service: str
    purpose: str
    selected: bool = True
    rationale: str
    alternatives_considered: list[str] = Field(default_factory=list)


class AWSServiceRecommendation(AWSServiceSelection):
    evidence_ids: list[str] = Field(default_factory=list)


class PricingLineItem(BaseModel):
    service: str
    unit_basis: str
    low_monthly_usd: float
    expected_monthly_usd: float
    high_monthly_usd: float
    assumptions: list[str]
    evidence_ids: list[str]
    pricing_trace: dict[str, Any] = Field(default_factory=dict)


class PricingAnalysis(BaseModel):
    region: str
    currency: Literal["USD"] = "USD"
    low_monthly_usd: float
    expected_monthly_usd: float
    high_monthly_usd: float
    line_items: list[PricingLineItem]
    main_cost_drivers: list[str]
    cost_optimization_recommendations: list[str]
    unknown_variables: list[str]
    evidence_items: list[EvidenceItem]
    metadata: dict[str, Any] = Field(default_factory=dict)


class RiskItem(BaseModel):
    id: str = Field(default_factory=lambda: f"risk_{uuid4().hex[:10]}")
    title: str
    severity: Literal["low", "medium", "high"]
    mitigation: str
    evidence_ids: list[str] = Field(default_factory=list)


class ResearchReport(BaseModel):
    id: str = Field(default_factory=lambda: f"research_{uuid4().hex[:10]}")
    session_id: str
    executive_verdict: str
    proceed_recommendation: Literal["proceed", "proceed_with_caution", "do_not_proceed_yet"]
    use_case_interpretation: str
    assumptions: list[Assumption]
    feasibility_analysis: str
    viability_analysis: str
    competitor_analysis: str
    aws_service_recommendations: list[AWSServiceRecommendation]
    pricing_analysis: PricingAnalysis
    risks: list[RiskItem]
    recommended_poc: str
    recommended_production_direction: str
    evidence_items: list[EvidenceItem]
    evidence_assessments: list[EvidenceAssessment] = Field(default_factory=list)
    facts: list[ReportClaim] = Field(default_factory=list)
    recommendations: list[ReportClaim] = Field(default_factory=list)
    uncertainties: list[ReportClaim] = Field(default_factory=list)
    citation_coverage: CitationCoverageReport | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=utc_now)


class ArchitectureComponent(BaseModel):
    id: str
    name: str
    service: str
    scope: str | None = None
    region: str | None = None
    vpc_id: str | None = None
    subnet_id: str | None = None
    logical_group: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArchitectureFlow(BaseModel):
    id: str
    source: str
    target: str
    label: str | None = None
    protocol: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SecurityControl(BaseModel):
    name: str
    rationale: str


class GovernanceControl(BaseModel):
    id: str
    control_type: Literal[
        "human_approval",
        "policy_approval",
        "automated_guardrail",
        "kill_switch",
        "rate_limit",
        "dual_control",
        "rollback",
        "manual_override",
        "audit_trail",
        "consent_gate",
        "safety_gate",
    ]
    name: str
    rationale: str
    governed_flow_ids: list[str] = Field(default_factory=list)
    action_types: list[str] = Field(default_factory=list)
    impact_level: Literal["low", "medium", "high", "critical"] = "medium"
    enforcement: Literal["recommendation_only", "manual", "policy", "automated"] = "policy"
    enforcement_point: str | None = None
    failure_behavior: Literal["block", "queue_for_review", "rollback", "allow_with_audit", "recommendation_only"] = "queue_for_review"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ObservabilityControl(BaseModel):
    name: str
    rationale: str


class ArchitectureSpec(BaseModel):
    id: str = Field(default_factory=lambda: f"arch_{uuid4().hex[:10]}")
    session_id: str
    mode: Literal["poc", "production"]
    title: str
    summary: str
    selected_services: list[AWSServiceSelection]
    components: list[ArchitectureComponent]
    flows: list[ArchitectureFlow]
    security_controls: list[SecurityControl]
    governance_controls: list[GovernanceControl] = Field(default_factory=list)
    observability_controls: list[ObservabilityControl]
    scaling_strategy: str
    resilience_strategy: str
    cost_optimization_strategy: str
    assumptions: list[Assumption]
    risks: list[RiskItem]
    regions: list[str] = Field(default_factory=lambda: ["us-east-1"])
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArchitectureValidationIssue(BaseModel):
    severity: Literal["critical", "important", "optional"]
    code: str
    message: str
    mode: Literal["poc", "production"] | None = None


class ArchitectureRevision(BaseModel):
    id: str = Field(default_factory=lambda: f"archrev_{uuid4().hex[:10]}")
    session_id: str
    version: int
    created_at: datetime = Field(default_factory=utc_now)
    reason: str
    specs: list[ArchitectureSpec]
    validation_issues: list[ArchitectureValidationIssue] = Field(default_factory=list)


class DiagramArtifact(BaseModel):
    id: str
    title: str
    mode: Literal["poc", "production"]
    view_id: str
    compiler_view_id: str | None = None
    semantic_view_id: str | None = None
    user_description: str | None = None
    rendered_as_native_view: bool = True
    fallback_reason: str | None = None
    format_paths: dict[str, str]
    preview_svg_artifact_id: str | None = None
    placement_explanation_artifact_id: str | None = None


class DiagramQAReport(BaseModel):
    view_id: str
    passed: bool
    diagnostics: list[dict[str, Any]]
    metrics: dict[str, Any]


class DiagramGalleryResult(BaseModel):
    session_id: str
    architecture_spec_id: str
    mode: Literal["poc", "production"]
    diagrams: list[DiagramArtifact]
    qa_reports: list[DiagramQAReport]
    rendered_view_ids: list[str] = Field(default_factory=list)
    missing_requested_views: list[dict[str, Any]] = Field(default_factory=list)
    view_rendering_ledger: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
