from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.services.dossier_manifest import stable_json_hash

ArchitectureProvenance = Literal["deterministic", "catalog_backed", "model_proposed", "derived", "user_input", "skipped"]
ArchitectureConfidence = Literal["low", "medium", "high"]
ArchitectureAcceptedStatus = Literal["proposed", "rejected", "conflict", "needs_review", "pattern_backed"]
ArchitectureStructuralStatus = Literal["pass", "warning", "block", "not_run"]
ArchitectureHumanReviewStatus = Literal["not_reviewed", "approved", "rejected", "needs_revision"]
ArchitectureControlType = Literal[
    "identity",
    "encryption",
    "audit",
    "network",
    "observability",
    "resilience",
    "compliance",
    "approval",
    "data_governance",
]


class ArchitectureHumanReviewGate(BaseModel):
    required: bool = True
    status: ArchitectureHumanReviewStatus = "not_reviewed"
    reviewer: str | None = None
    reviewed_at: str | None = None
    notes: str | None = None


class ArchitectureComponentCandidate(BaseModel):
    component_id: str
    label: str
    service_hint: str | None = None
    role: str
    data_class: str | None = None
    trust_boundary: str | None = None
    confidence_label: ArchitectureConfidence = "medium"
    provenance: ArchitectureProvenance = "model_proposed"
    accepted_status: ArchitectureAcceptedStatus = "proposed"
    reason: str = ""


class ArchitectureFlowCandidate(BaseModel):
    flow_id: str
    source: str
    target: str
    flow_type: str
    data_class: str | None = None
    sync_async: str | None = None
    security_controls: list[str] = Field(default_factory=list)
    confidence_label: ArchitectureConfidence = "medium"
    provenance: ArchitectureProvenance = "model_proposed"
    accepted_status: ArchitectureAcceptedStatus = "proposed"
    reason: str = ""


class ArchitectureControlCandidate(BaseModel):
    control_id: str
    control_type: ArchitectureControlType
    target_components: list[str] = Field(default_factory=list)
    rationale: str
    evidence_refs: list[str] = Field(default_factory=list)
    provenance: ArchitectureProvenance = "model_proposed"
    accepted_status: ArchitectureAcceptedStatus = "proposed"
    reason: str = ""


class ArchitectureCritiqueFinding(BaseModel):
    finding_id: str
    severity: Literal["info", "warning", "block"]
    category: str
    message: str
    target_ref: str | None = None


class ArchitectureCritiqueResult(BaseModel):
    candidate_id: str
    structural_status: ArchitectureStructuralStatus = "not_run"
    findings: list[ArchitectureCritiqueFinding] = Field(default_factory=list)
    missing_boundaries: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    human_review_required: bool = True
    can_affect_client: bool = False
    can_affect_procurement: bool = False


class ArchitectureCandidateDecision(BaseModel):
    target_id: str
    target_type: Literal["component", "flow", "control", "proposal"]
    decision: Literal["accepted_for_audit", "needs_review", "rejected", "blocked_from_authority"]
    reason: str
    deterministic_gate: str


class ArchitectureCandidateProposal(BaseModel):
    proposal_id: str
    lane: Literal["architecture"] = "architecture"
    title: str
    candidate_components: list[ArchitectureComponentCandidate] = Field(default_factory=list)
    candidate_flows: list[ArchitectureFlowCandidate] = Field(default_factory=list)
    trust_boundaries: list[str] = Field(default_factory=list)
    data_classes: list[str] = Field(default_factory=list)
    security_controls: list[ArchitectureControlCandidate] = Field(default_factory=list)
    reliability_controls: list[ArchitectureControlCandidate] = Field(default_factory=list)
    observability_controls: list[ArchitectureControlCandidate] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    human_review_required: bool = True
    procurement_cap: bool = True
    provenance: ArchitectureProvenance = "model_proposed"
    input_hash: str
    output_hash: str


class ArchitectureCandidateTrace(BaseModel):
    run_id: str
    enabled: bool = False
    provider: str
    deterministic_architecture_ref: dict[str, Any] = Field(default_factory=dict)
    critique_ref: dict[str, Any] = Field(default_factory=dict)
    proposal: ArchitectureCandidateProposal
    critique: ArchitectureCritiqueResult
    decisions: list[ArchitectureCandidateDecision] = Field(default_factory=list)
    human_review_gate: ArchitectureHumanReviewGate = Field(default_factory=ArchitectureHumanReviewGate)
    input_hash: str
    output_hash: str
    prompt_hash: str | None = None
    response_hash: str | None = None


class ArchitectureCandidateProvider(Protocol):
    provider_name: str

    def propose(self, context: dict[str, Any]) -> ArchitectureCandidateProposal: ...

    def validate(self, proposal: ArchitectureCandidateProposal, deterministic_context: dict[str, Any]) -> ArchitectureCandidateTrace: ...


class DisabledArchitectureCandidateProvider:
    provider_name = "disabled"

    def trace(self, context: dict[str, Any]) -> ArchitectureCandidateTrace:
        input_hash = stable_json_hash(context)
        proposal = _proposal(
            proposal_id="architecture_candidate_" + input_hash.removeprefix("sha256:")[:12],
            title="Agentic architecture candidate lane disabled",
            input_hash=input_hash,
            provenance="skipped",
            assumptions=["Architecture candidate lane is disabled by feature flag."],
            risks=["No model-proposed architecture candidate was generated."],
            open_questions=["Enable and review the architecture candidate lane only in a controlled audit workflow."],
        )
        critique = ArchitectureCritiqueResult(
            candidate_id=proposal.proposal_id,
            structural_status="not_run",
            findings=[
                ArchitectureCritiqueFinding(
                    finding_id="architecture_candidate_disabled",
                    severity="info",
                    category="feature_flag",
                    message="Agentic architecture candidate lane is disabled by feature flag.",
                    target_ref="ARCHWAY_ENABLE_AGENTIC_ARCHITECTURE",
                )
            ],
        )
        output_hash = _trace_hash(proposal, critique, [], context)
        return ArchitectureCandidateTrace(
            run_id="architecture_candidate_run_" + input_hash.removeprefix("sha256:")[:12],
            enabled=False,
            provider=self.provider_name,
            deterministic_architecture_ref=_deterministic_architecture_ref(context),
            critique_ref=_critique_ref(context),
            proposal=proposal.model_copy(update={"output_hash": stable_json_hash(_proposal_payload(proposal))}),
            critique=critique,
            decisions=[
                ArchitectureCandidateDecision(
                    target_id=proposal.proposal_id,
                    target_type="proposal",
                    decision="blocked_from_authority",
                    reason="Agentic architecture candidate lane is disabled by feature flag.",
                    deterministic_gate="ARCHWAY_ENABLE_AGENTIC_ARCHITECTURE",
                )
            ],
            input_hash=input_hash,
            output_hash=output_hash,
        )


class DeterministicFixtureArchitectureCandidateProvider:
    provider_name = "deterministic_fixture"

    def propose(self, context: dict[str, Any]) -> ArchitectureCandidateProposal:
        input_hash = stable_json_hash(context)
        component_ids = list(context.get("deterministic_component_ids") or ["api"])
        first = component_ids[0]
        second = component_ids[1] if len(component_ids) > 1 else first
        boundary = (context.get("known_trust_boundaries") or ["application"])[0]
        data_class = (context.get("known_data_classes") or ["customer_data"])[0]
        components = [
            ArchitectureComponentCandidate(
                component_id=first,
                label=first.replace("_", " ").title(),
                service_hint=(context.get("deterministic_services") or [None])[0],
                role="Existing deterministic architecture component candidate reference.",
                data_class=data_class,
                trust_boundary=boundary,
                confidence_label="high",
                provenance="derived",
            ),
            ArchitectureComponentCandidate(
                component_id="candidate_resilience_buffer",
                label="Candidate Resilience Buffer",
                service_hint="Amazon SQS",
                role="Audit-only resilience candidate; not inserted into deterministic architecture.",
                data_class=data_class,
                trust_boundary=None,
                confidence_label="medium",
                provenance="model_proposed",
            ),
        ]
        flows = [
            ArchitectureFlowCandidate(
                flow_id="candidate_existing_flow_review",
                source=first,
                target=second,
                flow_type="application_request",
                data_class=data_class,
                sync_async="sync",
                security_controls=["identity", "audit"],
                provenance="derived",
            ),
            ArchitectureFlowCandidate(
                flow_id="candidate_unknown_flow_review",
                source="candidate_resilience_buffer",
                target=second,
                flow_type="async_buffer",
                data_class=data_class,
                sync_async="async",
                security_controls=[],
                provenance="model_proposed",
            ),
        ]
        controls = [
            ArchitectureControlCandidate(
                control_id="candidate_audit_control",
                control_type="audit",
                target_components=[first],
                rationale="Candidate references audit coverage for the deterministic component.",
                evidence_refs=["deterministic_architecture"],
                provenance="derived",
            ),
            ArchitectureControlCandidate(
                control_id="candidate_network_control_unknown",
                control_type="network",
                target_components=["candidate_resilience_buffer"],
                rationale="Candidate network control for a proposed component; remains human-review only.",
                evidence_refs=[],
                provenance="model_proposed",
            ),
        ]
        return _proposal(
            proposal_id="architecture_candidate_" + input_hash.removeprefix("sha256:")[:12],
            title="Audit-only architecture candidate supplement",
            input_hash=input_hash,
            candidate_components=components,
            candidate_flows=flows,
            trust_boundaries=[boundary],
            data_classes=[data_class],
            security_controls=controls,
            reliability_controls=[controls[1]],
            observability_controls=[],
            failure_modes=["Proposed buffer may introduce queue latency and operational dead-letter handling requirements."],
            assumptions=["Candidate is not applied to SemanticArchitectureSpec, FlowLedger, pricing, diagrams, readiness, or client_pack."],
            risks=["Architecture soundness cannot be proven automatically and requires human review."],
            open_questions=["Should a human reviewer promote any candidate into deterministic pattern support?"],
            provenance="derived",
        )

    def validate(self, proposal: ArchitectureCandidateProposal, deterministic_context: dict[str, Any]) -> ArchitectureCandidateTrace:
        return validate_architecture_candidate_proposal(proposal, deterministic_context, provider_name=self.provider_name)


class LiveArchitectureCandidateProvider:
    provider_name = "live_stub"

    def propose(self, context: dict[str, Any]) -> ArchitectureCandidateProposal:
        raise NotImplementedError("Live architecture candidate provider is intentionally unavailable in this audit-only branch.")

    def validate(self, proposal: ArchitectureCandidateProposal, deterministic_context: dict[str, Any]) -> ArchitectureCandidateTrace:
        raise NotImplementedError("Live architecture candidate validation is intentionally unavailable in this branch.")


def build_architecture_candidate_context(
    *,
    architectures: list | None,
    pricing: dict | None = None,
    report: dict | None = None,
) -> dict[str, Any]:
    component_ids: set[str] = set()
    service_names: set[str] = set()
    flow_ids: set[str] = set()
    data_classes: set[str] = set()
    trust_boundaries: set[str] = set()
    critique_payloads: list[dict[str, Any]] = []
    for spec in architectures or []:
        metadata = spec.get("metadata") or {}
        critique = metadata.get("architecture_critique")
        if critique:
            critique_payloads.append({"mode": spec.get("mode"), "architecture_id": spec.get("id"), "critique": critique})
        for component in spec.get("components") or spec.get("selected_services") or []:
            if not isinstance(component, dict):
                continue
            component_id = component.get("id") or component.get("name") or component.get("service")
            if component_id:
                component_ids.add(str(component_id))
            service = component.get("service") or component.get("name")
            if service:
                service_names.add(str(service))
            for key in ("data_class", "data_sensitivity", "classification"):
                if component.get(key):
                    data_classes.add(str(component[key]))
            if component.get("trust_boundary"):
                trust_boundaries.add(str(component["trust_boundary"]))
        for flow in spec.get("flows") or []:
            if not isinstance(flow, dict):
                continue
            if flow.get("id"):
                flow_ids.add(str(flow["id"]))
            if flow.get("source"):
                component_ids.add(str(flow["source"]))
            if flow.get("target"):
                component_ids.add(str(flow["target"]))
            if flow.get("data_class"):
                data_classes.add(str(flow["data_class"]))
            if flow.get("trust_boundary"):
                trust_boundaries.add(str(flow["trust_boundary"]))
    pricing_services = {
        str(item.get("service"))
        for item in (pricing or {}).get("line_items", [])
        if isinstance(item, dict) and item.get("service")
    }
    readiness = (((report or {}).get("metadata") or {}).get("customer_readiness") or {})
    return {
        "deterministic_component_ids": sorted(component_ids),
        "deterministic_services": sorted(service_names),
        "deterministic_flow_ids": sorted(flow_ids),
        "known_data_classes": sorted(data_classes),
        "known_trust_boundaries": sorted(trust_boundaries),
        "pricing_services": sorted(pricing_services),
        "procurement_ready": ((pricing or {}).get("metadata") or {}).get("procurement_ready") is True,
        "readiness_status": readiness.get("status") or readiness.get("tier"),
        "architecture_critique_ref": critique_payloads,
    }


def build_architecture_candidate_trace(
    *,
    settings: Settings,
    context: dict[str, Any],
    provider: ArchitectureCandidateProvider | None = None,
) -> ArchitectureCandidateTrace:
    if not settings.enable_agentic_architecture:
        return DisabledArchitectureCandidateProvider().trace(context)
    provider = provider or DeterministicFixtureArchitectureCandidateProvider()
    proposal = provider.propose(context)
    return provider.validate(proposal, context)


def validate_architecture_candidate_proposal(
    proposal: ArchitectureCandidateProposal,
    deterministic_context: dict[str, Any],
    *,
    provider_name: str,
) -> ArchitectureCandidateTrace:
    known_components = set(deterministic_context.get("deterministic_component_ids") or [])
    known_services = set(deterministic_context.get("deterministic_services") or [])
    known_boundaries = set(deterministic_context.get("known_trust_boundaries") or [])
    known_data_classes = set(deterministic_context.get("known_data_classes") or [])
    decisions: list[ArchitectureCandidateDecision] = []
    findings: list[ArchitectureCritiqueFinding] = []
    unsupported_claims: list[str] = []
    missing_boundaries: list[str] = []
    validated_components: list[ArchitectureComponentCandidate] = []
    validated_flows: list[ArchitectureFlowCandidate] = []
    validated_controls: list[ArchitectureControlCandidate] = []

    for component in sorted(proposal.candidate_components, key=lambda item: item.component_id):
        status, decision, reason = _validate_component(component, known_components, known_services, known_boundaries, known_data_classes)
        validated_components.append(component.model_copy(update={"accepted_status": status, "reason": reason}))
        decisions.append(_decision(component.component_id, "component", decision, reason))
        if not component.trust_boundary:
            missing_boundaries.append(component.component_id)
            findings.append(_finding("warning", "missing_trust_boundary", f"Component `{component.component_id}` lacks a trust boundary.", component.component_id))
        if component.service_hint and component.service_hint not in known_services:
            unsupported_claims.append(f"{component.component_id}:{component.service_hint}")
            findings.append(_finding("warning", "unsupported_service_claim", f"Service hint `{component.service_hint}` is not in deterministic architecture.", component.component_id))

    all_candidate_ids = {item.component_id for item in proposal.candidate_components}
    for flow in sorted(proposal.candidate_flows, key=lambda item: item.flow_id):
        status, decision, reason = _validate_flow(flow, known_components, all_candidate_ids, known_data_classes)
        validated_flows.append(flow.model_copy(update={"accepted_status": status, "reason": reason}))
        decisions.append(_decision(flow.flow_id, "flow", decision, reason))
        if not flow.security_controls:
            findings.append(_finding("warning", "missing_flow_controls", f"Flow `{flow.flow_id}` lacks security controls.", flow.flow_id))
        if flow.data_class and known_data_classes and flow.data_class not in known_data_classes:
            unsupported_claims.append(f"{flow.flow_id}:{flow.data_class}")
            findings.append(_finding("warning", "unknown_data_class", f"Flow `{flow.flow_id}` uses an unknown data class.", flow.flow_id))

    controls = [*proposal.security_controls, *proposal.reliability_controls, *proposal.observability_controls]
    seen_controls: set[str] = set()
    for control in sorted(controls, key=lambda item: (item.control_type, item.control_id)):
        if control.control_id in seen_controls:
            continue
        seen_controls.add(control.control_id)
        status, decision, reason = _validate_control(control, known_components, all_candidate_ids)
        validated_controls.append(control.model_copy(update={"accepted_status": status, "reason": reason}))
        decisions.append(_decision(control.control_id, "control", decision, reason))
        if not control.evidence_refs:
            findings.append(_finding("warning", "missing_control_evidence", f"Control `{control.control_id}` has no evidence reference.", control.control_id))

    missing_control_types = sorted({"identity", "encryption", "audit", "network", "observability"} - {item.control_type for item in controls})
    for control_type in missing_control_types:
        findings.append(_finding("warning", "missing_control_family", f"Candidate set lacks `{control_type}` control coverage.", control_type))

    if proposal.human_review_required is not True:
        findings.append(_finding("block", "human_review_required", "Architecture candidate attempted to remove human-review requirement.", proposal.proposal_id))
    if proposal.procurement_cap is not True:
        findings.append(_finding("block", "procurement_cap", "Architecture candidate attempted to remove procurement cap.", proposal.proposal_id))
    decisions.append(ArchitectureCandidateDecision(
        target_id=proposal.proposal_id,
        target_type="proposal",
        decision="blocked_from_authority",
        reason="Architecture candidates are raw/audit-only and cannot affect client artifacts, readiness, pricing, compiler output, or procurement readiness.",
        deterministic_gate="D21 architecture candidate authority boundary",
    ))

    structural_status: ArchitectureStructuralStatus = "pass"
    if any(item.severity == "block" for item in findings):
        structural_status = "block"
    elif findings or missing_boundaries or unsupported_claims:
        structural_status = "warning"

    critique = ArchitectureCritiqueResult(
        candidate_id=proposal.proposal_id,
        structural_status=structural_status,
        findings=sorted(findings, key=lambda item: (item.severity, item.category, item.finding_id)),
        missing_boundaries=sorted(set(missing_boundaries)),
        unsupported_claims=sorted(set(unsupported_claims)),
        human_review_required=True,
        can_affect_client=False,
        can_affect_procurement=False,
    )
    updated = proposal.model_copy(update={
        "candidate_components": validated_components,
        "candidate_flows": validated_flows,
        "security_controls": [item for item in validated_controls if item.control_type in {"identity", "encryption", "audit", "network", "compliance", "approval", "data_governance"}],
        "reliability_controls": [item for item in validated_controls if item.control_type == "resilience"],
        "observability_controls": [item for item in validated_controls if item.control_type == "observability"],
        "trust_boundaries": sorted(set(proposal.trust_boundaries)),
        "data_classes": sorted(set(proposal.data_classes)),
        "failure_modes": sorted(set(proposal.failure_modes)),
        "assumptions": sorted(set(proposal.assumptions)),
        "risks": sorted(set(proposal.risks)),
        "open_questions": sorted(set(proposal.open_questions)),
        "human_review_required": True,
        "procurement_cap": True,
        "output_hash": "sha256:pending",
    })
    updated = updated.model_copy(update={"output_hash": stable_json_hash(_proposal_payload(updated))})
    output_hash = _trace_hash(updated, critique, decisions, deterministic_context)
    return ArchitectureCandidateTrace(
        run_id="architecture_candidate_run_" + updated.input_hash.removeprefix("sha256:")[:12],
        enabled=True,
        provider=provider_name,
        deterministic_architecture_ref=_deterministic_architecture_ref(deterministic_context),
        critique_ref=_critique_ref(deterministic_context),
        proposal=updated,
        critique=critique,
        decisions=decisions,
        human_review_gate=ArchitectureHumanReviewGate(),
        input_hash=updated.input_hash,
        output_hash=output_hash,
    )


def architecture_candidate_summary_markdown(trace: ArchitectureCandidateTrace) -> str:
    lines = [
        "# D21 Agentic Architecture Candidates",
        "",
        "This audit-only supplement records typed architecture candidates. Candidate content is not applied to deterministic architecture, is not rendered as diagram truth, is not client-facing, and cannot be procurement-ready while model-proposed and unreviewed.",
        "",
        f"**Enabled:** {'Yes' if trace.enabled else 'No'}",
        f"**Provider:** {trace.provider}",
        f"**Run ID:** `{trace.run_id}`",
        f"**Input hash:** `{trace.input_hash}`",
        f"**Output hash:** `{trace.output_hash}`",
        f"**Human review required:** {'Yes' if trace.human_review_gate.required else 'No'}",
        f"**Human review status:** `{trace.human_review_gate.status}`",
        f"**Procurement capped:** {'Yes' if trace.proposal.procurement_cap else 'No'}",
        "",
        "## Proposed Components",
        "",
    ]
    if trace.proposal.candidate_components:
        for item in trace.proposal.candidate_components:
            service = f" service=`{item.service_hint}`" if item.service_hint else ""
            lines.append(f"- `{item.component_id}` ({item.accepted_status}): {item.label}; role={item.role}; boundary={item.trust_boundary or 'missing'};{service} reason={item.reason}")
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Proposed Flows", ""])
    if trace.proposal.candidate_flows:
        for item in trace.proposal.candidate_flows:
            lines.append(f"- `{item.flow_id}` ({item.accepted_status}): `{item.source}` -> `{item.target}`; type={item.flow_type}; controls={', '.join(item.security_controls) or 'missing'}; reason={item.reason}")
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Proposed Controls", ""])
    controls = [*trace.proposal.security_controls, *trace.proposal.reliability_controls, *trace.proposal.observability_controls]
    if controls:
        for item in controls:
            lines.append(f"- `{item.control_id}` ({item.accepted_status}): {item.control_type}; targets={', '.join(item.target_components) or 'none'}; reason={item.reason}")
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Critique Findings", ""])
    if trace.critique.findings:
        for item in trace.critique.findings:
            target = f" target=`{item.target_ref}`" if item.target_ref else ""
            lines.append(f"- [{item.severity}] `{item.category}`: {item.message}{target}")
    else:
        lines.append("- No structural findings recorded.")
    lines.extend(["", "## Missing Boundaries", ""])
    lines.extend([f"- `{item}`" for item in trace.critique.missing_boundaries] or ["- None recorded."])
    lines.extend(["", "## Assumptions", ""])
    lines.extend([f"- {item}" for item in trace.proposal.assumptions] or ["- None recorded."])
    lines.extend(["", "## Risks", ""])
    lines.extend([f"- {item}" for item in trace.proposal.risks] or ["- None recorded."])
    lines.extend(["", "## Open Questions", ""])
    lines.extend([f"- {item}" for item in trace.proposal.open_questions] or ["- None recorded."])
    lines.extend([
        "",
        "## Human Review Gate",
        "",
        f"- Required: {'yes' if trace.human_review_gate.required else 'no'}",
        f"- Status: `{trace.human_review_gate.status}`",
        "",
        "Deterministic critique here is structural only. It does not prove architecture soundness, does not approve client-facing output, and does not grant procurement readiness.",
        "",
    ])
    return "\n".join(lines)


def _proposal(
    *,
    proposal_id: str,
    title: str,
    input_hash: str,
    candidate_components: list[ArchitectureComponentCandidate] | None = None,
    candidate_flows: list[ArchitectureFlowCandidate] | None = None,
    trust_boundaries: list[str] | None = None,
    data_classes: list[str] | None = None,
    security_controls: list[ArchitectureControlCandidate] | None = None,
    reliability_controls: list[ArchitectureControlCandidate] | None = None,
    observability_controls: list[ArchitectureControlCandidate] | None = None,
    failure_modes: list[str] | None = None,
    assumptions: list[str] | None = None,
    risks: list[str] | None = None,
    open_questions: list[str] | None = None,
    provenance: ArchitectureProvenance,
) -> ArchitectureCandidateProposal:
    proposal = ArchitectureCandidateProposal(
        proposal_id=proposal_id,
        title=title,
        candidate_components=sorted(candidate_components or [], key=lambda item: item.component_id),
        candidate_flows=sorted(candidate_flows or [], key=lambda item: item.flow_id),
        trust_boundaries=sorted(set(trust_boundaries or [])),
        data_classes=sorted(set(data_classes or [])),
        security_controls=sorted(security_controls or [], key=lambda item: item.control_id),
        reliability_controls=sorted(reliability_controls or [], key=lambda item: item.control_id),
        observability_controls=sorted(observability_controls or [], key=lambda item: item.control_id),
        failure_modes=sorted(set(failure_modes or [])),
        assumptions=sorted(set(assumptions or [])),
        risks=sorted(set(risks or [])),
        open_questions=sorted(set(open_questions or [])),
        human_review_required=True,
        procurement_cap=True,
        provenance=provenance,
        input_hash=input_hash,
        output_hash="sha256:pending",
    )
    return proposal.model_copy(update={"output_hash": stable_json_hash(_proposal_payload(proposal))})


def _proposal_payload(proposal: ArchitectureCandidateProposal) -> dict[str, Any]:
    payload = proposal.model_dump(mode="json")
    payload["output_hash"] = "sha256:self"
    return payload


def _trace_hash(
    proposal: ArchitectureCandidateProposal,
    critique: ArchitectureCritiqueResult,
    decisions: list[ArchitectureCandidateDecision],
    context: dict[str, Any],
) -> str:
    return stable_json_hash({
        "proposal": _proposal_payload(proposal),
        "critique": critique.model_dump(mode="json"),
        "decisions": [item.model_dump(mode="json") for item in decisions],
        "deterministic_architecture_ref": _deterministic_architecture_ref(context),
        "critique_ref": _critique_ref(context),
        "human_review_gate": ArchitectureHumanReviewGate().model_dump(mode="json"),
    })


def _deterministic_architecture_ref(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "component_ids": sorted(str(item) for item in context.get("deterministic_component_ids") or []),
        "services": sorted(str(item) for item in context.get("deterministic_services") or []),
        "flow_ids": sorted(str(item) for item in context.get("deterministic_flow_ids") or []),
        "pricing_services": sorted(str(item) for item in context.get("pricing_services") or []),
        "procurement_ready": bool(context.get("procurement_ready") is True),
        "readiness_status": context.get("readiness_status"),
    }


def _critique_ref(context: dict[str, Any]) -> dict[str, Any]:
    critiques = context.get("architecture_critique_ref") or []
    return {
        "source": "deterministic_architecture_metadata",
        "count": len(critiques),
        "hash": stable_json_hash(critiques),
        "structural_only": True,
        "design_soundness_requires_human_review": True,
    }


def _validate_component(
    component: ArchitectureComponentCandidate,
    known_components: set[str],
    known_services: set[str],
    known_boundaries: set[str],
    known_data_classes: set[str],
) -> tuple[ArchitectureAcceptedStatus, Literal["accepted_for_audit", "needs_review", "rejected"], str]:
    if component.component_id in known_components and component.provenance in {"derived", "deterministic", "catalog_backed"}:
        return "pattern_backed", "accepted_for_audit", "Component references deterministic architecture and remains audit-only."
    if component.service_hint and component.service_hint not in known_services:
        return "needs_review", "needs_review", "Service hint is not present in deterministic architecture and cannot become architecture truth."
    if component.trust_boundary and known_boundaries and component.trust_boundary not in known_boundaries:
        return "needs_review", "needs_review", "Trust boundary is not present in deterministic architecture context."
    if component.data_class and known_data_classes and component.data_class not in known_data_classes:
        return "needs_review", "needs_review", "Data class is not present in deterministic architecture context."
    if not component.trust_boundary:
        return "needs_review", "needs_review", "Trust boundary must be reviewed before any future promotion."
    return "needs_review", "needs_review", "Architecture component remains a human-review candidate only."


def _validate_flow(
    flow: ArchitectureFlowCandidate,
    known_components: set[str],
    all_candidate_ids: set[str],
    known_data_classes: set[str],
) -> tuple[ArchitectureAcceptedStatus, Literal["accepted_for_audit", "needs_review", "rejected"], str]:
    if flow.source not in known_components or flow.target not in known_components:
        if flow.source in all_candidate_ids or flow.target in all_candidate_ids:
            return "needs_review", "needs_review", "Flow references candidate-only components and cannot enter FlowLedger."
        return "conflict", "rejected", "Flow references unknown deterministic architecture components."
    if flow.data_class and known_data_classes and flow.data_class not in known_data_classes:
        return "needs_review", "needs_review", "Flow data class requires human review."
    if not flow.security_controls:
        return "needs_review", "needs_review", "Flow lacks candidate security controls."
    return "pattern_backed", "accepted_for_audit", "Flow references deterministic components but remains audit-only."


def _validate_control(
    control: ArchitectureControlCandidate,
    known_components: set[str],
    all_candidate_ids: set[str],
) -> tuple[ArchitectureAcceptedStatus, Literal["accepted_for_audit", "needs_review", "rejected"], str]:
    unknown = [item for item in control.target_components if item not in known_components]
    if unknown and all(item not in all_candidate_ids for item in unknown):
        return "conflict", "rejected", "Control targets unknown architecture components."
    if unknown:
        return "needs_review", "needs_review", "Control targets candidate-only components and cannot change governance posture."
    if not control.evidence_refs:
        return "needs_review", "needs_review", "Control lacks deterministic evidence reference."
    return "pattern_backed", "accepted_for_audit", "Control references deterministic architecture context but remains audit-only."


def _decision(
    target_id: str,
    target_type: Literal["component", "flow", "control"],
    decision: Literal["accepted_for_audit", "needs_review", "rejected"],
    reason: str,
) -> ArchitectureCandidateDecision:
    return ArchitectureCandidateDecision(
        target_id=target_id,
        target_type=target_type,
        decision=decision,
        reason=reason,
        deterministic_gate="D21 architecture candidate structural validation",
    )


def _finding(
    severity: Literal["info", "warning", "block"],
    category: str,
    message: str,
    target_ref: str | None,
) -> ArchitectureCritiqueFinding:
    return ArchitectureCritiqueFinding(
        finding_id=stable_json_hash({"severity": severity, "category": category, "message": message, "target": target_ref}).removeprefix("sha256:")[:16],
        severity=severity,
        category=category,
        message=message,
        target_ref=target_ref,
    )
