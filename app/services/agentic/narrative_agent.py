from __future__ import annotations

import json
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.services.agentic.live_audit import LiveCallAudit
from app.services.agentic.live_bedrock_harness import LiveRunContext, live_call
from app.services.dossier_manifest import stable_json_hash
from app.services.llm.base import LLMMessage, LLMTaskType

NarrativeClaimKind = Literal[
    "aws_docs",
    "aws_pricing",
    "architecture",
    "compliance",
    "security",
    "pricing",
    "readiness",
    "narrative_only",
    "unknown",
]
NarrativeSupportStatus = Literal["verified", "assumption", "not_estimated", "unsupported", "conflict", "narrative_only"]
NarrativeDecisionStatus = Literal["accepted_for_audit", "rejected", "downgraded", "needs_evidence", "client_blocked"]
NarrativeProvenance = Literal["deterministic", "derived", "model_proposed", "skipped"]


class NarrativeSentenceClaim(BaseModel):
    sentence_id: str
    text: str
    claim_kind: NarrativeClaimKind = "unknown"
    support_status: NarrativeSupportStatus = "unsupported"
    evidence_refs: list[str] = Field(default_factory=list)
    source_artifact_refs: list[str] = Field(default_factory=list)
    can_render_client: bool = False


class NarrativeRewriteProposal(BaseModel):
    proposal_id: str
    lane: Literal["narrative"] = "narrative"
    target_artifact: str
    target_section: str
    original_text_hash: str
    proposed_text: str
    sentence_claim_map: list[NarrativeSentenceClaim] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    not_estimated_refs: list[str] = Field(default_factory=list)
    unsupported_sentence_ids: list[str] = Field(default_factory=list)
    provenance: NarrativeProvenance = "model_proposed"
    input_hash: str
    output_hash: str


class NarrativeDecision(BaseModel):
    proposal_id: str
    sentence_id: str | None = None
    decision: NarrativeDecisionStatus
    reason: str
    deterministic_gate: str


class NarrativeTrace(BaseModel):
    run_id: str
    enabled: bool = False
    provider: str
    proposal: NarrativeRewriteProposal
    decisions: list[NarrativeDecision] = Field(default_factory=list)
    unsupported_sentences: list[NarrativeSentenceClaim] = Field(default_factory=list)
    input_hash: str
    output_hash: str
    prompt_hash: str | None = None
    response_hash: str | None = None
    live_call: LiveCallAudit | None = None


class NarrativeProvider(Protocol):
    provider_name: str

    def propose(self, context: dict[str, Any]) -> NarrativeRewriteProposal: ...

    def validate(self, proposal: NarrativeRewriteProposal, deterministic_context: dict[str, Any]) -> NarrativeTrace: ...


class DisabledNarrativeProvider:
    provider_name = "disabled"

    def trace(self, context: dict[str, Any]) -> NarrativeTrace:
        input_hash = stable_json_hash(context)
        proposal = _proposal(
            proposal_id="narrative_proposal_" + input_hash.removeprefix("sha256:")[:12],
            input_hash=input_hash,
            target_artifact="none",
            target_section="disabled",
            original_text="",
            proposed_text="",
            provenance="skipped",
        )
        output_hash = stable_json_hash({"proposal": _proposal_payload(proposal), "enabled": False})
        proposal = proposal.model_copy(update={"output_hash": output_hash})
        return NarrativeTrace(
            run_id="narrative_run_" + input_hash.removeprefix("sha256:")[:12],
            enabled=False,
            provider=self.provider_name,
            proposal=proposal,
            decisions=[
                NarrativeDecision(
                    proposal_id=proposal.proposal_id,
                    decision="rejected",
                    reason="Agentic narrative lane is disabled by feature flag.",
                    deterministic_gate="ARCHWAY_ENABLE_AGENTIC_NARRATIVE",
                )
            ],
            input_hash=input_hash,
            output_hash=output_hash,
        )


class DeterministicFixtureNarrativeProvider:
    provider_name = "deterministic_fixture"

    def propose(self, context: dict[str, Any]) -> NarrativeRewriteProposal:
        input_hash = stable_json_hash(context)
        sentences = [
            NarrativeSentenceClaim(
                sentence_id="s1",
                text="This package keeps pricing directional until customer quantities and rate evidence are confirmed.",
                claim_kind="pricing",
                support_status="verified",
                evidence_refs=["pricing.metadata.pricing_driver_closure"],
                source_artifact_refs=["03-pricing.md"],
            ),
            NarrativeSentenceClaim(
                sentence_id="s2",
                text="Reviewers should treat agentic suggestions as audit-only proposals.",
                claim_kind="narrative_only",
                support_status="narrative_only",
                source_artifact_refs=["raw/agent_runs.json"],
            ),
        ]
        proposal = _proposal(
            proposal_id="narrative_proposal_" + input_hash.removeprefix("sha256:")[:12],
            input_hash=input_hash,
            target_artifact=str(context.get("target_artifact") or "01-solution-brief.md"),
            target_section=str(context.get("target_section") or "Executive summary"),
            original_text=str(context.get("original_text") or ""),
            proposed_text=" ".join(sentence.text for sentence in sentences),
            sentence_claim_map=sentences,
            evidence_refs=["pricing.metadata.pricing_driver_closure"],
            provenance="derived",
        )
        return proposal.model_copy(update={"output_hash": stable_json_hash(_proposal_payload(proposal))})

    def validate(self, proposal: NarrativeRewriteProposal, deterministic_context: dict[str, Any]) -> NarrativeTrace:
        return validate_narrative_proposal(proposal, deterministic_context, provider_name=self.provider_name)


class LiveNarrativeProvider:
    provider_name = "bedrock"

    def __init__(self, *, session_id: str | None = None, run_context: LiveRunContext | None = None, sensitivity_text: str | None = None):
        self.session_id = session_id
        self.run_context = run_context
        self.sensitivity_text = sensitivity_text
        self.last_call: LiveCallAudit | None = None

    def propose(self, context: dict[str, Any]) -> NarrativeRewriteProposal:
        input_hash = stable_json_hash(context)
        messages = [
            LLMMessage(role="system", content=(
                "You are Archway's live narrative synthesizer. Return JSON only. "
                "Only rewrite using provided verified, assumption, not_estimated, or narrative_only claims. "
                "Do not invent services, prices, readiness, compliance, or architecture claims."
            )),
            LLMMessage(role="user", content=json.dumps(context, default=str)[:22000]),
        ]
        result = live_call(
            LLMTaskType.live_narrative_synthesis,
            messages,
            NarrativeRewriteProposal,
            session_id=self.session_id,
            lane="narrative",
            run_context=self.run_context,
            sensitivity_text=self.sensitivity_text,
        )
        self.last_call = result.audit
        if isinstance(result.parsed, NarrativeRewriteProposal):
            proposal = result.parsed
            return proposal.model_copy(update={
                "input_hash": proposal.input_hash or input_hash,
                "output_hash": stable_json_hash(_proposal_payload(proposal)),
            })
        proposal = _proposal(
            proposal_id="narrative_proposal_" + input_hash.removeprefix("sha256:")[:12],
            input_hash=input_hash,
            target_artifact=str(context.get("target_artifact") or "01-solution-brief.md"),
            target_section=str(context.get("target_section") or "Executive summary"),
            original_text=str(context.get("original_text") or ""),
            proposed_text="",
            provenance="model_proposed",
            unsupported_sentence_ids=["live_narrative_unavailable"],
        )
        return proposal.model_copy(update={"output_hash": stable_json_hash(_proposal_payload(proposal))})

    def validate(self, proposal: NarrativeRewriteProposal, deterministic_context: dict[str, Any]) -> NarrativeTrace:
        trace = validate_narrative_proposal(proposal, deterministic_context, provider_name=self.provider_name)
        if self.last_call:
            trace = trace.model_copy(update={
                "provider": self.last_call.provider,
                "prompt_hash": self.last_call.prompt_hash,
                "response_hash": self.last_call.response_hash,
                "live_call": self.last_call,
            })
        return trace


def build_narrative_context(
    *,
    report: dict | None,
    pricing: dict | None,
    architectures: list | None,
    reviewer_findings: list | None = None,
    target_artifact: str = "01-solution-brief.md",
    target_section: str = "Executive summary",
) -> dict[str, Any]:
    pricing_metadata = ((pricing or {}).get("metadata") or {})
    readiness = (((report or {}).get("metadata") or {}).get("customer_readiness") or {})
    services = sorted({
        str(component.get("service") or component.get("name"))
        for spec in architectures or []
        for component in (spec.get("components") or spec.get("selected_services") or [])
        if isinstance(component, dict) and (component.get("service") or component.get("name"))
    })
    return {
        "target_artifact": target_artifact,
        "target_section": target_section,
        "original_text": ((report or {}).get("summary") or (report or {}).get("executive_summary") or ""),
        "known_services": services,
        "pricing": {
            "low_monthly_usd": (pricing or {}).get("low_monthly_usd"),
            "expected_monthly_usd": (pricing or {}).get("expected_monthly_usd"),
            "high_monthly_usd": (pricing or {}).get("high_monthly_usd"),
            "headline_safe": pricing_metadata.get("pricing_can_be_displayed_as_headline") is True,
            "procurement_ready": pricing_metadata.get("procurement_ready") is True,
            "closure": pricing_metadata.get("pricing_driver_closure") or {},
        },
        "readiness": {
            "tier": readiness.get("tier"),
            "label": readiness.get("label"),
            "reasons": readiness.get("reasons") or [],
        },
        "evidence_refs": _evidence_refs(report, pricing),
        "reviewer_findings": [_finding_id(item) for item in reviewer_findings or []],
    }


def build_narrative_trace(
    *,
    settings: Settings,
    context: dict[str, Any],
    provider: NarrativeProvider | None = None,
    live_run_context: LiveRunContext | None = None,
    session_id: str | None = None,
    sensitivity_text: str | None = None,
) -> NarrativeTrace:
    if not settings.enable_agentic_narrative:
        return DisabledNarrativeProvider().trace(context)
    if provider is None and settings.agentic_mode == "live_demo":
        provider = LiveNarrativeProvider(session_id=session_id, run_context=live_run_context, sensitivity_text=sensitivity_text)
    provider = provider or DeterministicFixtureNarrativeProvider()
    proposal = provider.propose(context)
    return provider.validate(proposal, context)


def validate_narrative_proposal(
    proposal: NarrativeRewriteProposal,
    deterministic_context: dict[str, Any],
    *,
    provider_name: str,
) -> NarrativeTrace:
    known_services = set(deterministic_context.get("known_services") or [])
    known_prices = {
        str(value)
        for value in (deterministic_context.get("pricing") or {}).values()
        if isinstance(value, int | float)
    }
    readiness_values = {
        str(value)
        for value in (deterministic_context.get("readiness") or {}).values()
        if isinstance(value, str) and value
    }
    decisions: list[NarrativeDecision] = []
    unsupported: list[NarrativeSentenceClaim] = []
    validated_sentences: list[NarrativeSentenceClaim] = []
    for sentence in sorted(proposal.sentence_claim_map, key=lambda item: item.sentence_id):
        status, reason = _validate_sentence(sentence, known_services, known_prices, readiness_values)
        can_render_client = False
        if status in {"unsupported", "conflict"}:
            decision = "client_blocked" if status == "unsupported" else "rejected"
            unsupported.append(sentence.model_copy(update={"support_status": status, "can_render_client": False}))
        elif status in {"verified", "assumption", "not_estimated", "narrative_only"}:
            decision = "accepted_for_audit"
        else:
            decision = "needs_evidence"
            unsupported.append(sentence.model_copy(update={"support_status": status, "can_render_client": False}))
        validated = sentence.model_copy(update={"support_status": status, "can_render_client": can_render_client})
        validated_sentences.append(validated)
        decisions.append(NarrativeDecision(
            proposal_id=proposal.proposal_id,
            sentence_id=sentence.sentence_id,
            decision=decision,
            reason=reason,
            deterministic_gate="D21 narrative audit-only validation",
        ))
    updated = proposal.model_copy(update={
        "sentence_claim_map": validated_sentences,
        "unsupported_sentence_ids": sorted({item.sentence_id for item in unsupported}),
        "output_hash": "sha256:pending",
    })
    updated = updated.model_copy(update={"output_hash": stable_json_hash(_proposal_payload(updated))})
    output_hash = stable_json_hash({
        "proposal": _proposal_payload(updated),
        "decisions": [decision.model_dump(mode="json") for decision in decisions],
        "unsupported_sentences": [item.model_dump(mode="json") for item in unsupported],
    })
    return NarrativeTrace(
        run_id="narrative_run_" + updated.input_hash.removeprefix("sha256:")[:12],
        enabled=True,
        provider=provider_name,
        proposal=updated,
        decisions=decisions,
        unsupported_sentences=unsupported,
        input_hash=updated.input_hash,
        output_hash=output_hash,
    )


def narrative_summary_markdown(trace: NarrativeTrace) -> str:
    lines = [
        "# D21 Agentic Narrative Proposals",
        "",
        "This audit-only supplement records proposed wording improvements. They are proposed only and are not applied to client_pack in this branch.",
        "",
        f"**Enabled:** {'Yes' if trace.enabled else 'No'}",
        f"**Provider:** {trace.provider}",
        f"**Run ID:** `{trace.run_id}`",
        f"**Input hash:** `{trace.input_hash}`",
        f"**Output hash:** `{trace.output_hash}`",
        "",
        "## Proposed Rewrite",
        "",
        trace.proposal.proposed_text or "_No proposed rewrite recorded._",
        "",
        "## Decisions",
        "",
    ]
    if trace.decisions:
        lines.extend(f"- {item.sentence_id or trace.proposal.proposal_id}: {item.decision} — {item.reason}" for item in trace.decisions)
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Unsupported / Client-Blocked Sentences", ""])
    if trace.unsupported_sentences:
        lines.extend(f"- `{item.sentence_id}`: {item.text}" for item in trace.unsupported_sentences)
    else:
        lines.append("- None recorded.")
    lines.extend(["", "Narrative proposals remain raw/audit-only and cannot change readiness, pricing, architecture, governance, diagrams, or client_pack.", ""])
    return "\n".join(lines)


def _validate_sentence(
    sentence: NarrativeSentenceClaim,
    known_services: set[str],
    known_prices: set[str],
    readiness_values: set[str],
) -> tuple[NarrativeSupportStatus, str]:
    if sentence.claim_kind == "narrative_only":
        return "narrative_only", "Sentence is narrative-only and remains audit-only."
    if not sentence.evidence_refs and not sentence.source_artifact_refs and sentence.support_status not in {"assumption", "not_estimated"}:
        return "unsupported", "Factual sentence lacks evidence, assumption, not-estimated marker, or deterministic source artifact."
    if sentence.claim_kind in {"aws_docs", "architecture", "security", "compliance"}:
        unknown_services = [service for service in _service_like_tokens(sentence.text) if service not in known_services]
        if unknown_services:
            return "unsupported", f"Sentence introduces services not present in deterministic architecture: {', '.join(unknown_services)}."
    if sentence.claim_kind == "pricing":
        prices = _money_like_tokens(sentence.text)
        if prices and not any(price in known_prices for price in prices):
            return "conflict", "Pricing number does not match deterministic pricing source."
    if sentence.claim_kind == "readiness":
        if readiness_values and not any(value in sentence.text for value in readiness_values):
            return "conflict", "Readiness label does not match deterministic readiness source."
    if sentence.support_status in {"assumption", "not_estimated"}:
        return sentence.support_status, f"Sentence is explicitly labeled {sentence.support_status}."
    return "verified", "Sentence is backed by deterministic evidence/source references and accepted for audit only."


def _proposal(
    *,
    proposal_id: str,
    input_hash: str,
    target_artifact: str,
    target_section: str,
    original_text: str,
    proposed_text: str,
    sentence_claim_map: list[NarrativeSentenceClaim] | None = None,
    evidence_refs: list[str] | None = None,
    assumptions: list[str] | None = None,
    not_estimated_refs: list[str] | None = None,
    unsupported_sentence_ids: list[str] | None = None,
    provenance: NarrativeProvenance,
) -> NarrativeRewriteProposal:
    proposal = NarrativeRewriteProposal(
        proposal_id=proposal_id,
        target_artifact=target_artifact,
        target_section=target_section,
        original_text_hash=stable_json_hash({"original_text": original_text}),
        proposed_text=proposed_text,
        sentence_claim_map=sorted(sentence_claim_map or [], key=lambda item: item.sentence_id),
        evidence_refs=sorted(set(evidence_refs or [])),
        assumptions=sorted(set(assumptions or [])),
        not_estimated_refs=sorted(set(not_estimated_refs or [])),
        unsupported_sentence_ids=sorted(set(unsupported_sentence_ids or [])),
        provenance=provenance,
        input_hash=input_hash,
        output_hash="sha256:pending",
    )
    return proposal.model_copy(update={"output_hash": stable_json_hash(_proposal_payload(proposal))})


def _proposal_payload(proposal: NarrativeRewriteProposal) -> dict[str, Any]:
    payload = proposal.model_dump(mode="json")
    payload["output_hash"] = "sha256:self"
    return payload


def _evidence_refs(report: dict | None, pricing: dict | None) -> list[str]:
    refs = ["report.metadata"] if report else []
    if pricing:
        refs.append("pricing.metadata")
    return refs


def _finding_id(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("finding_id") or item.get("rule_id") or item.get("id") or item)
    return str(getattr(item, "finding_id", None) or getattr(item, "rule_id", None) or item)


def _service_like_tokens(text: str) -> list[str]:
    # Conservative: only treat explicit "Amazon/AWS <Name>" phrases as service-like.
    words = text.replace(",", " ").replace(".", " ").split()
    out: list[str] = []
    for idx, word in enumerate(words[:-1]):
        if word in {"Amazon", "AWS"}:
            out.append(f"{word} {words[idx + 1]}")
    return sorted(set(out))


def _money_like_tokens(text: str) -> list[str]:
    return sorted({
        token.strip("$,./")
        for token in text.replace(",", " ").split()
        if token.startswith("$") and any(ch.isdigit() for ch in token)
    })
