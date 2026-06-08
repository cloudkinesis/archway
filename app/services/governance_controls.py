from __future__ import annotations

from dataclasses import dataclass

from app.models.domain import ArchitectureFlow, ArchitectureSpec, GovernanceControl


EFFECTFUL_ACTION_MARKERS: dict[str, tuple[str, ...]] = {
    "create": ("create", "submit", "submission", "open case", "ticket"),
    "update": ("update", "modify", "rollout", "coordinate ota"),
    "delete": ("delete", "remove", "purge", "decommission"),
    "dispatch": ("dispatch", "route crew", "send crew", "ground stop"),
    "pre_position": ("pre-position", "preposition", "stage inventory", "replacement equipment"),
    "external_write": ("external_write", "write", "external api", "adapter call"),
    "policy_change": ("policy change", "policy update", "guardrail change", "threshold change"),
    "trade_block": ("block transaction", "trade block", "pre-trade", "kill order", "bid submission", "submit bid"),
    "device_update": ("device update", "ota", "firmware", "rollout", "configuration push"),
    "network_change": ("network change", "slice lifecycle", "traffic shaping", "nssf", "smf"),
}

HIGH_IMPACT_ACTIONS = {"delete", "dispatch", "pre_position", "trade_block", "device_update", "network_change", "policy_change"}
REVERSIBLE_ACTIONS = {"delete", "trade_block", "device_update", "network_change", "policy_change"}


@dataclass(frozen=True)
class EffectfulFlow:
    flow: ArchitectureFlow
    action_type: str
    impact_level: str


class GovernanceControlEnricher:
    """Adds typed governance controls for effectful architecture flows."""

    def enrich_specs(self, specs: list[ArchitectureSpec]) -> list[ArchitectureSpec]:
        return [self.enrich_spec(spec) for spec in specs]

    def enrich_spec(self, spec: ArchitectureSpec) -> ArchitectureSpec:
        updated = spec.model_copy(deep=True)
        effectful = classify_effectful_flows(updated.flows)
        if not effectful:
            updated.metadata = {
                **updated.metadata,
                "governance_enrichment": {
                    "effectful_flow_count": 0,
                    "auto_added_control_count": 0,
                    "unresolved_flow_ids": [],
                },
            }
            return updated

        for item in effectful:
            item.flow.metadata = {
                **item.flow.metadata,
                "effectful_action": True,
                "governance_action_type": item.action_type,
                "action_type": item.flow.metadata.get("action_type") or item.action_type,
                "impact_level": item.impact_level,
            }

        existing = {
            (control.control_type, tuple(sorted(control.governed_flow_ids)))
            for control in updated.governance_controls
        }
        added = 0
        for control in _required_controls(effectful):
            key = (control.control_type, tuple(sorted(control.governed_flow_ids)))
            if key not in existing:
                updated.governance_controls.append(control)
                existing.add(key)
                added += 1

        unresolved = unresolved_effectful_flow_ids(updated)
        if unresolved:
            _convert_unresolved_to_recommendation_only(updated, unresolved)
            unresolved = unresolved_effectful_flow_ids(updated)

        updated.metadata = {
            **updated.metadata,
            "governance_enrichment": {
                "effectful_flow_count": len(effectful),
                "auto_added_control_count": added,
                "unresolved_flow_ids": unresolved,
                "action_types": sorted({item.action_type for item in effectful}),
            },
        }
        return updated


def classify_effectful_flows(flows: list[ArchitectureFlow]) -> list[EffectfulFlow]:
    classified: list[EffectfulFlow] = []
    for flow in flows:
        action_type = _action_type(flow)
        if action_type:
            classified.append(EffectfulFlow(flow=flow, action_type=action_type, impact_level=_impact_level(flow, action_type)))
    return classified


def unresolved_effectful_flow_ids(spec: ArchitectureSpec) -> list[str]:
    effectful = classify_effectful_flows(spec.flows)
    unresolved = []
    for item in effectful:
        if item.flow.metadata.get("recommendation_only"):
            continue
        controls = [
            control
            for control in spec.governance_controls
            if item.flow.id in control.governed_flow_ids or item.action_type in control.action_types
        ]
        present = {control.control_type for control in controls}
        required = _required_control_types(item.action_type, item.impact_level)
        if not required <= present:
            unresolved.append(item.flow.id)
    return sorted(set(unresolved))


def _required_controls(effectful: list[EffectfulFlow]) -> list[GovernanceControl]:
    controls: list[GovernanceControl] = []
    for action_type in sorted({item.action_type for item in effectful}):
        group = [item for item in effectful if item.action_type == action_type]
        flow_ids = sorted({item.flow.id for item in group})
        impact = _max_impact(item.impact_level for item in group)
        for control_type in sorted(_required_control_types(action_type, impact)):
            controls.append(
                GovernanceControl(
                    id=f"gov_{action_type}_{control_type}",
                    control_type=control_type,
                    name=_control_name(control_type, action_type),
                    rationale=_control_rationale(control_type, action_type, impact),
                    governed_flow_ids=flow_ids,
                    action_types=[action_type],
                    impact_level=impact,
                    enforcement=_enforcement(control_type),
                    enforcement_point=_enforcement_point(action_type, control_type),
                    failure_behavior=_failure_behavior(action_type, control_type, impact),
                    metadata={"auto_added": True, "source": "governance_control_enricher"},
                )
            )
    return controls


def _required_control_types(action_type: str, impact_level: str) -> set[str]:
    required = {"audit_trail", "policy_approval", "automated_guardrail"}
    if action_type in HIGH_IMPACT_ACTIONS or impact_level in {"high", "critical"}:
        required.update({"human_approval", "manual_override"})
    if action_type in REVERSIBLE_ACTIONS or impact_level == "critical":
        required.update({"kill_switch", "rollback"})
    return required


def _action_type(flow: ArchitectureFlow) -> str | None:
    classification = str(flow.metadata.get("classification", "")).lower()
    label = (flow.label or "").lower()
    text = f"{classification} {label}"
    for action_type, markers in EFFECTFUL_ACTION_MARKERS.items():
        if any(marker in text for marker in markers):
            return action_type
    return None


def _impact_level(flow: ArchitectureFlow, action_type: str) -> str:
    text = f"{flow.label or ''} {flow.metadata}".lower()
    if any(term in text for term in ("safety", "catastrophic", "kill switch", "public", "customer-impacting")):
        return "critical"
    if action_type in HIGH_IMPACT_ACTIONS or any(term in text for term in ("external", "dispatch", "device", "trade", "network", "policy")):
        return "high"
    if action_type in {"create", "update", "external_write"}:
        return "medium"
    return "low"


def _max_impact(levels) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return max(levels, key=lambda level: order.get(level, 1))


def _control_name(control_type: str, action_type: str) -> str:
    labels = {
        "human_approval": "Human approval",
        "policy_approval": "Policy approval",
        "automated_guardrail": "Automated guardrail",
        "kill_switch": "Kill switch",
        "rollback": "Rollback",
        "manual_override": "Manual override",
        "audit_trail": "Audit trail",
    }
    return f"{labels[control_type]} for {action_type.replace('_', ' ')} actions"


def _control_rationale(control_type: str, action_type: str, impact_level: str) -> str:
    return (
        f"Required for {impact_level}-impact {action_type.replace('_', ' ')} flows so effectful AWS or external-system actions "
        "are bounded by approval, policy, recovery, and evidence controls."
    )


def _enforcement(control_type: str) -> str:
    if control_type == "human_approval":
        return "manual"
    if control_type in {"audit_trail", "automated_guardrail", "kill_switch", "rollback"}:
        return "automated"
    return "policy"


def _enforcement_point(action_type: str, control_type: str) -> str:
    if action_type in {"trade_block", "policy_change"}:
        return "policy decision point before external submission"
    if action_type in {"device_update", "network_change"}:
        return "change orchestration workflow before rollout"
    if action_type in {"dispatch", "pre_position"}:
        return "workflow state machine before external system write"
    if control_type == "audit_trail":
        return "append-only audit event stream"
    return "integration adapter policy check"


def _failure_behavior(action_type: str, control_type: str, impact_level: str) -> str:
    if control_type == "rollback":
        return "rollback"
    if control_type == "audit_trail":
        return "allow_with_audit"
    if action_type in {"trade_block", "device_update", "network_change"} or impact_level == "critical":
        return "block"
    return "queue_for_review"


def _convert_unresolved_to_recommendation_only(spec: ArchitectureSpec, unresolved_flow_ids: list[str]) -> None:
    for flow in spec.flows:
        if flow.id not in unresolved_flow_ids:
            continue
        flow.metadata = {
            **flow.metadata,
            "recommendation_only": True,
            "governance_safe_variant": "Action is queued for review instead of executed directly.",
        }
        prefix = "Recommend / queue for review"
        if flow.label and not flow.label.lower().startswith("recommend"):
            flow.label = f"{prefix}: {flow.label}"
