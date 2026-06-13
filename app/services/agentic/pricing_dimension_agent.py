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

PricingConfidence = Literal["low", "medium", "high"]
PricingProvenance = Literal["deterministic", "catalog_backed", "model_proposed", "user_input", "derived", "scenario_profile"]
PricingAcceptedStatus = Literal["proposed", "accepted", "downgraded", "rejected", "conflict", "assumed"]
PricingDriverStatus = Literal["proposed", "assumed", "missing", "derived", "confirmed_candidate"]
PricingSourceRequirement = Literal["aws_pricing", "catalog", "scenario_profile", "unknown"]
PricingBindingLabel = Literal[
    "bound",
    "scenario_assumed",
    "ambiguous",
    "not_estimated",
    "unsupported",
    "missing_quantity",
    "unit_mismatch",
]


class PricingServiceCandidate(BaseModel):
    service_name: str
    aws_service_code: str | None = None
    confidence_label: PricingConfidence = "medium"
    provenance: PricingProvenance = "model_proposed"
    reason: str
    accepted_status: PricingAcceptedStatus = "proposed"


class PricingUsageDimensionCandidate(BaseModel):
    dimension_id: str
    service_name: str
    aws_service_code: str | None = None
    usage_name: str | None = None
    unit: str | None = None
    formula: str | None = None
    required_rate_dimensions: dict[str, str] = Field(default_factory=dict)
    required_customer_drivers: list[str] = Field(default_factory=list)
    source_requirement: PricingSourceRequirement = "unknown"
    evidence_refs: list[str] = Field(default_factory=list)
    confidence_label: PricingConfidence = "medium"
    provenance: PricingProvenance = "model_proposed"
    accepted_status: PricingAcceptedStatus = "proposed"
    binding_label: PricingBindingLabel = "not_estimated"
    ambiguity_reason: str | None = None


class PricingDriverCandidate(BaseModel):
    driver_key: str
    display_label: str
    unit: str | None = None
    required_for: list[str] = Field(default_factory=list)
    status: PricingDriverStatus = "proposed"
    scenario_default: str | int | float | bool | None = None
    source: Literal["user_input", "scenario_profile", "deterministic_default", "derived", "model_proposed"] = "model_proposed"
    reason: str


class PricingScenarioProfile(BaseModel):
    profile_id: str
    label: str
    assumptions: list[str] = Field(default_factory=list)
    source: Literal["scenario_profile"] = "scenario_profile"
    intended_use: Literal["small_pilot", "department", "enterprise", "custom"] = "custom"
    confidence_label: PricingConfidence = "medium"


class PricingDimensionProposal(BaseModel):
    proposal_id: str
    lane: Literal["pricing_dimension"] = "pricing_dimension"
    service_candidates: list[PricingServiceCandidate] = Field(default_factory=list)
    usage_dimensions: list[PricingUsageDimensionCandidate] = Field(default_factory=list)
    required_drivers: list[PricingDriverCandidate] = Field(default_factory=list)
    scenario_profiles: list[PricingScenarioProfile] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    not_estimated_reasons: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    provenance: PricingProvenance = "model_proposed"
    input_hash: str
    output_hash: str


class PricingDimensionTrace(BaseModel):
    run_id: str
    enabled: bool = False
    provider: str
    deterministic_pricing_ref: dict[str, Any] = Field(default_factory=dict)
    use_case_analyst_ref: dict[str, Any] | None = None
    proposal: PricingDimensionProposal
    decisions: list[AgentDecision] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    input_hash: str
    output_hash: str
    prompt_hash: str | None = None
    response_hash: str | None = None
    live_call: LiveCallAudit | None = None


class PricingDimensionProvider(Protocol):
    provider_name: str

    def propose(self, context: dict[str, Any]) -> PricingDimensionProposal: ...

    def validate(self, proposal: PricingDimensionProposal, deterministic_context: dict[str, Any]) -> PricingDimensionTrace: ...


class DisabledPricingDimensionProvider:
    provider_name = "disabled"

    def trace(self, context: dict[str, Any]) -> PricingDimensionTrace:
        input_hash = stable_json_hash(context)
        proposal = _proposal(
            proposal_id="pricing_dim_proposal_" + input_hash.removeprefix("sha256:")[:12],
            input_hash=input_hash,
            provenance="deterministic",
        )
        output_hash = stable_json_hash({
            "deterministic_pricing_ref": _deterministic_pricing_ref(context),
            "proposal": proposal.model_dump(mode="json"),
        })
        return PricingDimensionTrace(
            run_id="pricing_dim_run_" + input_hash.removeprefix("sha256:")[:12],
            enabled=False,
            provider=self.provider_name,
            deterministic_pricing_ref=_deterministic_pricing_ref(context),
            use_case_analyst_ref=_use_case_analyst_ref(context),
            proposal=proposal.model_copy(update={"output_hash": output_hash}),
            decisions=[
                AgentDecision(
                    proposal_id=proposal.proposal_id,
                    decision="rejected",
                    reason="Agentic pricing-dimension lane is disabled by feature flag.",
                    deterministic_gate="ARCHWAY_ENABLE_AGENTIC_PRICING",
                )
            ],
            input_hash=input_hash,
            output_hash=output_hash,
        )


class DeterministicFixturePricingDimensionProvider:
    provider_name = "deterministic_fixture"

    def propose(self, context: dict[str, Any]) -> PricingDimensionProposal:
        input_hash = stable_json_hash(context)
        specs = list(context.get("dimension_fixture_specs") or [])
        services = _service_candidates(specs, context)
        dimensions = [_dimension_from_spec(spec) for spec in specs]
        drivers = _driver_candidates(specs)
        scenario_profiles = _scenario_profiles(specs)
        proposal = _proposal(
            proposal_id="pricing_dim_proposal_" + input_hash.removeprefix("sha256:")[:12],
            input_hash=input_hash,
            provenance="derived",
            service_candidates=services,
            usage_dimensions=dimensions,
            required_drivers=drivers,
            scenario_profiles=scenario_profiles,
            assumptions=_scenario_assumptions(drivers),
            ambiguities=sorted({item.ambiguity_reason for item in dimensions if item.ambiguity_reason}),
            not_estimated_reasons=sorted({
                item.ambiguity_reason or f"{item.service_name} dimension is not estimated."
                for item in dimensions
                if item.binding_label in {"not_estimated", "unsupported"}
            }),
        )
        return proposal.model_copy(update={"output_hash": stable_json_hash(_proposal_payload(proposal))})

    def validate(self, proposal: PricingDimensionProposal, deterministic_context: dict[str, Any]) -> PricingDimensionTrace:
        return validate_pricing_dimension_proposal(proposal, deterministic_context, provider_name=self.provider_name)


class LivePricingDimensionProvider:
    provider_name = "bedrock"

    def __init__(self, *, session_id: str | None = None, run_context: LiveRunContext | None = None, sensitivity_text: str | None = None):
        self.session_id = session_id
        self.run_context = run_context
        self.sensitivity_text = sensitivity_text
        self.last_call: LiveCallAudit | None = None

    def propose(self, context: dict[str, Any]) -> PricingDimensionProposal:
        input_hash = stable_json_hash(context)
        messages = [
            LLMMessage(role="system", content=(
                "You are Archway's live pricing-dimension analyst. Return JSON only. "
                "Propose generic AWS service usage dimensions, required customer drivers, "
                "ambiguities, and scenario assumptions. Do not produce totals or procurement claims."
            )),
            LLMMessage(role="user", content=json.dumps(context, default=str)[:22000]),
        ]
        result = live_call(
            LLMTaskType.live_pricing_dimension,
            messages,
            PricingDimensionProposal,
            session_id=self.session_id,
            lane="pricing_dimension",
            run_context=self.run_context,
            sensitivity_text=self.sensitivity_text,
        )
        self.last_call = result.audit
        if isinstance(result.parsed, PricingDimensionProposal):
            proposal = result.parsed
            return proposal.model_copy(update={
                "input_hash": proposal.input_hash or input_hash,
                "output_hash": stable_json_hash(_proposal_payload(proposal)),
            })
        proposal = _proposal(
            proposal_id="pricing_dim_proposal_" + input_hash.removeprefix("sha256:")[:12],
            input_hash=input_hash,
            provenance="model_proposed",
            not_estimated_reasons=[result.audit.error_message or result.audit.skip_reason or "Live pricing-dimension response was not usable."],
        )
        return proposal.model_copy(update={"output_hash": stable_json_hash(_proposal_payload(proposal))})

    def validate(self, proposal: PricingDimensionProposal, deterministic_context: dict[str, Any]) -> PricingDimensionTrace:
        trace = validate_pricing_dimension_proposal(proposal, deterministic_context, provider_name=self.provider_name)
        if self.last_call:
            trace = trace.model_copy(update={
                "provider": self.last_call.provider,
                "prompt_hash": self.last_call.prompt_hash,
                "response_hash": self.last_call.response_hash,
                "live_call": self.last_call,
            })
        return trace


def build_pricing_dimension_context(
    *,
    pricing: dict | None,
    architectures: list | None,
    use_case_analyst_trace: Any | None = None,
    fixture_specs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    metadata = (pricing or {}).get("metadata") or {}
    services = sorted({
        str(component.get("service") or component.get("name"))
        for spec in architectures or []
        for component in (spec.get("components") or spec.get("selected_services") or [])
        if isinstance(component, dict) and (component.get("service") or component.get("name"))
    })
    return {
        "services": services,
        "pricing": {
            "headline_safe": metadata.get("pricing_can_be_displayed_as_headline") is True,
            "low_monthly_usd": (pricing or {}).get("low_monthly_usd"),
            "expected_monthly_usd": (pricing or {}).get("expected_monthly_usd"),
            "high_monthly_usd": (pricing or {}).get("high_monthly_usd"),
        },
        "pricing_driver_closure": metadata.get("pricing_driver_closure") or {},
        "service_usage_dimensions": metadata.get("service_usage_dimensions") or [],
        "pricing_driver_bindings": metadata.get("pricing_driver_bindings") or [],
        "aws_rate_bindings": metadata.get("aws_rate_bindings") or [],
        "use_case_analyst": _trace_ref(use_case_analyst_trace),
        "dimension_fixture_specs": fixture_specs or [],
    }


def build_pricing_dimension_trace(
    *,
    settings: Settings,
    context: dict[str, Any],
    provider: PricingDimensionProvider | None = None,
    live_run_context: LiveRunContext | None = None,
    session_id: str | None = None,
    sensitivity_text: str | None = None,
) -> PricingDimensionTrace:
    if not settings.enable_agentic_pricing:
        return DisabledPricingDimensionProvider().trace(context)
    if provider is None and settings.agentic_mode == "live_demo":
        provider = LivePricingDimensionProvider(session_id=session_id, run_context=live_run_context, sensitivity_text=sensitivity_text)
    provider = provider or DeterministicFixturePricingDimensionProvider()
    proposal = provider.propose(context)
    return provider.validate(proposal, context)


def validate_pricing_dimension_proposal(
    proposal: PricingDimensionProposal,
    deterministic_context: dict[str, Any],
    *,
    provider_name: str,
) -> PricingDimensionTrace:
    pricing_ref = _deterministic_pricing_ref(deterministic_context)
    confirmed_drivers = set(pricing_ref.get("confirmed_driver_keys") or [])
    bound_dimensions = set(pricing_ref.get("bound_dimension_ids") or [])
    conflicts: list[str] = list(proposal.conflicts)
    dimensions: list[PricingUsageDimensionCandidate] = []
    for dimension in proposal.usage_dimensions:
        label = _dimension_binding_label(dimension, confirmed_drivers, bound_dimensions)
        status: PricingAcceptedStatus = "accepted" if label == "bound" else "downgraded"
        reason = dimension.ambiguity_reason
        if label == "missing_quantity":
            reason = reason or f"{dimension.dimension_id} requires missing customer quantity."
        elif label == "ambiguous":
            reason = reason or f"{dimension.dimension_id} has multiple plausible usage names or units."
        elif label in {"not_estimated", "unsupported"}:
            reason = reason or f"{dimension.service_name} is not deterministically bound by pricing."
        dimensions.append(dimension.model_copy(update={
            "binding_label": label,
            "accepted_status": status,
            "ambiguity_reason": reason,
        }))
    drivers = [
        driver.model_copy(update={"status": "confirmed_candidate" if driver.driver_key in confirmed_drivers else driver.status})
        for driver in proposal.required_drivers
    ]
    if any(item.binding_label == "bound" and item.dimension_id not in bound_dimensions for item in dimensions):
        conflicts.append("Agent proposal attempted to mark an unbound dimension as bound.")
    updated = proposal.model_copy(update={
        "usage_dimensions": sorted(dimensions, key=lambda item: (item.service_name, item.dimension_id)),
        "required_drivers": sorted(drivers, key=lambda item: item.driver_key),
        "ambiguities": sorted(set(proposal.ambiguities) | {item.ambiguity_reason for item in dimensions if item.binding_label == "ambiguous" and item.ambiguity_reason}),
        "not_estimated_reasons": sorted(set(proposal.not_estimated_reasons) | {item.ambiguity_reason for item in dimensions if item.binding_label in {"not_estimated", "unsupported"} and item.ambiguity_reason}),
        "conflicts": sorted(set(conflicts)),
    })
    decision_reason = "Pricing-dimension output remains raw/audit-only and cannot change pricing math or headline pricing."
    if conflicts:
        decision_reason = "Pricing-dimension proposal conflicted with deterministic pricing state; conflicts were recorded and not applied."
    decisions = [
        AgentDecision(
            proposal_id=updated.proposal_id,
            decision="downgraded",
            reason=decision_reason,
            deterministic_gate="D21 pricing-dimension audit-only lane",
        )
    ]
    proposal_hash = stable_json_hash(_proposal_payload(updated))
    updated = updated.model_copy(update={"output_hash": proposal_hash})
    output_hash = stable_json_hash({
        "deterministic_pricing_ref": pricing_ref,
        "use_case_analyst_ref": _use_case_analyst_ref(deterministic_context),
        "proposal": _proposal_payload(updated),
        "decisions": [item.model_dump(mode="json") for item in decisions],
        "conflicts": sorted(set(conflicts)),
    })
    return PricingDimensionTrace(
        run_id="pricing_dim_run_" + updated.input_hash.removeprefix("sha256:")[:12],
        enabled=True,
        provider=provider_name,
        deterministic_pricing_ref=pricing_ref,
        use_case_analyst_ref=_use_case_analyst_ref(deterministic_context),
        proposal=updated,
        decisions=decisions,
        conflicts=sorted(set(conflicts)),
        input_hash=updated.input_hash,
        output_hash=output_hash,
    )


def pricing_dimension_summary_markdown(trace: PricingDimensionTrace) -> str:
    proposal = trace.proposal
    lines = [
        "# D21 Agentic Pricing-Dimension Supplement",
        "",
        "This audit-only supplement records candidate pricing dimensions and driver questions. It is not client-facing pricing authority and does not change pricing math, headline pricing, readiness, architecture, governance, or diagram truth.",
        "",
        f"**Enabled:** {'Yes' if trace.enabled else 'No'}",
        f"**Provider:** {trace.provider}",
        f"**Run ID:** `{trace.run_id}`",
        f"**Input hash:** `{trace.input_hash}`",
        f"**Output hash:** `{trace.output_hash}`",
        "",
        "## Deterministic Pricing Facts",
        "",
        f"- Bound dimensions: {len(trace.deterministic_pricing_ref.get('bound_dimension_ids') or [])}",
        f"- Confirmed drivers: {len(trace.deterministic_pricing_ref.get('confirmed_driver_keys') or [])}",
        "",
        "## Proposed Dimensions",
        "",
    ]
    if proposal.usage_dimensions:
        for item in proposal.usage_dimensions:
            lines.append(f"- {item.service_name} / `{item.dimension_id}`: {item.binding_label}; unit={item.unit or 'unknown'}; drivers={', '.join(item.required_customer_drivers) or 'none'}")
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Missing Drivers", ""])
    missing = [item for item in proposal.required_drivers if item.status == "missing"]
    if missing:
        lines.extend(f"- {item.display_label} (`{item.driver_key}`): {item.reason}" for item in missing)
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Scenario Assumptions", ""])
    assumed = [item for item in proposal.required_drivers if item.status == "assumed"]
    if assumed or proposal.scenario_profiles:
        lines.extend(f"- {item.display_label} (`{item.driver_key}`): {item.scenario_default} {item.unit or ''}".strip() for item in assumed)
        for profile in proposal.scenario_profiles:
            lines.append(f"- {profile.label} (`{profile.profile_id}`): {', '.join(profile.assumptions) or 'no assumptions recorded'}")
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Ambiguous Dimensions", ""])
    if proposal.ambiguities:
        lines.extend(f"- {item}" for item in proposal.ambiguities)
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Not-Estimated Services / Dimensions", ""])
    if proposal.not_estimated_reasons:
        lines.extend(f"- {item}" for item in proposal.not_estimated_reasons)
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Conflicts", ""])
    if trace.conflicts:
        lines.extend(f"- {item}" for item in trace.conflicts)
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Follow-up Questions", ""])
    questions: list[str] = []
    questions.extend(f"Confirm {item.display_label} for {', '.join(item.required_for) or 'the proposed dimension'}." for item in missing)
    questions.extend(f"Resolve ambiguity: {item}" for item in proposal.ambiguities)
    if questions:
        lines.extend(f"- {item}" for item in sorted(set(questions)))
    else:
        lines.append("- None recorded.")
    lines.extend(["", "Pricing-dimension output remains raw/audit-only in this branch.", ""])
    return "\n".join(lines)


def _proposal(
    *,
    proposal_id: str,
    input_hash: str,
    provenance: PricingProvenance,
    service_candidates: list[PricingServiceCandidate] | None = None,
    usage_dimensions: list[PricingUsageDimensionCandidate] | None = None,
    required_drivers: list[PricingDriverCandidate] | None = None,
    scenario_profiles: list[PricingScenarioProfile] | None = None,
    assumptions: list[str] | None = None,
    ambiguities: list[str] | None = None,
    not_estimated_reasons: list[str] | None = None,
    conflicts: list[str] | None = None,
) -> PricingDimensionProposal:
    base = PricingDimensionProposal(
        proposal_id=proposal_id,
        service_candidates=sorted(service_candidates or [], key=lambda item: (item.service_name, item.aws_service_code or "")),
        usage_dimensions=sorted(usage_dimensions or [], key=lambda item: (item.service_name, item.dimension_id)),
        required_drivers=sorted(required_drivers or [], key=lambda item: item.driver_key),
        scenario_profiles=sorted(scenario_profiles or [], key=lambda item: item.profile_id),
        assumptions=sorted(set(assumptions or [])),
        ambiguities=sorted(set(ambiguities or [])),
        not_estimated_reasons=sorted(set(not_estimated_reasons or [])),
        conflicts=sorted(set(conflicts or [])),
        provenance=provenance,
        input_hash=input_hash,
        output_hash="sha256:pending",
    )
    return base.model_copy(update={"output_hash": stable_json_hash(_proposal_payload(base))})


def _proposal_payload(proposal: PricingDimensionProposal) -> dict[str, Any]:
    payload = proposal.model_dump(mode="json")
    payload["output_hash"] = "sha256:self"
    return payload


def _service_candidates(specs: list[dict[str, Any]], context: dict[str, Any]) -> list[PricingServiceCandidate]:
    services = {
        str(spec.get("service_name")): spec.get("aws_service_code")
        for spec in specs
        if spec.get("service_name")
    }
    for service in context.get("services") or []:
        services.setdefault(str(service), None)
    return [
        PricingServiceCandidate(
            service_name=name,
            aws_service_code=str(code) if code else None,
            confidence_label="medium",
            provenance="derived",
            reason="Candidate service for pricing-dimension discovery; does not alter architecture.",
        )
        for name, code in sorted(services.items())
    ]


def _dimension_from_spec(spec: dict[str, Any]) -> PricingUsageDimensionCandidate:
    return PricingUsageDimensionCandidate(
        dimension_id=str(spec.get("dimension_id") or _slug(f"{spec.get('service_name')}_{spec.get('usage_name') or 'dimension'}")),
        service_name=str(spec.get("service_name") or "unknown_service"),
        aws_service_code=str(spec["aws_service_code"]) if spec.get("aws_service_code") else None,
        usage_name=str(spec["usage_name"]) if spec.get("usage_name") else None,
        unit=str(spec["unit"]) if spec.get("unit") else None,
        formula=str(spec["formula"]) if spec.get("formula") else None,
        required_rate_dimensions={str(k): str(v) for k, v in (spec.get("required_rate_dimensions") or {}).items()},
        required_customer_drivers=sorted(str(item) for item in spec.get("required_customer_drivers") or []),
        source_requirement=spec.get("source_requirement") or "unknown",
        evidence_refs=sorted(str(item) for item in spec.get("evidence_refs") or []),
        confidence_label=spec.get("confidence_label") or "medium",
        provenance=spec.get("provenance") or "derived",
        binding_label=spec.get("binding_label") or "not_estimated",
        ambiguity_reason=spec.get("ambiguity_reason"),
    )


def _driver_candidates(specs: list[dict[str, Any]]) -> list[PricingDriverCandidate]:
    drivers: dict[str, PricingDriverCandidate] = {}
    for spec in specs:
        dimension_id = str(spec.get("dimension_id") or _slug(f"{spec.get('service_name')}_{spec.get('usage_name') or 'dimension'}"))
        for driver in spec.get("drivers") or []:
            key = str(driver.get("driver_key") or _slug(driver.get("display_label") or "driver"))
            existing = drivers.get(key)
            required_for = sorted(set((existing.required_for if existing else []) + [dimension_id]))
            drivers[key] = PricingDriverCandidate(
                driver_key=key,
                display_label=str(driver.get("display_label") or key),
                unit=str(driver["unit"]) if driver.get("unit") else None,
                required_for=required_for,
                status=driver.get("status") or "missing",
                scenario_default=driver.get("scenario_default"),
                source=driver.get("source") or "model_proposed",
                reason=str(driver.get("reason") or "Required pricing driver candidate."),
            )
    return sorted(drivers.values(), key=lambda item: item.driver_key)


def _scenario_profiles(specs: list[dict[str, Any]]) -> list[PricingScenarioProfile]:
    profiles: dict[str, PricingScenarioProfile] = {}
    for spec in specs:
        for profile in spec.get("scenario_profiles") or []:
            profile_id = str(profile.get("profile_id") or "scenario_profile")
            profiles[profile_id] = PricingScenarioProfile(
                profile_id=profile_id,
                label=str(profile.get("label") or profile_id),
                assumptions=sorted(str(item) for item in profile.get("assumptions") or []),
                intended_use=profile.get("intended_use") or "custom",
                confidence_label=profile.get("confidence_label") or "medium",
            )
    return sorted(profiles.values(), key=lambda item: item.profile_id)


def _scenario_assumptions(drivers: list[PricingDriverCandidate]) -> list[str]:
    return sorted(
        f"{item.display_label} assumed from scenario profile: {item.scenario_default} {item.unit or ''}".strip()
        for item in drivers
        if item.status == "assumed"
    )


def _dimension_binding_label(
    dimension: PricingUsageDimensionCandidate,
    confirmed_drivers: set[str],
    bound_dimensions: set[str],
) -> PricingBindingLabel:
    if dimension.dimension_id in bound_dimensions:
        return "bound"
    if not dimension.aws_service_code or dimension.source_requirement == "unknown":
        return "not_estimated"
    if dimension.ambiguity_reason:
        return "ambiguous"
    if dimension.source_requirement == "aws_pricing" and not dimension.evidence_refs:
        return "unsupported"
    if dimension.provenance == "scenario_profile" or dimension.source_requirement == "scenario_profile":
        return "scenario_assumed"
    missing = [driver for driver in dimension.required_customer_drivers if driver not in confirmed_drivers]
    if missing:
        return "missing_quantity"
    if not dimension.unit:
        return "unit_mismatch"
    return "not_estimated"


def _deterministic_pricing_ref(context: dict[str, Any]) -> dict[str, Any]:
    dimensions = context.get("service_usage_dimensions") or []
    bindings = context.get("pricing_driver_bindings") or []
    rate_bindings = context.get("aws_rate_bindings") or []
    return {
        "bound_dimension_ids": sorted(
            str(item.get("id") or item.get("dimension_id"))
            for item in dimensions
            if isinstance(item, dict) and item.get("binding_status") == "bound"
        ),
        "confirmed_driver_keys": sorted(
            str(item.get("driver_name") or item.get("driver_key"))
            for item in bindings
            if isinstance(item, dict) and item.get("status") == "confirmed"
        ),
        "rate_binding_statuses": sorted(
            str(item.get("binding_status"))
            for item in rate_bindings
            if isinstance(item, dict) and item.get("binding_status")
        ),
        "headline_safe": ((context.get("pricing") or {}).get("headline_safe") is True),
    }


def _use_case_analyst_ref(context: dict[str, Any]) -> dict[str, Any] | None:
    ref = context.get("use_case_analyst")
    return ref if isinstance(ref, dict) else None


def _trace_ref(trace: Any | None) -> dict[str, Any] | None:
    if trace is None:
        return None
    if isinstance(trace, dict):
        return {
            "run_id": trace.get("run_id"),
            "output_hash": trace.get("output_hash"),
            "provider": trace.get("provider"),
        }
    return {
        "run_id": getattr(trace, "run_id", None),
        "output_hash": getattr(trace, "output_hash", None),
        "provider": getattr(trace, "provider", None),
    }


def _slug(value: str) -> str:
    out = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value)).strip("_")
    while "__" in out:
        out = out.replace("__", "_")
    return out or "unknown"
