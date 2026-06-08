from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.services.llm.base import LLMMessage, LLMTask, LLMTaskType
from app.services.llm.model_router import ModelRouter


class DigestSourceChip(BaseModel):
    title: str
    source_type: str
    confidence: str


class ResearchUiDigest(BaseModel):
    headline: str
    decision: str
    one_minute_read: list[str] = Field(default_factory=list)
    aws_direction: list[str] = Field(default_factory=list)
    governance_boundaries: list[str] = Field(default_factory=list)
    pricing_snapshot: str
    pricing_caveats: list[str] = Field(default_factory=list)
    top_risks: list[str] = Field(default_factory=list)
    validate_next: list[str] = Field(default_factory=list)
    source_chips: list[DigestSourceChip] = Field(default_factory=list)
    generated_by: str = "deterministic"
    warnings: list[str] = Field(default_factory=list)


async def build_research_ui_digest(session_id: str, report: dict | None, narrative: dict | None) -> ResearchUiDigest | None:
    if not report:
        return None
    fallback = deterministic_research_ui_digest(report)
    payload = _digest_prompt_payload(report, narrative)
    result = await ModelRouter().complete(
        LLMTask(task_type=LLMTaskType.executive_summary_writing, session_id=session_id, name="research_ui_digest"),
        [
            LLMMessage(
                role="system",
                content=(
                    "You compress an AWS architecture research dossier into calm UI copy. "
                    "Use only the supplied JSON. Do not invent services, prices, citations, guarantees, or requirements. "
                    "Preserve safety, pricing, evidence, and approval caveats. Avoid internal IDs. "
                    "Write short bullets that reduce cognitive load for an architecture reviewer."
                ),
            ),
            LLMMessage(role="user", content=json.dumps(payload, default=str)[:22000]),
        ],
        response_schema=ResearchUiDigest,
        temperature=0,
        max_tokens=1800,
        timeout_seconds=40,
    )
    if result.validated and isinstance(result.parsed, ResearchUiDigest):
        digest = result.parsed
        digest.generated_by = result.model_id or result.provider
        digest.source_chips = fallback.source_chips
        digest.warnings = [*digest.warnings, *result.warnings]
        return _sanitize_digest(digest, fallback)
    fallback.warnings.extend(result.warnings)
    return fallback


def deterministic_research_ui_digest(report: dict) -> ResearchUiDigest:
    pricing = report.get("pricing_analysis") or {}
    metadata = report.get("metadata") or {}
    readiness = metadata.get("customer_readiness") or {}
    services = report.get("aws_service_recommendations") or []
    risks = report.get("risks") or []
    unknowns = pricing.get("unknown_variables") or []
    evidence = report.get("evidence_items") or []
    source_chips = [
        DigestSourceChip(
            title=str(item.get("title") or "Source")[:90],
            source_type=str(item.get("source_type") or "unknown"),
            confidence=str(item.get("confidence") or "unknown"),
        )
        for item in evidence[:6]
    ]
    service_names = [str(item.get("service")) for item in services[:5] if item.get("service")]
    decision = str(report.get("proceed_recommendation") or "Proceed with caution").replace("_", " ").title()
    expected = pricing.get("expected_monthly_usd")
    low = pricing.get("low_monthly_usd")
    high = pricing.get("high_monthly_usd")
    pricing_snapshot = (
        f"Directional estimate: expected ${expected}, range ${low}-${high}. "
        "Treat as scenario-level until workload drivers and SKU quantities are validated."
    )
    return ResearchUiDigest(
        headline=_calm_headline(report),
        decision=decision,
        one_minute_read=[
            _first_sentence(str(report.get("use_case_interpretation") or "Use case interpreted from user input."), 170),
            f"Primary AWS shape: {', '.join(service_names) if service_names else 'service recommendations require review'}.",
            f"Customer readiness: {str(readiness.get('status') or 'unknown').replace('_', ' ')}.",
        ],
        aws_direction=[
            _first_sentence(str(report.get("recommended_poc") or "Start with a scoped POC."), 160),
            _first_sentence(str(report.get("recommended_production_direction") or "Harden for production after validation."), 180),
        ],
        governance_boundaries=_governance_bullets(report),
        pricing_snapshot=pricing_snapshot,
        pricing_caveats=[_clean_text(item, 150) for item in unknowns[:4]] or ["Pricing is directional until workload-specific drivers are confirmed."],
        top_risks=[f"{str(item.get('severity', 'risk')).title()}: {_clean_text(item.get('title', 'Risk'), 120)}" for item in risks[:4]],
        validate_next=_validation_bullets(report),
        source_chips=source_chips,
    )


def _digest_prompt_payload(report: dict, narrative: dict | None) -> dict[str, Any]:
    pricing = report.get("pricing_analysis") or {}
    metadata = report.get("metadata") or {}
    return {
        "executive_verdict": report.get("executive_verdict"),
        "proceed_recommendation": report.get("proceed_recommendation"),
        "use_case_interpretation": _clean_text(report.get("use_case_interpretation"), 1800),
        "recommended_poc": report.get("recommended_poc"),
        "recommended_production_direction": report.get("recommended_production_direction"),
        "services": [
            {
                "service": item.get("service"),
                "purpose": item.get("purpose"),
                "rationale": _clean_text(item.get("rationale"), 500),
                "alternatives": item.get("alternatives_considered") or [],
            }
            for item in (report.get("aws_service_recommendations") or [])[:10]
        ],
        "pricing": {
            "region": pricing.get("region"),
            "low": pricing.get("low_monthly_usd"),
            "expected": pricing.get("expected_monthly_usd"),
            "high": pricing.get("high_monthly_usd"),
            "maturity": (pricing.get("metadata") or {}).get("pricing_maturity"),
            "unknown_variables": pricing.get("unknown_variables") or [],
            "drivers": pricing.get("main_cost_drivers") or [],
        },
        "risks": report.get("risks") or [],
        "customer_readiness": metadata.get("customer_readiness") or {},
        "competitor_scan": metadata.get("competitor_scan") or {},
        "citation_coverage": report.get("citation_coverage") or {},
        "narrative_sections": [
            {"id": item.get("id"), "title": item.get("title"), "markdown": _clean_text(item.get("markdown"), 1400)}
            for item in ((narrative or {}).get("sections") or [])
            if item.get("id") in {"executive_verdict", "architecture_recommendation", "pricing_analysis", "validation_plan"}
        ],
    }


def _sanitize_digest(digest: ResearchUiDigest, fallback: ResearchUiDigest) -> ResearchUiDigest:
    if "ev_" in digest.model_dump_json():
        digest.warnings.append("LLM digest contained internal evidence IDs; deterministic digest used instead.")
        return fallback
    return ResearchUiDigest(
        headline=(_clean_text(digest.headline, 150) if "_" not in digest.headline and len(digest.headline) <= 150 else fallback.headline) or fallback.headline,
        decision=_clean_text(digest.decision, 80).replace("_", " ").title() or fallback.decision,
        one_minute_read=[_clean_text(item, 180) for item in digest.one_minute_read[:4] if _clean_text(item, 180)] or fallback.one_minute_read,
        aws_direction=[_clean_text(item, 170) for item in digest.aws_direction[:4] if _clean_text(item, 170)] or fallback.aws_direction,
        governance_boundaries=[_clean_text(item, 160) for item in digest.governance_boundaries[:5] if _clean_text(item, 160)] or fallback.governance_boundaries,
        pricing_snapshot=_clean_text(digest.pricing_snapshot, 190) or fallback.pricing_snapshot,
        pricing_caveats=[_clean_text(item, 160) for item in digest.pricing_caveats[:4] if _clean_text(item, 160)] or fallback.pricing_caveats,
        top_risks=[_clean_text(item, 150) for item in digest.top_risks[:4] if _clean_text(item, 150)] or fallback.top_risks,
        validate_next=[_clean_text(item, 150) for item in digest.validate_next[:5] if _clean_text(item, 150)] or fallback.validate_next,
        source_chips=fallback.source_chips,
        generated_by=digest.generated_by,
        warnings=digest.warnings,
    )


def _governance_bullets(report: dict) -> list[str]:
    text = " ".join([
        str(report.get("use_case_interpretation") or ""),
        str(report.get("recommended_production_direction") or ""),
        " ".join(str(item.get("mitigation") or "") for item in report.get("risks") or []),
    ]).lower()
    bullets = []
    if any(token in text for token in ("approval", "human", "authorized", "policy")):
        bullets.append("Approval is required for high-impact writes or operational changes.")
    if any(token in text for token in ("audit", "logging", "trail")):
        bullets.append("Audit trail, logging, and traceability remain mandatory controls.")
    if any(token in text for token in ("rollback", "idempotent", "dead-letter")):
        bullets.append("Workflow actions need retry, rollback, and idempotency controls.")
    return bullets or ["Governance boundaries must be validated before customer-ready status."]


def _calm_headline(report: dict) -> str:
    metadata = report.get("metadata") or {}
    readiness = metadata.get("customer_readiness") or {}
    status = str(readiness.get("status") or "directional").replace("_", " ")
    interpretation = str(report.get("use_case_interpretation") or "").lower()
    if "hospital" in interpretation or "clinical" in interpretation or "patient" in interpretation:
        subject = "governed AWS healthcare operations POC"
    elif "utility" in interpretation or "grid" in interpretation or "transformer" in interpretation:
        subject = "governed AWS utility operations POC"
    elif "bank" in interpretation or "risk" in interpretation or "fraud" in interpretation:
        subject = "governed AWS financial services POC"
    else:
        subject = "governed AWS solution POC"
    return f"Proceed with caution: build a {subject}; validate evidence, pricing, and approval controls before procurement. Current readiness is {status}."


def _validation_bullets(report: dict) -> list[str]:
    pricing = report.get("pricing_analysis") or {}
    risks = report.get("risks") or []
    items = [str(item) for item in (pricing.get("unknown_variables") or [])[:3]]
    items.extend(str(item.get("mitigation") or item.get("title")) for item in risks[:3])
    cleaned = [_clean_text(item, 150) for item in items if _clean_text(item, 150)]
    return cleaned[:5] or ["Validate workload volumes, security posture, and pricing drivers."]


def _first_sentence(value: str, limit: int) -> str:
    value = _clean_text(value, limit * 2)
    for marker in (". ", "; "):
        if marker in value:
            return _clean_text(value.split(marker, 1)[0] + ".", limit)
    return _clean_text(value, limit)


def _clean_text(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").replace("\n", " ").split())
    text = text.replace("OPEN_VALIDATION_ITEM:", "").replace("No Reason:", "").replace("_", " ")
    if len(text) <= limit:
        return text.rstrip()
    return text[: max(0, limit - 1)].rstrip(" ,.;:-") + "…"
