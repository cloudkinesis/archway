from __future__ import annotations

import json
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.services.agentic.contracts import AgentDecision
from app.services.agentic.live_audit import LiveCallAudit
from app.services.agentic.live_bedrock_harness import LiveRunContext, live_call
from app.services.dossier_manifest import stable_json_hash
from app.services.llm.base import LLMMessage, LLMTaskType

ResearchClaimKind = Literal[
    "aws_docs",
    "aws_pricing",
    "architecture_rationale",
    "compliance",
    "security",
    "operational",
    "unknown",
]
ResearchSourceType = Literal["aws_docs", "aws_pricing", "catalog", "user_input", "deterministic_ledger", "model", "unknown"]
ResearchPriority = Literal["high", "medium", "low"]
ResearchFindingStatus = Literal["grounded", "gap", "conflict", "unsupported", "assumption", "needs_human_review", "skipped"]
ResearchConfidence = Literal["high", "medium", "low", "unknown"]
ResearchEvidenceStance = Literal["supports", "contradicts", "unknown"]


class ResearchQuestion(BaseModel):
    question_id: str
    claim_kind: ResearchClaimKind
    question: str
    required_source_type: ResearchSourceType
    priority: ResearchPriority
    reason: str


class ResearchQueryPlan(BaseModel):
    lane: Literal["research"] = "research"
    run_id: str
    questions: list[ResearchQuestion] = Field(default_factory=list)
    source_requirements: list[ResearchSourceType] = Field(default_factory=list)
    created_from_signals: list[str] = Field(default_factory=list)

    @property
    def deterministic_hash(self) -> str:
        return stable_json_hash(self.model_dump(mode="json"))


class ResearchEvidenceItem(BaseModel):
    evidence_id: str
    source_type: ResearchSourceType
    title: str
    citation: str | None = None
    url: str | None = None
    excerpt: str | None = None
    retrieved_at: str | None = None
    claim_kinds: list[ResearchClaimKind] = Field(default_factory=list)
    confidence_label: ResearchConfidence = "unknown"
    stance: ResearchEvidenceStance = "supports"


class ResearchFinding(BaseModel):
    finding_id: str
    question_id: str | None = None
    status: ResearchFindingStatus
    claim_kind: ResearchClaimKind
    statement: str
    evidence_refs: list[str] = Field(default_factory=list)
    provenance: ResearchSourceType | Literal["model_proposed"] = "deterministic_ledger"


class ResearchSynthesis(BaseModel):
    synthesis_id: str
    summary: str
    findings: list[ResearchFinding] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    provenance: Literal["deterministic", "fixture", "model_proposed", "skipped"] = "deterministic"


class ResearchAgentTrace(BaseModel):
    run_id: str
    enabled: bool = False
    provider: str
    query_plan: ResearchQueryPlan
    evidence_items: list[ResearchEvidenceItem] = Field(default_factory=list)
    synthesis: ResearchSynthesis
    decisions: list[AgentDecision] = Field(default_factory=list)
    prompt_hash: str | None = None
    response_hash: str | None = None
    live_call: LiveCallAudit | None = None
    input_hash: str
    output_hash: str


class ResearchProvider(Protocol):
    provider_name: str

    def plan_queries(self, input_context: dict[str, Any]) -> ResearchQueryPlan: ...

    def retrieve(self, plan: ResearchQueryPlan) -> list[ResearchEvidenceItem]: ...

    def synthesize(self, plan: ResearchQueryPlan, evidence_items: list[ResearchEvidenceItem]) -> ResearchSynthesis: ...


class DisabledResearchProvider:
    provider_name = "disabled"

    def trace(self, input_context: dict[str, Any]) -> ResearchAgentTrace:
        input_hash = stable_json_hash(input_context)
        run_id = "research_run_" + input_hash.removeprefix("sha256:")[:12]
        plan = ResearchQueryPlan(run_id=run_id, created_from_signals=["agentic_research_disabled"])
        synthesis = ResearchSynthesis(
            synthesis_id="synth_" + input_hash.removeprefix("sha256:")[:12],
            summary="Agentic research lane is disabled by default; deterministic research output remains authoritative.",
            findings=[
                ResearchFinding(
                    finding_id="research_disabled",
                    status="skipped",
                    claim_kind="unknown",
                    statement="ARCHWAY_ENABLE_AGENTIC_RESEARCH is false; no provider was invoked.",
                    provenance="deterministic_ledger",
                )
            ],
            provenance="skipped",
        )
        output_hash = stable_json_hash({"plan": plan.model_dump(mode="json"), "synthesis": synthesis.model_dump(mode="json")})
        return ResearchAgentTrace(
            run_id=run_id,
            enabled=False,
            provider=self.provider_name,
            query_plan=plan,
            synthesis=synthesis,
            decisions=[
                AgentDecision(
                    proposal_id=run_id,
                    decision="rejected",
                    reason="Agentic research is disabled by feature flag.",
                    deterministic_gate="ARCHWAY_ENABLE_AGENTIC_RESEARCH",
                )
            ],
            input_hash=input_hash,
            output_hash=output_hash,
        )


class DeterministicFixtureResearchProvider:
    provider_name = "deterministic_fixture"

    def plan_queries(self, input_context: dict[str, Any]) -> ResearchQueryPlan:
        input_hash = stable_json_hash(input_context)
        run_id = "research_run_" + input_hash.removeprefix("sha256:")[:12]
        services = sorted({str(item) for item in input_context.get("services", []) if item})
        questions: list[ResearchQuestion] = []
        for idx, service in enumerate(services[:4], start=1):
            questions.append(ResearchQuestion(
                question_id=f"rq_service_{idx}",
                claim_kind="aws_docs",
                question=f"Which AWS documentation supports the use of {service} in this workload?",
                required_source_type="aws_docs",
                priority="high",
                reason="AWS service capability claims require AWS Docs evidence.",
            ))
        if input_context.get("pricing_evidence_gap"):
            questions.append(ResearchQuestion(
                question_id="rq_pricing_1",
                claim_kind="aws_pricing",
                question="Which AWS Pricing source supports the pricing dimensions used in this package?",
                required_source_type="aws_pricing",
                priority="high",
                reason="AWS pricing claims require AWS Pricing evidence.",
            ))
        if input_context.get("compliance_context"):
            questions.append(ResearchQuestion(
                question_id="rq_compliance_1",
                claim_kind="compliance",
                question="Which compliance or security assumptions still need customer or authoritative evidence?",
                required_source_type="user_input",
                priority="medium",
                reason="Compliance posture should not be invented by an agent.",
            ))
        questions = sorted(questions, key=lambda question: question.question_id)
        requirements = sorted({question.required_source_type for question in questions})
        return ResearchQueryPlan(
            run_id=run_id,
            questions=questions,
            source_requirements=requirements,
            created_from_signals=sorted(set(input_context.get("signals", []) or ["use_case", "architecture", "evidence_quality"])),
        )

    def retrieve(self, plan: ResearchQueryPlan) -> list[ResearchEvidenceItem]:
        items: list[ResearchEvidenceItem] = []
        for question in plan.questions:
            if question.required_source_type in {"aws_docs", "aws_pricing", "catalog", "user_input", "deterministic_ledger"}:
                items.append(ResearchEvidenceItem(
                    evidence_id=f"ev_{question.question_id}",
                    source_type=question.required_source_type,
                    title=f"Fixture evidence for {question.question_id}",
                    citation=f"fixture:{question.question_id}",
                    excerpt=f"Deterministic fixture evidence for: {question.question}",
                    claim_kinds=[question.claim_kind],
                    confidence_label="medium",
                ))
        return items

    def synthesize(self, plan: ResearchQueryPlan, evidence_items: list[ResearchEvidenceItem]) -> ResearchSynthesis:
        findings: list[ResearchFinding] = []
        gaps: list[str] = []
        unsupported: list[str] = []
        conflicts: list[str] = []
        for question in plan.questions:
            relevant_evidence = [
                item for item in evidence_items
                if question.claim_kind in item.claim_kinds
            ]
            status = classify_research_status(question.claim_kind, question.required_source_type, [
                item for item in relevant_evidence
            ])
            refs = sorted({
                item.evidence_id
                for item in relevant_evidence
                if item.source_type == question.required_source_type
            })
            if status == "conflict":
                conflicts.append(f"{question.question_id} has conflicting {question.required_source_type} evidence.")
            if status != "grounded":
                message = f"{question.question_id} lacks {question.required_source_type} evidence."
                gaps.append(message)
                unsupported.append(question.question)
            findings.append(ResearchFinding(
                finding_id=f"finding_{question.question_id}",
                question_id=question.question_id,
                status=status,
                claim_kind=question.claim_kind,
                statement=question.question,
                evidence_refs=refs,
                provenance=question.required_source_type if refs else "deterministic_ledger",
            ))
        evidence_refs = sorted({ref for finding in findings for ref in finding.evidence_refs})
        return ResearchSynthesis(
            synthesis_id="synth_" + plan.deterministic_hash.removeprefix("sha256:")[:12],
            summary="Deterministic fixture research synthesis. Use for tests only; not client-facing authority.",
            findings=findings,
            gaps=gaps,
            conflicts=conflicts,
            evidence_refs=evidence_refs,
            unsupported_claims=unsupported,
            provenance="fixture",
        )


class LiveResearchProvider:
    provider_name = "bedrock"

    def __init__(self, *, session_id: str | None = None, run_context: LiveRunContext | None = None, sensitivity_text: str | None = None):
        self.session_id = session_id
        self.run_context = run_context
        self.sensitivity_text = sensitivity_text
        self.input_context: dict[str, Any] = {}
        self.last_call: LiveCallAudit | None = None

    def plan_queries(self, input_context: dict[str, Any]) -> ResearchQueryPlan:
        self.input_context = input_context
        return DeterministicFixtureResearchProvider().plan_queries(input_context)

    def retrieve(self, plan: ResearchQueryPlan) -> list[ResearchEvidenceItem]:
        return []

    def synthesize(self, plan: ResearchQueryPlan, evidence_items: list[ResearchEvidenceItem]) -> ResearchSynthesis:
        messages = [
            LLMMessage(role="system", content=(
                "You are Archway's live research synthesizer. Return JSON only. "
                "Use only the supplied deterministic context. Do not claim fresh AWS Docs or Pricing retrieval. "
                "Mark fresh-evidence requirements as gaps."
            )),
            LLMMessage(role="user", content=json.dumps({"plan": plan.model_dump(mode="json"), "context": self.input_context}, default=str)[:22000]),
        ]
        result = live_call(
            LLMTaskType.live_research_synthesis,
            messages,
            ResearchSynthesis,
            session_id=self.session_id,
            lane="research",
            run_context=self.run_context,
            sensitivity_text=self.sensitivity_text,
        )
        self.last_call = result.audit
        if isinstance(result.parsed, ResearchSynthesis):
            synthesis = result.parsed
            return synthesis.model_copy(update={"provenance": "model_proposed"})
        return ResearchSynthesis(
            synthesis_id="synth_" + plan.deterministic_hash.removeprefix("sha256:")[:12],
            summary="Live research synthesis was not usable; deterministic context remains authoritative.",
            findings=[
                ResearchFinding(
                    finding_id="live_research_unavailable",
                    status="gap",
                    claim_kind="unknown",
                    statement=result.audit.error_message or result.audit.skip_reason or "Live research synthesis did not complete.",
                    provenance="model_proposed",
                )
            ],
            gaps=[result.audit.error_message or result.audit.skip_reason or "Live research synthesis unavailable."],
            provenance="model_proposed",
        )


def classify_research_status(
    claim_kind: ResearchClaimKind,
    required_source_type: ResearchSourceType,
    evidence_items: list[ResearchEvidenceItem],
) -> ResearchFindingStatus:
    if any(item.source_type == required_source_type and item.stance == "contradicts" for item in evidence_items):
        return "conflict"
    if claim_kind == "aws_docs" and not any(item.source_type == "aws_docs" for item in evidence_items):
        return "gap"
    if claim_kind == "aws_pricing" and not any(item.source_type == "aws_pricing" for item in evidence_items):
        return "gap"
    if required_source_type in {"aws_docs", "aws_pricing"} and not any(item.source_type == required_source_type for item in evidence_items):
        return "unsupported"
    if not evidence_items:
        return "needs_human_review"
    return "grounded"


def build_research_input_context(
    *,
    brief: dict | None,
    report: dict | None,
    pricing: dict | None,
    architectures: list | None,
    diagrams: list | None,
    reviewer_findings: list | None = None,
) -> dict[str, Any]:
    services = sorted({
        str(component.get("service") or component.get("name"))
        for spec in architectures or []
        for component in (spec.get("components") or spec.get("selected_services") or [])
        if isinstance(component, dict) and (component.get("service") or component.get("name"))
    })
    metadata = (report or {}).get("metadata") or {}
    evidence_quality = metadata.get("evidence_quality") or {}
    closure = ((pricing or {}).get("metadata") or {}).get("pricing_driver_closure") or {}
    profile = (brief or {}).get("use_case_profile") or {}
    return {
        "use_case_title": (brief or {}).get("title") or (report or {}).get("title"),
        "domain": profile.get("domain"),
        "workload_families": profile.get("workload_families") or [],
        "services": services,
        "pricing_evidence_gap": not bool(evidence_quality.get("aws_pricing_available")),
        "docs_evidence_gap": not bool(evidence_quality.get("aws_docs_available")),
        "compliance_context": bool(profile.get("compliance") or profile.get("regulatory_context")),
        "readiness_reasons": ((metadata.get("customer_readiness") or {}).get("reasons") or []),
        "pricing_missing_drivers": closure.get("missing_drivers") or [],
        "diagram_count": sum(len(gallery.get("diagrams") or []) for gallery in diagrams or [] if isinstance(gallery, dict)),
        "reviewer_findings": [_finding_id(item) for item in reviewer_findings or []],
        "signals": ["brief", "research_report", "pricing", "architecture", "diagrams", "reviewer"],
    }


def build_research_agent_trace(
    *,
    settings: Settings,
    input_context: dict[str, Any],
    provider: ResearchProvider | None = None,
    live_run_context: LiveRunContext | None = None,
    session_id: str | None = None,
    sensitivity_text: str | None = None,
) -> ResearchAgentTrace:
    if not settings.enable_agentic_research:
        return DisabledResearchProvider().trace(input_context)
    if provider is None and settings.agentic_mode == "live_demo":
        provider = LiveResearchProvider(session_id=session_id, run_context=live_run_context, sensitivity_text=sensitivity_text)
    provider = provider or DeterministicFixtureResearchProvider()
    plan = provider.plan_queries(input_context)
    evidence = provider.retrieve(plan)
    synthesis = provider.synthesize(plan, evidence)
    input_hash = stable_json_hash(input_context)
    output_hash = stable_json_hash({
        "plan": plan.model_dump(mode="json"),
        "evidence_items": [item.model_dump(mode="json") for item in evidence],
        "synthesis": synthesis.model_dump(mode="json"),
    })
    live_audit = getattr(provider, "last_call", None)
    return ResearchAgentTrace(
        run_id=plan.run_id,
        enabled=True,
        provider=live_audit.provider if live_audit else provider.provider_name,
        query_plan=plan,
        evidence_items=evidence,
        synthesis=synthesis,
        decisions=[
            AgentDecision(
                proposal_id=plan.run_id,
                decision="downgraded",
                reason="Research agent output is audit/raw-only and cannot promote readiness or client authority.",
                deterministic_gate="D21 research audit-only lane",
            )
        ],
        prompt_hash=live_audit.prompt_hash if live_audit else None,
        response_hash=live_audit.response_hash if live_audit else None,
        live_call=live_audit,
        input_hash=input_hash,
        output_hash=output_hash,
    )


def research_summary_markdown(trace: ResearchAgentTrace) -> str:
    lines = [
        "# D21 Agentic Research Supplement",
        "",
        "This audit-only supplement records the D21 research lane trace. It is not client-facing authority and does not change readiness, pricing, architecture, or diagram truth.",
        "",
        f"**Enabled:** {'Yes' if trace.enabled else 'No'}",
        f"**Provider:** {trace.provider}",
        f"**Run ID:** `{trace.run_id}`",
        f"**Input hash:** `{trace.input_hash}`",
        f"**Output hash:** `{trace.output_hash}`",
        "",
        "## Query Plan",
        "",
    ]
    if trace.query_plan.questions:
        for question in trace.query_plan.questions:
            lines.append(f"- **{question.question_id}** ({question.claim_kind}, requires `{question.required_source_type}`): {question.question}")
    else:
        lines.append("- No questions planned.")
    lines.extend(["", "## Findings", ""])
    if trace.synthesis.findings:
        for finding in trace.synthesis.findings:
            refs = ", ".join(finding.evidence_refs) if finding.evidence_refs else "none"
            lines.append(f"- **{finding.status}** `{finding.claim_kind}` - {finding.statement} (evidence: {refs})")
    else:
        lines.append("- No findings.")
    lines.extend(["", "## Gaps / Unsupported Claims", ""])
    for gap in trace.synthesis.gaps:
        lines.append(f"- Gap: {gap}")
    for claim in trace.synthesis.unsupported_claims:
        lines.append(f"- Unsupported: {claim}")
    if not trace.synthesis.gaps and not trace.synthesis.unsupported_claims:
        lines.append("- None recorded.")
    lines.extend(["", "Research-agent output remains raw/audit-only in this branch.", ""])
    return "\n".join(lines)


def _finding_id(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("finding_id") or item.get("id") or item.get("rule_id") or item)
    return str(getattr(item, "finding_id", None) or getattr(item, "id", None) or item)
