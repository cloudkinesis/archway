from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


GENERIC_FALLBACK_FAMILY = "web_api_application"
OPEN_WORLD_PROFILE_SOURCE = "open_world_understanding"


@dataclass(frozen=True)
class ClientFacingPlan:
    """Selection result for the client-facing candidate presentation layer.

    This object is intentionally plain data. It decides only whether existing
    candidate traces may be summarized in the client pack; it does not mutate
    architecture, pricing, diagram rendering, readiness, or verifier state.
    """

    tier: Literal["deterministic", "candidate"]
    reason: str
    architecture_candidate: dict[str, Any] = field(default_factory=dict)
    pricing_candidate: dict[str, Any] = field(default_factory=dict)
    diagram_candidate: dict[str, Any] = field(default_factory=dict)
    narrative_candidate: dict[str, Any] = field(default_factory=dict)
    reviewer_candidate: dict[str, Any] = field(default_factory=dict)
    readiness_cap: str | None = None

    @property
    def is_candidate(self) -> bool:
        return self.tier == "candidate"


def build_client_facing_plan(
    *,
    profile_metadata: dict | None,
    architecture_candidate_trace: Any | None = None,
    pricing_dimension_trace: Any | None = None,
    diagram_plan_trace: Any | None = None,
    narrative_trace: Any | None = None,
    reviewer_trace: Any | None = None,
) -> ClientFacingPlan:
    """Choose deterministic or labeled-candidate client presentation.

    Candidate mode is deliberately narrow:
    - the workload profile must be an open-world broad fallback;
    - an architecture candidate must have an accepted live call and useful
      proposal content;
    - optional companion candidate lanes are surfaced only when their own live
      call was accepted.
    """

    profile = profile_metadata or {}
    if not _is_open_world_fallback(profile):
        return ClientFacingPlan(
            tier="deterministic",
            reason="Profile resolved to a deterministic workload path.",
        )

    architecture = _candidate_payload(architecture_candidate_trace)
    if not architecture or not _architecture_has_content(architecture):
        return ClientFacingPlan(
            tier="deterministic",
            reason="No accepted live architecture candidate is available for client presentation.",
        )

    return ClientFacingPlan(
        tier="candidate",
        reason="Open-world fallback profile with accepted live candidate traces.",
        architecture_candidate=architecture,
        pricing_candidate=_candidate_payload(pricing_dimension_trace),
        diagram_candidate=_candidate_payload(diagram_plan_trace),
        narrative_candidate=_candidate_payload(narrative_trace),
        reviewer_candidate=_reviewer_payload(reviewer_trace),
        readiness_cap="demo_ready",
    )


def _is_open_world_fallback(profile: dict[str, Any]) -> bool:
    families = [str(item) for item in profile.get("workload_families") or [] if item]
    primary = str(profile.get("primary_family") or (families[0] if families else "")).strip()
    source = str(profile.get("profile_source") or "").strip()
    has_open_world_payload = bool(profile.get("open_world_understanding"))
    return (
        primary == GENERIC_FALLBACK_FAMILY
        and (source == OPEN_WORLD_PROFILE_SOURCE or has_open_world_payload)
    )


def _candidate_payload(trace: Any | None) -> dict[str, Any]:
    trace_map = _as_mapping(trace)
    if not trace_map or not _accepted_live_trace(trace_map):
        return {}
    proposal = _as_mapping(trace_map.get("proposal"))
    if not proposal:
        return {}
    payload = dict(proposal)
    for key in ("critique", "human_review_gate", "decisions", "conflicts"):
        value = trace_map.get(key)
        if value:
            payload[key] = value
    return payload


def _reviewer_payload(trace: Any | None) -> dict[str, Any]:
    trace_map = _as_mapping(trace)
    if not trace_map or not _accepted_live_trace(trace_map):
        return {}
    findings = trace_map.get("accepted_findings") or []
    if not findings:
        return {}
    return {"accepted_findings": list(findings)}


def _accepted_live_trace(trace: dict[str, Any]) -> bool:
    live_call = _as_mapping(trace.get("live_call"))
    provider = str(live_call.get("provider") or trace.get("provider") or "")
    status = str(live_call.get("status") or "")
    return bool(trace.get("enabled")) and provider == "bedrock" and status == "accepted"


def _architecture_has_content(proposal: dict[str, Any]) -> bool:
    return any(
        proposal.get(key)
        for key in (
            "candidate_components",
            "candidate_flows",
            "security_controls",
            "reliability_controls",
            "observability_controls",
        )
    )


def _as_mapping(value: Any | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return {}
