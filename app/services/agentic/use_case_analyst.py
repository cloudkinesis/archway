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

AnalystConfidence = Literal["low", "medium", "high"]
AnalystProvenance = Literal["deterministic", "catalog_backed", "model_proposed", "user_input", "derived"]
AnalystAcceptedStatus = Literal["proposed", "accepted", "downgraded", "rejected", "conflict", "assumed"]
AnalystFindingSeverity = Literal["blocker", "warning", "advisory", "info"]


class AnalystCandidate(BaseModel):
    key: str
    label: str
    confidence_label: AnalystConfidence = "medium"
    provenance: AnalystProvenance = "model_proposed"
    evidence_refs: list[str] = Field(default_factory=list)
    reason: str
    accepted_status: AnalystAcceptedStatus = "proposed"


class AnalystFinding(BaseModel):
    severity: AnalystFindingSeverity
    rule_id: str
    message: str
    target: str | None = None
    suggested_repair: str | None = None


class UseCaseAnalystProposal(BaseModel):
    proposal_id: str
    lane: Literal["use_case_analyst"] = "use_case_analyst"
    domain_candidates: list[AnalystCandidate] = Field(default_factory=list)
    workload_family_candidates: list[AnalystCandidate] = Field(default_factory=list)
    actor_candidates: list[AnalystCandidate] = Field(default_factory=list)
    business_process_candidates: list[AnalystCandidate] = Field(default_factory=list)
    data_class_candidates: list[AnalystCandidate] = Field(default_factory=list)
    action_flow_candidates: list[AnalystCandidate] = Field(default_factory=list)
    slo_latency_hints: list[AnalystCandidate] = Field(default_factory=list)
    compliance_hints: list[AnalystCandidate] = Field(default_factory=list)
    security_hints: list[AnalystCandidate] = Field(default_factory=list)
    candidate_services: list[AnalystCandidate] = Field(default_factory=list)
    candidate_pricing_drivers: list[AnalystCandidate] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    provenance: AnalystProvenance = "model_proposed"
    input_hash: str
    output_hash: str


class UseCaseAnalystTrace(BaseModel):
    run_id: str
    enabled: bool = False
    provider: str
    deterministic_profile_ref: dict[str, Any] = Field(default_factory=dict)
    proposal: UseCaseAnalystProposal
    decisions: list[AgentDecision] = Field(default_factory=list)
    findings: list[AnalystFinding] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    prompt_hash: str | None = None
    response_hash: str | None = None
    live_call: LiveCallAudit | None = None
    input_hash: str
    output_hash: str


class UseCaseAnalystProvider(Protocol):
    provider_name: str

    def propose(self, context: dict[str, Any]) -> UseCaseAnalystProposal: ...

    def validate(self, proposal: UseCaseAnalystProposal, deterministic_context: dict[str, Any]) -> UseCaseAnalystTrace: ...


class DisabledUseCaseAnalystProvider:
    provider_name = "disabled"

    def trace(self, context: dict[str, Any]) -> UseCaseAnalystTrace:
        input_hash = stable_json_hash(context)
        run_id = "use_case_analyst_run_" + input_hash.removeprefix("sha256:")[:12]
        proposal = _proposal(
            proposal_id="proposal_" + input_hash.removeprefix("sha256:")[:12],
            input_hash=input_hash,
            provenance="deterministic",
        )
        finding = AnalystFinding(
            severity="info",
            rule_id="use_case_analyst.disabled",
            message="ARCHWAY_ENABLE_AGENTIC_USE_CASE_ANALYST is false; no analyst provider was invoked.",
            target="raw/agent_use_case_analyst_trace.json",
        )
        output_hash = stable_json_hash({
            "deterministic_profile_ref": _deterministic_profile_ref(context),
            "proposal": proposal.model_dump(mode="json"),
            "findings": [finding.model_dump(mode="json")],
        })
        return UseCaseAnalystTrace(
            run_id=run_id,
            enabled=False,
            provider=self.provider_name,
            deterministic_profile_ref=_deterministic_profile_ref(context),
            proposal=proposal.model_copy(update={"output_hash": output_hash}),
            decisions=[
                AgentDecision(
                    proposal_id=proposal.proposal_id,
                    decision="rejected",
                    reason="Agentic use-case analyst is disabled by feature flag.",
                    deterministic_gate="ARCHWAY_ENABLE_AGENTIC_USE_CASE_ANALYST",
                )
            ],
            findings=[finding],
            input_hash=input_hash,
            output_hash=output_hash,
        )


class DeterministicFixtureUseCaseAnalystProvider:
    provider_name = "deterministic_fixture"

    def propose(self, context: dict[str, Any]) -> UseCaseAnalystProposal:
        input_hash = stable_json_hash(context)
        profile = context.get("deterministic_profile") or {}
        domain = str(profile.get("domain") or context.get("domain") or "general")
        families = [str(item) for item in profile.get("workload_families") or context.get("workload_families") or []]
        services = [str(item) for item in context.get("services") or []]
        pricing_missing = [str(item) for item in context.get("pricing_missing_drivers") or []]
        compliance_context = bool(context.get("compliance_context"))
        proposal = _proposal(
            proposal_id="proposal_" + input_hash.removeprefix("sha256:")[:12],
            input_hash=input_hash,
            provenance="derived",
            domain_candidates=[
                _candidate("domain", domain, "derived from deterministic use_case_profile.domain", "derived", ["brief.use_case_profile.domain"])
            ] if domain and domain != "general" else [],
            workload_family_candidates=[
                _candidate("family", family, "derived from deterministic use_case_profile.workload_families", "derived", ["brief.use_case_profile.workload_families"])
                for family in families[:5]
            ],
            actor_candidates=_actor_candidates(context),
            business_process_candidates=_business_process_candidates(context),
            data_class_candidates=_data_class_candidates(context),
            action_flow_candidates=_action_flow_candidates(context),
            slo_latency_hints=_latency_hints(context),
            compliance_hints=_compliance_hints(compliance_context),
            security_hints=[
                _candidate("security_hint", "identity_and_access_review", "agentic analyst can only propose security review topics", "derived", ["reviewer_findings"])
            ],
            candidate_services=[
                _candidate("service", service, "candidate only; does not modify architecture", "derived", ["architecture.components"])
                for service in services[:8]
            ],
            candidate_pricing_drivers=[
                _candidate("pricing_driver", driver, "candidate only; does not bind pricing math", "derived", ["pricing.metadata.pricing_driver_closure"])
                for driver in pricing_missing[:8]
            ],
            missing_facts=_missing_facts(context),
            assumptions=_assumptions(context),
            uncertainties=_uncertainties(context),
        )
        questions = _follow_up_questions(proposal)
        proposal = proposal.model_copy(update={"follow_up_questions": questions})
        output_hash = stable_json_hash(_proposal_payload(proposal))
        return proposal.model_copy(update={"output_hash": output_hash})

    def validate(self, proposal: UseCaseAnalystProposal, deterministic_context: dict[str, Any]) -> UseCaseAnalystTrace:
        return validate_use_case_analyst_proposal(proposal, deterministic_context, provider_name=self.provider_name)


class LiveUseCaseAnalystProvider:
    provider_name = "bedrock"

    def __init__(self, *, session_id: str | None = None, run_context: LiveRunContext | None = None):
        self.session_id = session_id
        self.run_context = run_context
        self.last_call: LiveCallAudit | None = None

    def propose(self, context: dict[str, Any]) -> UseCaseAnalystProposal:
        input_hash = stable_json_hash(context)
        messages = [
            LLMMessage(role="system", content=(
                "You are Archway's live use-case analyst. Return JSON only. "
                "Propose candidates, missing facts, follow-up questions, and assumptions. "
                "Do not claim authority: deterministic facts outrank your proposal."
            )),
            LLMMessage(role="user", content=json.dumps(context, default=str)[:22000]),
        ]
        result = live_call(
            LLMTaskType.live_use_case_analyst,
            messages,
            UseCaseAnalystProposal,
            session_id=self.session_id,
            lane="use_case_analyst",
            run_context=self.run_context,
            sensitivity_text=str(context.get("raw_use_case") or ""),
        )
        self.last_call = result.audit
        if isinstance(result.parsed, UseCaseAnalystProposal):
            proposal = result.parsed
            return proposal.model_copy(update={
                "input_hash": proposal.input_hash or input_hash,
                "output_hash": stable_json_hash(_proposal_payload(proposal)),
            })
        proposal = _proposal(
            proposal_id="proposal_" + input_hash.removeprefix("sha256:")[:12],
            input_hash=input_hash,
            provenance="model_proposed",
            uncertainties=[result.audit.error_message or result.audit.skip_reason or "Live use-case analyst did not return a usable proposal."],
        )
        return proposal.model_copy(update={"output_hash": stable_json_hash(_proposal_payload(proposal))})

    def validate(self, proposal: UseCaseAnalystProposal, deterministic_context: dict[str, Any]) -> UseCaseAnalystTrace:
        trace = validate_use_case_analyst_proposal(proposal, deterministic_context, provider_name=self.provider_name)
        if self.last_call:
            decision = "downgraded" if self.last_call.status == "accepted" else self.last_call.status
            trace = trace.model_copy(update={
                "provider": self.last_call.provider,
                "prompt_hash": self.last_call.prompt_hash,
                "response_hash": self.last_call.response_hash,
                "live_call": self.last_call.model_copy(update={"status": decision}) if decision in {"rejected", "skipped", "failed", "not_attempted", "setup_required"} else self.last_call,
            })
        return trace


def build_use_case_analyst_context(
    *,
    session_input: str | None = None,
    brief: dict | None,
    report: dict | None,
    pricing: dict | None,
    architectures: list | None,
    diagrams: list | None,
    reviewer_findings: list | None = None,
) -> dict[str, Any]:
    profile = (brief or {}).get("use_case_profile") or ((report or {}).get("metadata") or {}).get("use_case_profile") or {}
    closure = ((pricing or {}).get("metadata") or {}).get("pricing_driver_closure") or {}
    services = sorted({
        str(component.get("service") or component.get("name"))
        for spec in architectures or []
        for component in (spec.get("components") or spec.get("selected_services") or [])
        if isinstance(component, dict) and (component.get("service") or component.get("name"))
    })
    return {
        "raw_use_case": (brief or {}).get("raw_use_case") or session_input,
        "title": (brief or {}).get("title") or (report or {}).get("title"),
        "deterministic_profile": {
            "domain": profile.get("domain"),
            "workload_families": profile.get("workload_families") or [],
            "capabilities": profile.get("capabilities") or profile.get("capability_model") or [],
            "confidence": profile.get("confidence"),
        },
        "actors": profile.get("actors") or [],
        "business_process": profile.get("business_process"),
        "data_classes": profile.get("data_classes") or [],
        "action_flows": profile.get("action_flows") or [],
        "slo_latency_hints": profile.get("slo_latency_hints") or [],
        "compliance_context": bool(profile.get("compliance") or profile.get("regulatory_context")),
        "services": services,
        "pricing_missing_drivers": closure.get("missing_drivers") or [],
        "pricing_assumed_drivers": closure.get("assumed_drivers") or [],
        "diagram_count": sum(len(gallery.get("diagrams") or []) for gallery in diagrams or [] if isinstance(gallery, dict)),
        "reviewer_findings": [_finding_id(item) for item in reviewer_findings or []],
        "signals": ["brief", "research_report", "pricing", "architecture", "diagrams", "reviewer"],
    }


def build_use_case_analyst_trace(
    *,
    settings: Settings,
    context: dict[str, Any],
    provider: UseCaseAnalystProvider | None = None,
    live_run_context: LiveRunContext | None = None,
    session_id: str | None = None,
) -> UseCaseAnalystTrace:
    if not settings.enable_agentic_use_case_analyst:
        return DisabledUseCaseAnalystProvider().trace(context)
    if provider is None and settings.agentic_mode == "live_demo":
        provider = LiveUseCaseAnalystProvider(session_id=session_id, run_context=live_run_context)
    provider = provider or DeterministicFixtureUseCaseAnalystProvider()
    proposal = provider.propose(context)
    return provider.validate(proposal, context)


def validate_use_case_analyst_proposal(
    proposal: UseCaseAnalystProposal,
    deterministic_context: dict[str, Any],
    *,
    provider_name: str,
) -> UseCaseAnalystTrace:
    profile = _deterministic_profile_ref(deterministic_context)
    updated = proposal
    conflicts: list[str] = list(proposal.conflicts)
    decisions: list[AgentDecision] = []
    findings: list[AnalystFinding] = []
    updated, domain_conflicts = _validate_candidates(
        updated,
        field="domain_candidates",
        deterministic_values=[profile.get("domain")] if profile.get("domain") else [],
        target="deterministic_profile.domain",
    )
    conflicts.extend(domain_conflicts)
    updated, family_conflicts = _validate_candidates(
        updated,
        field="workload_family_candidates",
        deterministic_values=list(profile.get("workload_families") or []),
        target="deterministic_profile.workload_families",
    )
    conflicts.extend(family_conflicts)
    updated = _mark_candidates(updated, "candidate_services", "proposed")
    updated = _mark_candidates(updated, "candidate_pricing_drivers", "proposed")
    updated = _mark_hint_candidates(updated)
    if conflicts:
        decisions.append(AgentDecision(
            proposal_id=updated.proposal_id,
            decision="downgraded",
            reason="Use-case analyst proposals conflicted with deterministic facts; conflicts were recorded and not applied.",
            deterministic_gate="deterministic_profile_precedence",
        ))
        findings.extend([
            AnalystFinding(
                severity="warning",
                rule_id="use_case_analyst.conflict",
                message=conflict,
                target="raw/agent_use_case_analyst_trace.json",
                suggested_repair="Review deterministic profile and agent proposal before accepting any candidate.",
            )
            for conflict in conflicts
        ])
    else:
        decisions.append(AgentDecision(
            proposal_id=updated.proposal_id,
            decision="downgraded",
            reason="Use-case analyst output remains raw/audit-only and cannot overwrite deterministic facts.",
            deterministic_gate="D21 use-case analyst audit-only lane",
        ))
    if updated.missing_facts:
        findings.append(AnalystFinding(
            severity="advisory",
            rule_id="use_case_analyst.missing_facts",
            message="Missing use-case facts were converted into follow-up questions.",
            target="audit_pack/agentic-use-case-analysis.md",
            suggested_repair="Ask the listed follow-up questions before promoting this package.",
        ))
    output_hash = stable_json_hash({
        "deterministic_profile_ref": profile,
        "proposal": _proposal_payload(updated),
        "decisions": [decision.model_dump(mode="json") for decision in decisions],
        "findings": [finding.model_dump(mode="json") for finding in findings],
        "conflicts": sorted(set(conflicts)),
    })
    updated = updated.model_copy(update={
        "conflicts": sorted(set(conflicts)),
        "output_hash": stable_json_hash(_proposal_payload(updated.model_copy(update={"conflicts": sorted(set(conflicts))}))),
    })
    return UseCaseAnalystTrace(
        run_id="use_case_analyst_run_" + updated.input_hash.removeprefix("sha256:")[:12],
        enabled=True,
        provider=provider_name,
        deterministic_profile_ref=profile,
        proposal=updated,
        decisions=decisions,
        findings=findings,
        conflicts=sorted(set(conflicts)),
        input_hash=updated.input_hash,
        output_hash=output_hash,
    )


def use_case_analyst_summary_markdown(trace: UseCaseAnalystTrace) -> str:
    proposal = trace.proposal
    lines = [
        "# D21 Agentic Use-Case Analysis Supplement",
        "",
        "This audit-only supplement records structured use-case analyst proposals. It is not client-facing authority and does not change readiness, pricing, architecture, governance, or diagram truth.",
        "",
        f"**Enabled:** {'Yes' if trace.enabled else 'No'}",
        f"**Provider:** {trace.provider}",
        f"**Run ID:** `{trace.run_id}`",
        f"**Input hash:** `{trace.input_hash}`",
        f"**Output hash:** `{trace.output_hash}`",
        "",
        "## Accepted Deterministic Facts",
        "",
    ]
    accepted = _candidates_by_status(proposal, "accepted")
    if accepted:
        lines.extend(f"- {item.label} (`{item.key}`): {item.reason}" for item in accepted)
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Proposed Candidates", ""])
    proposed = _candidates_by_status(proposal, "proposed")
    if proposed:
        lines.extend(f"- {item.label} (`{item.key}`, {item.confidence_label}, {item.provenance}): {item.reason}" for item in proposed)
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Conflicts", ""])
    if trace.conflicts:
        lines.extend(f"- {item}" for item in trace.conflicts)
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Assumptions", ""])
    if proposal.assumptions:
        lines.extend(f"- {item}" for item in proposal.assumptions)
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Missing Facts", ""])
    if proposal.missing_facts:
        lines.extend(f"- {item}" for item in proposal.missing_facts)
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Follow-Up Questions", ""])
    if proposal.follow_up_questions:
        lines.extend(f"- {item}" for item in proposal.follow_up_questions)
    else:
        lines.append("- None recorded.")
    lines.extend(["", "Use-case analyst output remains raw/audit-only in this branch.", ""])
    return "\n".join(lines)


def _proposal(
    *,
    proposal_id: str,
    input_hash: str,
    provenance: AnalystProvenance,
    domain_candidates: list[AnalystCandidate] | None = None,
    workload_family_candidates: list[AnalystCandidate] | None = None,
    actor_candidates: list[AnalystCandidate] | None = None,
    business_process_candidates: list[AnalystCandidate] | None = None,
    data_class_candidates: list[AnalystCandidate] | None = None,
    action_flow_candidates: list[AnalystCandidate] | None = None,
    slo_latency_hints: list[AnalystCandidate] | None = None,
    compliance_hints: list[AnalystCandidate] | None = None,
    security_hints: list[AnalystCandidate] | None = None,
    candidate_services: list[AnalystCandidate] | None = None,
    candidate_pricing_drivers: list[AnalystCandidate] | None = None,
    missing_facts: list[str] | None = None,
    assumptions: list[str] | None = None,
    conflicts: list[str] | None = None,
    uncertainties: list[str] | None = None,
    follow_up_questions: list[str] | None = None,
) -> UseCaseAnalystProposal:
    base = UseCaseAnalystProposal(
        proposal_id=proposal_id,
        domain_candidates=sorted(domain_candidates or [], key=lambda item: (item.key, item.label)),
        workload_family_candidates=sorted(workload_family_candidates or [], key=lambda item: (item.key, item.label)),
        actor_candidates=sorted(actor_candidates or [], key=lambda item: (item.key, item.label)),
        business_process_candidates=sorted(business_process_candidates or [], key=lambda item: (item.key, item.label)),
        data_class_candidates=sorted(data_class_candidates or [], key=lambda item: (item.key, item.label)),
        action_flow_candidates=sorted(action_flow_candidates or [], key=lambda item: (item.key, item.label)),
        slo_latency_hints=sorted(slo_latency_hints or [], key=lambda item: (item.key, item.label)),
        compliance_hints=sorted(compliance_hints or [], key=lambda item: (item.key, item.label)),
        security_hints=sorted(security_hints or [], key=lambda item: (item.key, item.label)),
        candidate_services=sorted(candidate_services or [], key=lambda item: (item.key, item.label)),
        candidate_pricing_drivers=sorted(candidate_pricing_drivers or [], key=lambda item: (item.key, item.label)),
        missing_facts=sorted(set(missing_facts or [])),
        assumptions=sorted(set(assumptions or [])),
        conflicts=sorted(set(conflicts or [])),
        uncertainties=sorted(set(uncertainties or [])),
        follow_up_questions=sorted(set(follow_up_questions or [])),
        provenance=provenance,
        input_hash=input_hash,
        output_hash="sha256:pending",
    )
    return base.model_copy(update={"output_hash": stable_json_hash(_proposal_payload(base))})


def _proposal_payload(proposal: UseCaseAnalystProposal) -> dict[str, Any]:
    payload = proposal.model_dump(mode="json")
    payload["output_hash"] = "sha256:self"
    return payload


def _candidate(
    key_prefix: str,
    label: str,
    reason: str,
    provenance: AnalystProvenance,
    evidence_refs: list[str] | None = None,
    *,
    confidence: AnalystConfidence = "medium",
    status: AnalystAcceptedStatus = "proposed",
) -> AnalystCandidate:
    key = f"{key_prefix}:{_slug(label)}"
    return AnalystCandidate(
        key=key,
        label=label,
        confidence_label=confidence,
        provenance=provenance,
        evidence_refs=sorted(evidence_refs or []),
        reason=reason,
        accepted_status=status,
    )


def _actor_candidates(context: dict[str, Any]) -> list[AnalystCandidate]:
    actors = [str(item) for item in context.get("actors") or []]
    if not actors and context.get("raw_use_case"):
        actors = ["end_user", "operator"]
    return [_candidate("actor", actor, "candidate actor; requires user confirmation", "derived", ["brief.raw_use_case"]) for actor in actors[:6]]


def _business_process_candidates(context: dict[str, Any]) -> list[AnalystCandidate]:
    process = context.get("business_process")
    if not process and context.get("title"):
        process = str(context["title"])
    return [_candidate("business_process", str(process), "business process candidate from deterministic brief", "derived", ["brief.title"])] if process else []


def _data_class_candidates(context: dict[str, Any]) -> list[AnalystCandidate]:
    classes = [str(item) for item in context.get("data_classes") or []]
    raw = str(context.get("raw_use_case") or "").lower()
    if not classes:
        if any(word in raw for word in ["patient", "phi", "clinical", "health"]):
            classes.append("regulated_health_data")
        elif any(word in raw for word in ["contract", "document", "pdf"]):
            classes.append("business_documents")
        elif any(word in raw for word in ["customer", "chat", "call"]):
            classes.append("customer_interaction_data")
    return [_candidate("data_class", item, "data class candidate; not a compliance claim without evidence", "derived", ["brief.raw_use_case"]) for item in classes[:6]]


def _action_flow_candidates(context: dict[str, Any]) -> list[AnalystCandidate]:
    flows = [str(item) for item in context.get("action_flows") or []]
    if not flows and context.get("services"):
        flows.append("request_intake_to_managed_service_to_response")
    return [_candidate("action_flow", flow, "action-flow candidate for follow-up validation", "derived", ["architecture.components"]) for flow in flows[:6]]


def _latency_hints(context: dict[str, Any]) -> list[AnalystCandidate]:
    hints = [str(item) for item in context.get("slo_latency_hints") or []]
    raw = str(context.get("raw_use_case") or "").lower()
    if not hints and any(word in raw for word in ["real-time", "realtime", "live", "interactive"]):
        hints.append("interactive_or_low_latency")
    return [_candidate("slo_latency", hint, "latency/SLO hint; requires explicit target before readiness promotion", "derived", ["brief.raw_use_case"]) for hint in hints[:4]]


def _compliance_hints(compliance_context: bool) -> list[AnalystCandidate]:
    if not compliance_context:
        return []
    return [
        _candidate("compliance_hint", "regulated_context_review", "compliance hint only; not an authoritative compliance claim", "derived", ["brief.use_case_profile"])
    ]


def _missing_facts(context: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    profile = context.get("deterministic_profile") or {}
    if not profile.get("domain"):
        missing.append("domain")
    if not profile.get("workload_families"):
        missing.append("workload_family")
    if not context.get("actors"):
        missing.append("actors")
    if not context.get("data_classes"):
        missing.append("data_classes")
    if not context.get("pricing_missing_drivers") and not context.get("pricing_assumed_drivers"):
        missing.append("pricing_driver_volumes")
    return sorted(set(missing))


def _assumptions(context: dict[str, Any]) -> list[str]:
    assumptions = [f"Pricing driver assumed: {item}" for item in context.get("pricing_assumed_drivers") or []]
    if context.get("diagram_count"):
        assumptions.append("Diagram artifacts are treated as deterministic output context, not analyst authority.")
    return sorted(set(assumptions))


def _uncertainties(context: dict[str, Any]) -> list[str]:
    uncertainties = []
    if context.get("reviewer_findings"):
        uncertainties.append("Reviewer findings indicate unresolved package uncertainty.")
    if context.get("pricing_missing_drivers"):
        uncertainties.append("Pricing driver closure has missing drivers.")
    return sorted(set(uncertainties))


def _follow_up_questions(proposal: UseCaseAnalystProposal) -> list[str]:
    questions = [f"Please confirm the missing fact: {item}." for item in proposal.missing_facts]
    for driver in proposal.candidate_pricing_drivers:
        questions.append(f"What value should Archway use for pricing driver candidate {driver.label}?")
    for service in proposal.candidate_services:
        questions.append(f"Should {service.label} remain in the candidate architecture, and what role should it play?")
    return sorted(set(questions))


def _validate_candidates(
    proposal: UseCaseAnalystProposal,
    *,
    field: str,
    deterministic_values: list[str],
    target: str,
) -> tuple[UseCaseAnalystProposal, list[str]]:
    deterministic = {str(item).lower(): str(item) for item in deterministic_values if item}
    conflicts: list[str] = []
    updated: list[AnalystCandidate] = []
    for candidate in getattr(proposal, field):
        label_key = candidate.label.lower()
        if deterministic:
            if label_key in deterministic:
                updated.append(candidate.model_copy(update={"accepted_status": "accepted", "provenance": "deterministic"}))
            else:
                conflicts.append(f"{field}:{candidate.label} conflicts with {target}={sorted(deterministic.values())}.")
                updated.append(candidate.model_copy(update={"accepted_status": "conflict"}))
        else:
            updated.append(candidate.model_copy(update={"accepted_status": "proposed"}))
    return proposal.model_copy(update={field: updated}), conflicts


def _mark_candidates(proposal: UseCaseAnalystProposal, field: str, status: AnalystAcceptedStatus) -> UseCaseAnalystProposal:
    return proposal.model_copy(update={
        field: [candidate.model_copy(update={"accepted_status": status}) for candidate in getattr(proposal, field)]
    })


def _mark_hint_candidates(proposal: UseCaseAnalystProposal) -> UseCaseAnalystProposal:
    fields = (
        "actor_candidates",
        "business_process_candidates",
        "data_class_candidates",
        "action_flow_candidates",
        "slo_latency_hints",
        "compliance_hints",
        "security_hints",
    )
    updates = {
        field: [candidate.model_copy(update={"accepted_status": "proposed"}) for candidate in getattr(proposal, field)]
        for field in fields
    }
    return proposal.model_copy(update=updates)


def _deterministic_profile_ref(context: dict[str, Any]) -> dict[str, Any]:
    profile = context.get("deterministic_profile") or {}
    return {
        "domain": profile.get("domain"),
        "workload_families": list(profile.get("workload_families") or []),
        "capabilities": list(profile.get("capabilities") or []),
        "confidence": profile.get("confidence"),
    }


def _candidates_by_status(proposal: UseCaseAnalystProposal, status: AnalystAcceptedStatus) -> list[AnalystCandidate]:
    fields = (
        "domain_candidates",
        "workload_family_candidates",
        "actor_candidates",
        "business_process_candidates",
        "data_class_candidates",
        "action_flow_candidates",
        "slo_latency_hints",
        "compliance_hints",
        "security_hints",
        "candidate_services",
        "candidate_pricing_drivers",
    )
    return sorted(
        [
            candidate
            for field in fields
            for candidate in getattr(proposal, field)
            if candidate.accepted_status == status
        ],
        key=lambda item: (item.key, item.label),
    )


def _finding_id(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("finding_id") or item.get("id") or item.get("rule_id") or item)
    return str(getattr(item, "finding_id", None) or getattr(item, "id", None) or item)


def _slug(value: str) -> str:
    out = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value)).strip("_")
    while "__" in out:
        out = out.replace("__", "_")
    return out or "unknown"
