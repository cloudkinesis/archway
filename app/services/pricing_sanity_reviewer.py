from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models.domain import PricingAnalysis
from app.services.llm.base import LLMMessage, LLMTask, LLMTaskType
from app.services.llm.model_router import ModelRouter
from app.services.understanding.deep_use_case_understanding import DeepUseCaseUnderstanding


class PricingSanityFinding(BaseModel):
    severity: Literal["info", "warning", "critical"]
    issue: str
    evidence_from_use_case: str
    impacted_pricing_driver: str
    recommended_fix: str


class PricingSanityReview(BaseModel):
    passed: bool
    findings: list[PricingSanityFinding] = Field(default_factory=list)
    pricing_can_be_displayed_as_headline: bool = True
    pricing_status: Literal["sku_traceable", "directional", "invalid_placeholder", "not_enough_information"] = "directional"
    enhancement_status: str = "deterministic"


class PricingSanityReviewer:
    async def review(self, raw_use_case: str, understanding: DeepUseCaseUnderstanding, pricing: PricingAnalysis, session_id: str | None = None) -> PricingSanityReview:
        deterministic = deterministic_pricing_sanity(raw_use_case, understanding, pricing)
        result = await ModelRouter().complete(
            LLMTask(task_type=LLMTaskType.metric_sanity_review, session_id=session_id),
            [
                LLMMessage(role="system", content="Review pricing-driver semantic fit. Return JSON only. Do not calculate prices."),
                LLMMessage(role="user", content=f"Use case:\n{raw_use_case}\n\nUnderstanding:\n{understanding.model_dump(mode='json')}\n\nPricing:\n{pricing.model_dump(mode='json')}"),
            ],
            response_schema=PricingSanityReview,
            temperature=0.1,
        )
        if result.validated and isinstance(result.parsed, PricingSanityReview):
            parsed = result.parsed
            parsed.findings = deterministic.findings + parsed.findings
            parsed.findings = _drop_stale_confirmed_unknown_findings(parsed.findings, pricing)
            parsed.passed = deterministic.passed and parsed.passed
            if any(item.severity == "critical" for item in parsed.findings):
                parsed.passed = False
            if not deterministic.pricing_can_be_displayed_as_headline:
                parsed.pricing_can_be_displayed_as_headline = False
                parsed.pricing_status = deterministic.pricing_status
            parsed.enhancement_status = f"{result.provider}_validated"
            return parsed
        deterministic.enhancement_status = "deterministic_fallback"
        deterministic.findings.extend(PricingSanityFinding(severity="info", issue=warning, evidence_from_use_case="LLM provider", impacted_pricing_driver="n/a", recommended_fix="Configure Bedrock for premium semantic review.") for warning in result.warnings)
        return deterministic


def deterministic_pricing_sanity(raw_use_case: str, understanding: DeepUseCaseUnderstanding, pricing: PricingAnalysis) -> PricingSanityReview:
    findings: list[PricingSanityFinding] = []
    metadata = pricing.metadata or {}
    if metadata.get("status") == "invalid_extracted_scale_not_applied":
        findings.append(PricingSanityFinding(
            severity="critical",
            issue="Pricing drivers ignore explicit workload scale.",
            evidence_from_use_case=metadata.get("reason", raw_use_case[:200]),
            impacted_pricing_driver="asset_count/daily_event_volume",
            recommended_fix="Apply extracted metrics before presenting a headline estimate.",
        ))
    if metadata.get("status") == "directional_only_missing_core_compute_drivers":
        findings.append(PricingSanityFinding(
            severity="critical",
            issue="Core compute and SKU drivers remain unknown for this workload.",
            evidence_from_use_case=metadata.get("reason", raw_use_case[:200]),
            impacted_pricing_driver="risk_compute_jobs/hpc_compute_hours/risk_grid_nodes/shared_storage_throughput",
            recommended_fix="Treat pricing as internal directional only until simulation count, node/runtime profile, storage throughput, and reporting scan volumes are confirmed.",
        ))
    if any(metric.pricing_relevance == "high" for metric in understanding.extracted_metrics) and metadata.get("scale_applied") is False:
        findings.append(PricingSanityFinding(
            severity="critical",
            issue="High-relevance extracted metrics were not applied.",
            evidence_from_use_case=", ".join(metric.name for metric in understanding.extracted_metrics[:6]),
            impacted_pricing_driver="pricing model",
            recommended_fix="Regenerate pricing drivers from merged understanding.",
        ))
    if understanding.extracted_metrics and metadata.get("pricing_driver_family") == "generic_directional":
        findings.append(PricingSanityFinding(
            severity="critical",
            issue="Pricing used a generic driver family despite explicit metrics.",
            evidence_from_use_case=", ".join(metric.name for metric in understanding.extracted_metrics[:8]),
            impacted_pricing_driver="pricing_driver_family",
            recommended_fix="Select a workload-specific pricing driver family or mark pricing as not headline-safe.",
        ))
    if metadata.get("pricing_can_be_displayed_as_headline") is False:
        findings.append(PricingSanityFinding(
            severity="warning",
            issue="Pricing metadata already marks the estimate as not headline-safe.",
            evidence_from_use_case=metadata.get("reason", raw_use_case[:200]),
            impacted_pricing_driver="headline_display",
            recommended_fix="Display as directional placeholder only.",
        ))
    status = "invalid_placeholder" if any(item.severity == "critical" for item in findings) else "directional"
    return PricingSanityReview(
        passed=not any(item.severity == "critical" for item in findings),
        findings=findings,
        pricing_can_be_displayed_as_headline=status != "invalid_placeholder",
        pricing_status=status,
    )


def _drop_stale_confirmed_unknown_findings(findings: list[PricingSanityFinding], pricing: PricingAnalysis) -> list[PricingSanityFinding]:
    metadata = pricing.metadata or {}
    facts_payload = metadata.get("canonical_facts") or {}
    known_fact_names = {
        str(item.get("name", "")).lower()
        for item in facts_payload.get("facts", [])
        if isinstance(item, dict) and item.get("name")
    }
    if not known_fact_names:
        return findings
    current_unknowns = {str(item).lower() for item in pricing.unknown_variables}
    filtered: list[PricingSanityFinding] = []
    for item in findings:
        haystack = " ".join([
            item.issue,
            item.evidence_from_use_case,
            item.impacted_pricing_driver,
            item.recommended_fix,
        ]).lower()
        is_confirmed_unknown_finding = "confirmed fact" in haystack and "unknown" in haystack
        if is_confirmed_unknown_finding:
            mentioned_facts = {name for name in known_fact_names if name and name in haystack}
            if mentioned_facts and not (mentioned_facts & current_unknowns):
                continue
        filtered.append(item)
    return filtered
