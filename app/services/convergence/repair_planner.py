from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.domain.quality_findings import QualityFinding


RepairActionType = Literal[
    "fix_classification",
    "extract_missing_metric",
    "replace_pricing_driver_model",
    "add_architecture_component",
    "add_architecture_flow",
    "add_governance_control",
    "replace_service",
    "add_service_decision",
    "fix_provider_catalog",
    "add_diagram_view",
    "rename_diagram_lane",
    "suppress_view_with_reason",
    "invalidate_headline_pricing",
    "regenerate_dossier_section",
    "cap_customer_readiness",
]

RegenerationTarget = Literal["understanding", "pricing", "architecture", "dossier", "diagrams", "export"]


class RepairAction(BaseModel):
    id: str
    finding_ids: list[str]
    action_type: RepairActionType
    target: str
    instructions: str
    requires_regeneration_of: list[RegenerationTarget] = Field(default_factory=list)
    safe_to_apply_automatically: bool = True


class RepairPlan(BaseModel):
    actions: list[RepairAction] = Field(default_factory=list)
    can_auto_apply: bool = True
    requires_user_confirmation: bool = False
    reason_user_confirmation_required: str | None = None
    repairs_applied: int = 0


class RepairPlanner:
    def plan(self, findings: list[QualityFinding]) -> RepairPlan:
        actions: list[RepairAction] = []
        for item in findings:
            if item.repaired or not item.auto_repairable:
                continue
            action = _action_for_finding(item)
            if action:
                actions.append(action)
        unsafe = [item for item in actions if not item.safe_to_apply_automatically]
        return RepairPlan(
            actions=actions,
            can_auto_apply=not unsafe,
            requires_user_confirmation=bool(unsafe),
            reason_user_confirmation_required="One or more repairs would change business or cost posture." if unsafe else None,
        )


def _action_for_finding(item: QualityFinding) -> RepairAction | None:
    if item.category == "governance":
        return RepairAction(
            id=f"repair_{item.id}",
            finding_ids=[item.id],
            action_type="add_governance_control",
            target="architecture.governance_controls",
            instructions=item.repair_strategy or "Run typed governance enrichment and revalidate architecture.",
            requires_regeneration_of=["architecture", "diagrams", "dossier", "export"],
        )
    if item.category == "architecture" and item.code.startswith("architecture."):
        return RepairAction(
            id=f"repair_{item.id}",
            finding_ids=[item.id],
            action_type="add_architecture_component" if "missing_component" in item.code or "latency" in item.code else "add_architecture_flow",
            target="architecture.components",
            instructions=item.repair_strategy or "Apply deterministic workload-specific architecture repair.",
            requires_regeneration_of=["architecture", "diagrams", "dossier", "export"],
        )
    if item.category == "pricing":
        return RepairAction(
            id=f"repair_{item.id}",
            finding_ids=[item.id],
            action_type="invalidate_headline_pricing",
            target="pricing.metadata",
            instructions=item.repair_strategy or "Mark pricing as not headline-safe and cap readiness.",
            requires_regeneration_of=["pricing", "dossier", "export"],
        )
    if item.category == "diagram":
        return RepairAction(
            id=f"repair_{item.id}",
            finding_ids=[item.id],
            action_type="suppress_view_with_reason",
            target="diagrams.missing_requested_views",
            instructions=item.repair_strategy or "Record explicit view suppression reason and readiness impact.",
            requires_regeneration_of=["dossier", "export"],
        )
    return None
