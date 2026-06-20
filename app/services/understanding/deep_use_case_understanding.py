from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.llm.base import LLMMessage, LLMTask, LLMTaskType
from app.services.llm.model_router import ModelRouter
from app.services.metric_extractor import extract_metrics
from app.services.use_case_profile import UseCaseProfile, profile_to_metadata, profile_use_case


class UnderstandingMetric(BaseModel):
    name: str
    value: str | int | float
    unit: str | None = None
    source_text: str
    confidence: Literal["low", "medium", "high"] = "medium"
    derived: bool = False
    derivation: str | None = None
    pricing_relevance: Literal["none", "low", "medium", "high"] = "medium"


class LatencyConstraint(BaseModel):
    name: str
    target: str
    latency_class: str
    source_text: str
    architecture_impact: str
    confidence: Literal["low", "medium", "high"] = "medium"


class ComplianceConstraint(BaseModel):
    name: str
    source_text: str
    jurisdiction: str | None = None
    requires_validation: bool = True
    architecture_impact: str


class ActionFlowUnderstanding(BaseModel):
    action_name: str
    action_type: str
    source_text: str
    impact_level: Literal["low", "medium", "high", "critical"]
    required_controls: list[str] = Field(default_factory=list)
    recommended_failure_behavior: Literal["block", "queue_for_review", "allow_with_audit", "rollback", "recommendation_only"] = "queue_for_review"


class FamilyTopologyJudgeReview(BaseModel):
    status: Literal["not_attempted", "accepted", "failed"] = "not_attempted"
    decision: Literal["accept", "downgrade", "reject", "needs_review", "not_attempted"] = "not_attempted"
    fit_confidence: Literal["low", "medium", "high"] = "low"
    accepted_families: list[str] = Field(default_factory=list)
    rejected_families: list[str] = Field(default_factory=list)
    rationale: str = ""
    risks: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    judge_model_id: str | None = None
    warnings: list[str] = Field(default_factory=list)


class DeepUseCaseUnderstanding(BaseModel):
    industry: str
    domain: str
    workload_families: list[str]
    excluded_patterns: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    extracted_metrics: list[UnderstandingMetric] = Field(default_factory=list)
    latency_constraints: list[LatencyConstraint] = Field(default_factory=list)
    compliance_constraints: list[ComplianceConstraint] = Field(default_factory=list)
    action_flows: list[ActionFlowUnderstanding] = Field(default_factory=list)
    deployment_posture: str = "public_cloud"
    architecture_implications: list[str] = Field(default_factory=list)
    pricing_implications: list[str] = Field(default_factory=list)
    dossier_research_questions: list[str] = Field(default_factory=list)
    critical_unknowns: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"
    concerns: list[str] = Field(default_factory=list)
    enhancement_status: str = "deterministic"
    family_topology_judge: FamilyTopologyJudgeReview | None = None


class DeepUseCaseUnderstandingService:
    async def build(self, raw_use_case: str, current_profile: UseCaseProfile | None = None, session_id: str | None = None) -> DeepUseCaseUnderstanding:
        profile = current_profile or profile_use_case(raw_use_case)
        deterministic = deterministic_understanding(raw_use_case, profile)
        result = await ModelRouter().complete(
            LLMTask(task_type=LLMTaskType.deep_use_case_understanding, session_id=session_id),
            [
                LLMMessage(role="system", content=_system_prompt()),
                LLMMessage(role="user", content=f"Raw use case:\n{raw_use_case}\n\nDeterministic extraction:\n{profile_to_metadata(profile)}"),
            ],
            response_schema=DeepUseCaseUnderstanding,
            temperature=0.1,
        )
        if result.validated and isinstance(result.parsed, DeepUseCaseUnderstanding):
            parsed = result.parsed
            _merge_deterministic_metrics(parsed, deterministic)
            _merge_deterministic_deployment_posture(parsed, deterministic)
            parsed.enhancement_status = f"{result.provider}_validated"
            parsed.family_topology_judge = await _review_family_topology_fit(raw_use_case, profile, parsed, session_id)
            return parsed
        deterministic.concerns.extend(result.warnings)
        deterministic.enhancement_status = "deterministic_fallback"
        return deterministic


def deterministic_understanding(raw_use_case: str, profile: UseCaseProfile | None = None) -> DeepUseCaseUnderstanding:
    profile = profile or profile_use_case(raw_use_case)
    metrics = extract_metrics(raw_use_case)
    extracted = []
    for bucket in (metrics.asset_counts, metrics.business_targets):
        for name, value in bucket.items():
            extracted.append(UnderstandingMetric(
                name=name,
                value=value.value,
                unit=value.unit,
                source_text=value.raw,
                confidence="high",
                derived=value.derived,
                derivation=value.raw if value.derived else None,
                pricing_relevance="high",
            ))
    existing_metric_names = {metric.name for metric in extracted}
    for metric in profile.metrics:
        if metric.label in existing_metric_names:
            continue
        extracted.append(UnderstandingMetric(
            name=metric.label,
            value=metric.value,
            unit=metric.unit,
            source_text=metric.raw,
            confidence="high",
            derived=False,
            derivation=None,
            pricing_relevance="high" if metric.kind in {"asset_count", "business_target"} else "medium",
        ))
        existing_metric_names.add(metric.label)
    latency_constraints = []
    if profile.latency_target:
        latency_constraints.append(LatencyConstraint(
            name="latency_target",
            target=profile.latency_target,
            latency_class=profile.latency_class or "unknown",
            source_text=profile.latency_target,
            architecture_impact="Constrains hot-path processing, inference placement, buffering, and failover design.",
            confidence="high",
        ))
    action_flows = [
        ActionFlowUnderstanding(
            action_name=action,
            action_type=_action_type(action),
            source_text=action,
            impact_level="high",
            required_controls=["policy_approval", "audit_trail", "operator_override", "rollback"],
            recommended_failure_behavior="queue_for_review",
        )
        for action in profile.actions
    ]
    compliance = [
        ComplianceConstraint(
            name=item,
            source_text=item,
            jurisdiction=None,
            requires_validation=True,
            architecture_impact="Requires validation with customer legal/compliance owners before production.",
        )
        for item in profile.capability_model
        if item.endswith("_compliance") or item in {"gxp_validation", "functional_safety", "data_residency"}
    ]
    return DeepUseCaseUnderstanding(
        industry=profile.domain or "unknown",
        domain=profile.domain or "unknown",
        workload_families=profile.workload_families,
        excluded_patterns=list(dict.fromkeys(profile.excluded_patterns + profile.excluded_families)),
        capabilities=list(dict.fromkeys(profile.capabilities + profile.capability_model)),
        extracted_metrics=extracted,
        latency_constraints=latency_constraints,
        compliance_constraints=compliance,
        action_flows=action_flows,
        deployment_posture=profile.deployment_posture[0] if profile.deployment_posture else "public_cloud",
        architecture_implications=_architecture_implications(profile),
        pricing_implications=_pricing_implications(profile),
        dossier_research_questions=[f"Validate workload drivers for {family}." for family in profile.workload_families[:3]],
        critical_unknowns=list((metrics.assumptions or [])[:5]),
        confidence=profile.confidence if profile.confidence in {"low", "medium", "high"} else "medium",
    )


async def _review_family_topology_fit(
    raw_use_case: str,
    deterministic_profile: UseCaseProfile,
    understanding: DeepUseCaseUnderstanding,
    session_id: str | None,
) -> FamilyTopologyJudgeReview:
    settings = get_settings()
    if not settings.enable_llm_judge:
        return FamilyTopologyJudgeReview(
            status="not_attempted",
            decision="not_attempted",
            rationale="LLM judge is disabled.",
            judge_model_id=settings.bedrock_judge_model_id,
        )
    if not settings.bedrock_judge_model_id:
        return FamilyTopologyJudgeReview(
            status="failed",
            decision="needs_review",
            rationale="LLM judge is enabled but ARCHWAY_BEDROCK_JUDGE_MODEL_ID is not configured.",
            judge_model_id=None,
            warnings=["judge_model_not_configured"],
        )
    try:
        result = await ModelRouter().complete(
            LLMTask(task_type=LLMTaskType.llm_judge_review, session_id=session_id, name="family_topology_fit", model_role="judge"),
            [
                LLMMessage(role="system", content=_judge_system_prompt()),
                LLMMessage(
                    role="user",
                    content=(
                        f"Raw use case:\n{raw_use_case}\n\n"
                        f"Deterministic extraction:\n{profile_to_metadata(deterministic_profile)}\n\n"
                        f"Main-model proposed understanding:\n{understanding.model_dump(mode='json', exclude={'family_topology_judge'})}\n\n"
                        "Review whether the proposed workload families/topology intent fits the use case. "
                        "Do not propose prices. Do not add AWS service facts unless directly implied by the use case. "
                        "If the family appears borrowed from telemetry/ML/streaming without evidence, downgrade or reject it."
                    ),
                ),
            ],
            response_schema=FamilyTopologyJudgeReview,
            temperature=0,
            timeout_seconds=settings.bedrock_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - judge failure must downgrade, not abort research
        return FamilyTopologyJudgeReview(
            status="failed",
            decision="needs_review",
            rationale="LLM judge invocation failed; LLM family authority must not be promoted by judge.",
            judge_model_id=settings.bedrock_judge_model_id,
            warnings=[f"judge_exception:{type(exc).__name__}"],
        )
    if result.validated and isinstance(result.parsed, FamilyTopologyJudgeReview):
        review = result.parsed
        review.status = "accepted"
        review.judge_model_id = result.model_id
        review.warnings.extend(result.warnings)
        return review
    return FamilyTopologyJudgeReview(
        status="failed",
        decision="needs_review",
        rationale="LLM judge response did not validate; LLM family authority must not be promoted by judge.",
        judge_model_id=result.model_id,
        warnings=result.warnings or ["judge_response_invalid"],
    )


def _merge_deterministic_metrics(parsed: DeepUseCaseUnderstanding, deterministic: DeepUseCaseUnderstanding) -> None:
    """Preserve deterministic numeric facts when a live model omits them."""
    existing = {metric.name for metric in parsed.extracted_metrics}
    for metric in deterministic.extracted_metrics:
        if metric.name not in existing:
            parsed.extracted_metrics.append(metric)
            existing.add(metric.name)


def _merge_deterministic_deployment_posture(parsed: DeepUseCaseUnderstanding, deterministic: DeepUseCaseUnderstanding) -> None:
    """Preserve deterministic edge/hybrid/sovereign posture over model defaults."""
    deterministic_posture = deterministic.deployment_posture
    if not deterministic_posture or deterministic_posture == "public_cloud":
        return
    if parsed.deployment_posture in {"", "unknown", "public_cloud", None}:
        parsed.deployment_posture = deterministic_posture
        note = f"Deployment posture reconciled to deterministic extraction: {deterministic_posture}."
        if note not in parsed.concerns:
            parsed.concerns.append(note)


def _action_type(action: str) -> str:
    if "dispatch" in action:
        return "dispatch"
    if "preposition" in action or "pre_position" in action:
        return "pre_position"
    if "block" in action:
        return "trade_block"
    if "route" in action:
        return "network_change"
    return "external_write"


def _architecture_implications(profile: UseCaseProfile) -> list[str]:
    items = []
    if profile.latency_class:
        items.append(f"Latency class {profile.latency_class} must shape hot-path design.")
    if "private_connectivity" in profile.capability_model or "hybrid" in profile.deployment_posture:
        items.append("Private connectivity and hybrid identity/network validation are production gates.")
    if profile.actions:
        items.append("Effectful actions require typed approval, guardrail, rollback, override, and audit controls.")
    return items


def _pricing_implications(profile: UseCaseProfile) -> list[str]:
    dimensions = []
    structured = profile.structured_metrics or {}
    for bucket in ("asset_counts", "business_targets"):
        dimensions.extend((structured.get(bucket) or {}).keys())
    return [f"Pricing must apply extracted driver: {item}" for item in dimensions[:8]]


def _system_prompt() -> str:
    return (
        "You are Archway's AWS solution-understanding reviewer. Return JSON only. "
        "Use only the provided use case and deterministic extraction. Do not invent prices, AWS facts, or compliance. "
        "If unsure, mark requires_validation or add a concern."
    )


def _judge_system_prompt() -> str:
    return (
        "You are Archway's independent topology-fit judge. Return JSON only. "
        "Your job is not to design a new architecture. Judge whether the main model's "
        "workload families and topology intent fit the user's stated use case. "
        "Accept only when the proposed family is directly supported by the use case. "
        "Downgrade or reject borrowed telemetry, ML, streaming, healthcare, finance, or other domain topology "
        "when the use case does not provide evidence for it. Prefer needs_review over false confidence."
    )
