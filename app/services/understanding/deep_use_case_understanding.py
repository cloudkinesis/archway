from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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
            parsed.enhancement_status = f"{result.provider}_validated"
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


def _merge_deterministic_metrics(parsed: DeepUseCaseUnderstanding, deterministic: DeepUseCaseUnderstanding) -> None:
    """Preserve deterministic numeric facts when a live model omits them."""
    existing = {metric.name for metric in parsed.extracted_metrics}
    for metric in deterministic.extracted_metrics:
        if metric.name not in existing:
            parsed.extracted_metrics.append(metric)
            existing.add(metric.name)


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
