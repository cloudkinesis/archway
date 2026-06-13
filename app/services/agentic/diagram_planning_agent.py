from __future__ import annotations

import json
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.services.agentic.live_audit import LiveCallAudit
from app.services.agentic.live_bedrock_harness import LiveRunContext, live_call
from app.services.dossier_manifest import stable_json_hash
from app.services.llm.base import LLMMessage, LLMTaskType
from app.services.view_planner import SEMANTIC_TO_COMPILER_VIEW

DiagramPlanProvenance = Literal["deterministic", "catalog_backed", "model_proposed", "derived", "user_input", "skipped"]
DiagramAudience = Literal["client", "audit", "internal"]
DiagramPriority = Literal["low", "medium", "high"]
DiagramAcceptedStatus = Literal["proposed", "accepted", "ignored", "unsupported", "fallback", "conflict"]
DiagramDecisionStatus = Literal["accepted_for_audit", "ignored", "unsupported", "fallback_recorded", "rejected"]


class DiagramViewCandidate(BaseModel):
    view_id: str
    view_type: str
    display_label: str
    purpose: str
    intended_nodes: list[str] = Field(default_factory=list)
    intended_flows: list[str] = Field(default_factory=list)
    expected_audience: DiagramAudience = "audit"
    priority: DiagramPriority = "medium"
    provenance: DiagramPlanProvenance = "model_proposed"
    accepted_status: DiagramAcceptedStatus = "proposed"
    reason: str = ""
    claims_rendered: bool = False
    requires_architecture_changes: bool = False


class DiagramMissingViewRequest(BaseModel):
    requested_view_type: str
    reason: str
    expected_nodes: list[str] = Field(default_factory=list)
    expected_flows: list[str] = Field(default_factory=list)
    disclosure_text: str
    provenance: DiagramPlanProvenance = "model_proposed"


class DiagramViewPlanProposal(BaseModel):
    proposal_id: str
    lane: Literal["diagram_planner"] = "diagram_planner"
    candidate_views: list[DiagramViewCandidate] = Field(default_factory=list)
    missing_view_requests: list[DiagramMissingViewRequest] = Field(default_factory=list)
    unsupported_view_requests: list[DiagramMissingViewRequest] = Field(default_factory=list)
    rationale: str
    provenance: DiagramPlanProvenance = "model_proposed"
    input_hash: str
    output_hash: str


class DiagramPlanningDecision(BaseModel):
    view_id: str
    decision: DiagramDecisionStatus
    reason: str
    compiler_ledger_ref: str | None = None
    rendered_view_ref: str | None = None


class DiagramPlanningTrace(BaseModel):
    run_id: str
    enabled: bool = False
    provider: str
    deterministic_view_plan_ref: dict[str, Any] = Field(default_factory=dict)
    compiler_ledger_ref: dict[str, Any] = Field(default_factory=dict)
    proposal: DiagramViewPlanProposal
    decisions: list[DiagramPlanningDecision] = Field(default_factory=list)
    input_hash: str
    output_hash: str
    prompt_hash: str | None = None
    response_hash: str | None = None
    live_call: LiveCallAudit | None = None


class DiagramPlanningProvider(Protocol):
    provider_name: str

    def propose(self, context: dict[str, Any]) -> DiagramViewPlanProposal: ...

    def validate(self, proposal: DiagramViewPlanProposal, deterministic_context: dict[str, Any]) -> DiagramPlanningTrace: ...


class DisabledDiagramPlanningProvider:
    provider_name = "disabled"

    def trace(self, context: dict[str, Any]) -> DiagramPlanningTrace:
        input_hash = stable_json_hash(context)
        proposal = _proposal(
            proposal_id="diagram_plan_" + input_hash.removeprefix("sha256:")[:12],
            input_hash=input_hash,
            rationale="Agentic diagram planning lane is disabled by feature flag.",
            provenance="skipped",
        )
        output_hash = stable_json_hash({"proposal": _proposal_payload(proposal), "enabled": False})
        proposal = proposal.model_copy(update={"output_hash": output_hash})
        return DiagramPlanningTrace(
            run_id="diagram_plan_run_" + input_hash.removeprefix("sha256:")[:12],
            enabled=False,
            provider=self.provider_name,
            deterministic_view_plan_ref=_deterministic_view_plan_ref(context),
            compiler_ledger_ref=_compiler_ledger_ref(context),
            proposal=proposal,
            decisions=[
                DiagramPlanningDecision(
                    view_id="diagram_planner_disabled",
                    decision="ignored",
                    reason="Agentic diagram planning lane is disabled by feature flag.",
                    compiler_ledger_ref="ARCHWAY_ENABLE_AGENTIC_DIAGRAM_PLANNER",
                )
            ],
            input_hash=input_hash,
            output_hash=output_hash,
        )


class DeterministicFixtureDiagramPlanningProvider:
    provider_name = "deterministic_fixture"

    def propose(self, context: dict[str, Any]) -> DiagramViewPlanProposal:
        input_hash = stable_json_hash(context)
        existing = sorted(context.get("deterministic_view_ids") or context.get("rendered_view_ids") or ["production_logical_service_flow"])
        first = existing[0]
        candidate = DiagramViewCandidate(
            view_id=first,
            view_type=first,
            display_label=first.replace("_", " ").title(),
            purpose="Confirm the deterministic rendered view remains the diagram authority.",
            intended_nodes=sorted((context.get("known_nodes") or [])[:2]),
            intended_flows=sorted((context.get("known_flows") or [])[:2]),
            expected_audience="audit",
            priority="medium",
            provenance="derived",
        )
        missing = DiagramMissingViewRequest(
            requested_view_type="future_customer_journey_view",
            reason="A future semantic view could help explain actor touchpoints, but no deterministic renderer is available in this branch.",
            disclosure_text="Requested customer journey view is audit-only and not rendered by the compiler.",
            provenance="derived",
        )
        proposal = _proposal(
            proposal_id="diagram_plan_" + input_hash.removeprefix("sha256:")[:12],
            input_hash=input_hash,
            candidate_views=[candidate],
            missing_view_requests=[missing],
            unsupported_view_requests=[missing],
            rationale="Fixture proposal demonstrates matching existing compiler output and disclosing unsupported semantic views.",
            provenance="derived",
        )
        return proposal.model_copy(update={"output_hash": stable_json_hash(_proposal_payload(proposal))})

    def validate(self, proposal: DiagramViewPlanProposal, deterministic_context: dict[str, Any]) -> DiagramPlanningTrace:
        return validate_diagram_plan_proposal(proposal, deterministic_context, provider_name=self.provider_name)


class LiveDiagramPlanningProvider:
    provider_name = "bedrock"

    def __init__(self, *, session_id: str | None = None, run_context: LiveRunContext | None = None, sensitivity_text: str | None = None):
        self.session_id = session_id
        self.run_context = run_context
        self.sensitivity_text = sensitivity_text
        self.last_call: LiveCallAudit | None = None

    def propose(self, context: dict[str, Any]) -> DiagramViewPlanProposal:
        input_hash = stable_json_hash(context)
        messages = [
            LLMMessage(role="system", content=(
                "You are Archway's live diagram planner. Return JSON only. "
                "Propose semantic diagram views and missing-view disclosures. "
                "Do not claim a view is rendered unless the deterministic context lists it as rendered."
            )),
            LLMMessage(role="user", content=json.dumps(context, default=str)[:22000]),
        ]
        result = live_call(
            LLMTaskType.live_diagram_planning,
            messages,
            DiagramViewPlanProposal,
            session_id=self.session_id,
            lane="diagram_planner",
            run_context=self.run_context,
            sensitivity_text=self.sensitivity_text,
        )
        self.last_call = result.audit
        if isinstance(result.parsed, DiagramViewPlanProposal):
            proposal = result.parsed
            return proposal.model_copy(update={
                "input_hash": proposal.input_hash or input_hash,
                "output_hash": stable_json_hash(_proposal_payload(proposal)),
            })
        proposal = _proposal(
            proposal_id="diagram_plan_" + input_hash.removeprefix("sha256:")[:12],
            input_hash=input_hash,
            rationale=result.audit.error_message or result.audit.skip_reason or "Live diagram planner did not return a usable proposal.",
            provenance="model_proposed",
        )
        return proposal.model_copy(update={"output_hash": stable_json_hash(_proposal_payload(proposal))})

    def validate(self, proposal: DiagramViewPlanProposal, deterministic_context: dict[str, Any]) -> DiagramPlanningTrace:
        trace = validate_diagram_plan_proposal(proposal, deterministic_context, provider_name=self.provider_name)
        if self.last_call:
            trace = trace.model_copy(update={
                "provider": self.last_call.provider,
                "prompt_hash": self.last_call.prompt_hash,
                "response_hash": self.last_call.response_hash,
                "live_call": self.last_call,
            })
        return trace


def build_diagram_planning_context(*, architectures: list | None, diagrams: list | None, diagram_fidelity: dict | None = None) -> dict[str, Any]:
    known_nodes: set[str] = set()
    known_flows: set[str] = set()
    expected_views: set[str] = set()
    for spec in architectures or []:
        metadata = spec.get("metadata") or {}
        expected_views.update(str(item) for item in metadata.get("expected_views") or [] if item)
        for component in spec.get("components") or spec.get("selected_services") or []:
            if isinstance(component, dict):
                for key in ("id", "name", "service"):
                    if component.get(key):
                        known_nodes.add(str(component[key]))
        for flow in spec.get("flows") or []:
            if isinstance(flow, dict):
                for key in ("id", "name", "label"):
                    if flow.get(key):
                        known_flows.add(str(flow[key]))

    rendered_view_ids: set[str] = set()
    deterministic_view_ids: set[str] = set(expected_views)
    ledger_entries: dict[str, list[dict[str, Any]]] = {}
    ledger_by_view: dict[str, dict[str, Any]] = {}
    fallback_view_ids: set[str] = set()
    unsupported_view_ids: set[str] = set()
    for gallery in diagrams or []:
        mode = gallery.get("mode") or "unknown"
        for diagram in gallery.get("diagrams") or []:
            for key in ("view_id", "compiler_view_id", "semantic_view_id"):
                if diagram.get(key):
                    deterministic_view_ids.add(str(diagram[key]))
            rendered = diagram.get("compiler_view_id") or diagram.get("view_id")
            if rendered:
                rendered_view_ids.add(str(rendered))
        ledger = gallery.get("view_rendering_ledger") or {}
        for bucket, items in ledger.items():
            ledger_entries.setdefault(bucket, [])
            for item in items or []:
                entry = {**item, "mode": item.get("mode") or mode, "ledger_bucket": bucket}
                ledger_entries[bucket].append(entry)
                for key in ("view_id", "semantic_view_id", "compiler_view_id", "represented_by_view_id"):
                    if entry.get(key):
                        ledger_by_view[str(entry[key])] = entry
                if bucket in {"rendered_via_broader_supported_view", "omitted_with_reason"}:
                    if entry.get("view_id"):
                        fallback_view_ids.add(str(entry["view_id"]))
                if bucket == "unsupported_not_rendered":
                    if entry.get("view_id"):
                        unsupported_view_ids.add(str(entry["view_id"]))

    fidelity = diagram_fidelity or {}
    for mode, ids in (fidelity.get("rendered_view_ids_by_mode") or {}).items():
        rendered_view_ids.update(str(item) for item in ids or [] if item)
    for item in fidelity.get("missing_requested_views") or []:
        if item.get("view_id"):
            unsupported_view_ids.add(str(item["view_id"]))
            ledger_by_view.setdefault(str(item["view_id"]), {**item, "ledger_bucket": "unsupported_not_rendered"})

    return {
        "known_nodes": sorted(known_nodes),
        "known_flows": sorted(known_flows),
        "deterministic_view_ids": sorted(deterministic_view_ids | rendered_view_ids),
        "rendered_view_ids": sorted(rendered_view_ids),
        "supported_view_types": sorted(set(SEMANTIC_TO_COMPILER_VIEW) | rendered_view_ids | deterministic_view_ids),
        "unsupported_view_ids": sorted(unsupported_view_ids),
        "fallback_view_ids": sorted(fallback_view_ids),
        "compiler_ledger": {key: sorted(value, key=lambda item: (str(item.get("mode")), str(item.get("view_id")), str(item.get("compiler_view_id")))) for key, value in ledger_entries.items()},
        "ledger_by_view": ledger_by_view,
    }


def build_diagram_planning_trace(
    *,
    settings: Settings,
    context: dict[str, Any],
    provider: DiagramPlanningProvider | None = None,
    live_run_context: LiveRunContext | None = None,
    session_id: str | None = None,
    sensitivity_text: str | None = None,
) -> DiagramPlanningTrace:
    if not settings.enable_agentic_diagram_planner:
        return DisabledDiagramPlanningProvider().trace(context)
    if provider is None and settings.agentic_mode == "live_demo":
        provider = LiveDiagramPlanningProvider(session_id=session_id, run_context=live_run_context, sensitivity_text=sensitivity_text)
    provider = provider or DeterministicFixtureDiagramPlanningProvider()
    proposal = provider.propose(context)
    return provider.validate(proposal, context)


def validate_diagram_plan_proposal(
    proposal: DiagramViewPlanProposal,
    deterministic_context: dict[str, Any],
    *,
    provider_name: str,
) -> DiagramPlanningTrace:
    deterministic_ids = set(deterministic_context.get("deterministic_view_ids") or [])
    rendered_ids = set(deterministic_context.get("rendered_view_ids") or [])
    supported_types = set(deterministic_context.get("supported_view_types") or [])
    unsupported_ids = set(deterministic_context.get("unsupported_view_ids") or [])
    fallback_ids = set(deterministic_context.get("fallback_view_ids") or [])
    known_nodes = set(deterministic_context.get("known_nodes") or [])
    known_flows = set(deterministic_context.get("known_flows") or [])
    ledger_by_view = deterministic_context.get("ledger_by_view") or {}
    decisions: list[DiagramPlanningDecision] = []
    candidates: list[DiagramViewCandidate] = []
    seen: set[str] = set()
    for candidate in sorted(proposal.candidate_views, key=lambda item: item.view_id):
        decision, status, reason, ledger_ref, rendered_ref = _validate_candidate(
            candidate,
            deterministic_ids=deterministic_ids,
            rendered_ids=rendered_ids,
            supported_types=supported_types,
            unsupported_ids=unsupported_ids,
            fallback_ids=fallback_ids,
            known_nodes=known_nodes,
            known_flows=known_flows,
            ledger_by_view=ledger_by_view,
            duplicate=candidate.view_id in seen,
        )
        seen.add(candidate.view_id)
        candidates.append(candidate.model_copy(update={"accepted_status": status, "reason": reason}))
        decisions.append(DiagramPlanningDecision(
            view_id=candidate.view_id,
            decision=decision,
            reason=reason,
            compiler_ledger_ref=ledger_ref,
            rendered_view_ref=rendered_ref,
        ))
    for request in sorted(proposal.unsupported_view_requests, key=lambda item: item.requested_view_type):
        ledger_ref = _ledger_ref(request.requested_view_type, ledger_by_view)
        decisions.append(DiagramPlanningDecision(
            view_id=request.requested_view_type,
            decision="unsupported",
            reason=request.disclosure_text or request.reason,
            compiler_ledger_ref=ledger_ref,
        ))
    updated = proposal.model_copy(update={
        "candidate_views": candidates,
        "missing_view_requests": sorted(proposal.missing_view_requests, key=lambda item: item.requested_view_type),
        "unsupported_view_requests": sorted(proposal.unsupported_view_requests, key=lambda item: item.requested_view_type),
        "output_hash": "sha256:pending",
    })
    updated = updated.model_copy(update={"output_hash": stable_json_hash(_proposal_payload(updated))})
    output_hash = stable_json_hash({
        "proposal": _proposal_payload(updated),
        "decisions": [item.model_dump(mode="json") for item in decisions],
        "deterministic_view_plan_ref": _deterministic_view_plan_ref(deterministic_context),
        "compiler_ledger_ref": _compiler_ledger_ref(deterministic_context),
    })
    return DiagramPlanningTrace(
        run_id="diagram_plan_run_" + updated.input_hash.removeprefix("sha256:")[:12],
        enabled=True,
        provider=provider_name,
        deterministic_view_plan_ref=_deterministic_view_plan_ref(deterministic_context),
        compiler_ledger_ref=_compiler_ledger_ref(deterministic_context),
        proposal=updated,
        decisions=decisions,
        input_hash=updated.input_hash,
        output_hash=output_hash,
    )


def diagram_planning_summary_markdown(trace: DiagramPlanningTrace) -> str:
    lines = [
        "# D21 Agentic Diagram Plan",
        "",
        "This audit-only supplement records candidate semantic diagram views. The deterministic ViewPlanner, FlowLedger, Layout IR, D2 compiler, and rendering ledger remain the only diagram authority.",
        "",
        f"**Enabled:** {'Yes' if trace.enabled else 'No'}",
        f"**Provider:** {trace.provider}",
        f"**Run ID:** `{trace.run_id}`",
        f"**Input hash:** `{trace.input_hash}`",
        f"**Output hash:** `{trace.output_hash}`",
        "",
        "## Proposed Views",
        "",
    ]
    if trace.proposal.candidate_views:
        for item in trace.proposal.candidate_views:
            lines.append(f"- `{item.view_id}` ({item.accepted_status}): {item.purpose} {item.reason}".strip())
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Missing / Unsupported View Requests", ""])
    requests = [*trace.proposal.missing_view_requests, *trace.proposal.unsupported_view_requests]
    if requests:
        for item in requests:
            lines.append(f"- `{item.requested_view_type}`: {item.disclosure_text or item.reason}")
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Decisions", ""])
    if trace.decisions:
        for item in trace.decisions:
            rendered = f" rendered=`{item.rendered_view_ref}`" if item.rendered_view_ref else ""
            ledger = f" ledger=`{item.compiler_ledger_ref}`" if item.compiler_ledger_ref else ""
            lines.append(f"- `{item.view_id}`: {item.decision} - {item.reason}{rendered}{ledger}")
    else:
        lines.append("- None recorded.")
    lines.extend(["", "Diagram-planning output is raw/audit-only. It cannot render diagrams, mutate architecture nodes/flows, alter FlowLedger/ViewPlanner/Layout IR/compiler output, change readiness, or write client_pack claims.", ""])
    return "\n".join(lines)


def _validate_candidate(
    candidate: DiagramViewCandidate,
    *,
    deterministic_ids: set[str],
    rendered_ids: set[str],
    supported_types: set[str],
    unsupported_ids: set[str],
    fallback_ids: set[str],
    known_nodes: set[str],
    known_flows: set[str],
    ledger_by_view: dict[str, dict[str, Any]],
    duplicate: bool,
) -> tuple[DiagramDecisionStatus, DiagramAcceptedStatus, str, str | None, str | None]:
    unknown_nodes = sorted(node for node in candidate.intended_nodes if node not in known_nodes)
    if unknown_nodes:
        return "rejected", "conflict", f"Candidate references unknown architecture nodes: {', '.join(unknown_nodes)}.", None, None
    unknown_flows = sorted(flow for flow in candidate.intended_flows if flow not in known_flows)
    if unknown_flows:
        return "rejected", "conflict", f"Candidate references unknown architecture flows: {', '.join(unknown_flows)}.", None, None
    if candidate.requires_architecture_changes:
        return "rejected", "conflict", "Candidate would require architecture node/flow changes, which this lane cannot make.", None, None
    if duplicate:
        return "ignored", "ignored", "Duplicate candidate view ignored; deterministic planning remains authoritative.", None, None
    ledger_ref = _ledger_ref(candidate.view_id, ledger_by_view) or _ledger_ref(candidate.view_type, ledger_by_view)
    if candidate.view_id in unsupported_ids or candidate.view_type not in supported_types and candidate.view_id not in deterministic_ids:
        return "unsupported", "unsupported", "Candidate view is unsupported by the deterministic compiler/view planner and remains audit-only.", ledger_ref, None
    if candidate.claims_rendered and candidate.view_id not in rendered_ids and candidate.view_type not in rendered_ids:
        return "rejected", "conflict", "Candidate claimed rendering without compiler/rendering ledger confirmation.", ledger_ref, None
    if candidate.accepted_status == "fallback":
        if candidate.view_id in fallback_ids or candidate.view_type in fallback_ids or ledger_ref:
            return "fallback_recorded", "fallback", "Fallback/disclosure is backed by the compiler rendering ledger.", ledger_ref, None
        return "rejected", "conflict", "Fallback claim lacks compiler rendering ledger support.", None, None
    if candidate.view_id in rendered_ids or candidate.view_type in rendered_ids:
        rendered = candidate.view_id if candidate.view_id in rendered_ids else candidate.view_type
        return "accepted_for_audit", "accepted", "Candidate matches a deterministic rendered compiler view.", ledger_ref, rendered
    if candidate.view_id in deterministic_ids or candidate.view_type in deterministic_ids:
        return "accepted_for_audit", "accepted", "Candidate matches the deterministic semantic view plan.", ledger_ref, None
    return "ignored", "ignored", "Candidate is audit-only and was not present in deterministic ViewPlanner/compiler output.", ledger_ref, None


def _proposal(
    *,
    proposal_id: str,
    input_hash: str,
    rationale: str,
    candidate_views: list[DiagramViewCandidate] | None = None,
    missing_view_requests: list[DiagramMissingViewRequest] | None = None,
    unsupported_view_requests: list[DiagramMissingViewRequest] | None = None,
    provenance: DiagramPlanProvenance,
) -> DiagramViewPlanProposal:
    proposal = DiagramViewPlanProposal(
        proposal_id=proposal_id,
        candidate_views=sorted(candidate_views or [], key=lambda item: item.view_id),
        missing_view_requests=sorted(missing_view_requests or [], key=lambda item: item.requested_view_type),
        unsupported_view_requests=sorted(unsupported_view_requests or [], key=lambda item: item.requested_view_type),
        rationale=rationale,
        provenance=provenance,
        input_hash=input_hash,
        output_hash="sha256:pending",
    )
    return proposal.model_copy(update={"output_hash": stable_json_hash(_proposal_payload(proposal))})


def _proposal_payload(proposal: DiagramViewPlanProposal) -> dict[str, Any]:
    payload = proposal.model_dump(mode="json")
    payload["output_hash"] = "sha256:self"
    return payload


def _deterministic_view_plan_ref(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "deterministic_view_ids": sorted(str(item) for item in context.get("deterministic_view_ids") or []),
        "rendered_view_ids": sorted(str(item) for item in context.get("rendered_view_ids") or []),
        "supported_view_types": sorted(str(item) for item in context.get("supported_view_types") or []),
    }


def _compiler_ledger_ref(context: dict[str, Any]) -> dict[str, Any]:
    ledger = context.get("compiler_ledger") or {}
    return {
        "ledger_hash": stable_json_hash(ledger),
        "buckets": {key: len(value or []) for key, value in sorted(ledger.items())},
    }


def _ledger_ref(view_id: str, ledger_by_view: dict[str, dict[str, Any]]) -> str | None:
    entry = ledger_by_view.get(view_id)
    if not entry:
        return None
    bucket = entry.get("ledger_bucket") or "unknown"
    mode = entry.get("mode") or "unknown"
    return f"{mode}.{bucket}.{view_id}"
