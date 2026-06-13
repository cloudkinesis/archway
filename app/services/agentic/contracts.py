from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.dossier_manifest import stable_json_hash
from app.services.agentic.provenance import AgentProvenance, MODEL_PROPOSED, can_write_surface

AgentLane = Literal[
    "deterministic_baseline",
    "repair_planner",
    "research",
    "use_case_analyst",
    "pricing",
    "narrative",
    "reviewer",
    "diagram_planner",
    "architecture",
]

AgentTaskStatus = Literal["proposed", "skipped", "accepted", "downgraded", "rejected", "failed"]
AgentDecisionStatus = Literal["accepted", "downgraded", "marked_assumed", "rejected"]
AgentClaimKind = Literal["architecture", "pricing", "aws_docs", "aws_pricing", "diagram", "narrative", "repair"]
AgentTargetSurface = Literal["raw", "audit_pack", "client_pack"]
AgentEvidenceSourceType = Literal[
    "aws_docs",
    "aws_pricing",
    "catalog",
    "deterministic_ledger",
    "user_input",
    "scenario_profile",
    "model",
]
AgentFindingSeverity = Literal["blocker", "warning", "advisory", "info"]
CompletenessOutcome = Literal["solution_package", "directional_diagnostic_package", "unsupported_refusal_package"]

AGENTIC_LANES: tuple[AgentLane, ...] = (
    "repair_planner",
    "research",
    "use_case_analyst",
    "pricing",
    "narrative",
    "reviewer",
    "diagram_planner",
    "architecture",
)


class AgentEvidenceRef(BaseModel):
    source_type: AgentEvidenceSourceType
    source_id: str
    citation: str | None = None
    claim_kind: AgentClaimKind


class AgentTask(BaseModel):
    task_id: str
    lane: AgentLane
    purpose: str
    input_refs: list[str] = Field(default_factory=list)
    status: AgentTaskStatus


class AgentProposal(BaseModel):
    proposal_id: str
    lane: AgentLane
    provenance: AgentProvenance = MODEL_PROPOSED
    claim_kind: AgentClaimKind
    content: dict[str, Any]
    evidence_refs: list[AgentEvidenceRef] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    target_surface: AgentTargetSurface = "raw"
    allowed_client_surface: bool = False

    def model_post_init(self, __context: Any) -> None:
        if self.provenance == MODEL_PROPOSED and self.target_surface == "client_pack" and not self.allowed_client_surface:
            raise ValueError("model_proposed proposals cannot target client_pack without deterministic upgrade")

    @property
    def content_hash(self) -> str:
        return stable_json_hash(self.model_dump(mode="json"))


class AgentDecision(BaseModel):
    proposal_id: str
    decision: AgentDecisionStatus
    reason: str
    deterministic_gate: str


class AgentFinding(BaseModel):
    lane: AgentLane
    severity: AgentFindingSeverity
    rule_id: str
    message: str
    target_artifact: str | None = None


class AgentRepairAction(BaseModel):
    action_id: str
    action: str
    source_signal: str
    target_artifact: str | None = None
    lane: AgentLane = "repair_planner"


class AgentRepairPlan(BaseModel):
    tier_from: str | None = None
    tier_to: str | None = None
    actions: list[AgentRepairAction] = Field(default_factory=list)
    source_signals: list[str] = Field(default_factory=list)


class ArtifactCompletenessState(BaseModel):
    outcome: CompletenessOutcome
    missing_evidence: list[str] = Field(default_factory=list)
    missing_pricing_drivers: list[str] = Field(default_factory=list)
    diagram_fallbacks: list[str] = Field(default_factory=list)
    readiness_reasons: list[str] = Field(default_factory=list)
    repair_plan: AgentRepairPlan


class AgentRun(BaseModel):
    run_id: str
    enabled_lanes: list[AgentLane] = Field(default_factory=list)
    model_provider: str = "deterministic"
    model_id: str | None = None
    prompt_hash: str | None = None
    response_hash: str | None = None
    input_hash: str
    started_at: str | None = None
    tasks: list[AgentTask] = Field(default_factory=list)
    decisions: list[AgentDecision] = Field(default_factory=list)
    findings: list[AgentFinding] = Field(default_factory=list)

    @property
    def trace_hash(self) -> str:
        return stable_json_hash(self.model_dump(mode="json"))


def surface_allowed(proposal: AgentProposal, surface: AgentTargetSurface, *, upgraded: bool = False) -> bool:
    return can_write_surface(proposal.provenance, surface, upgraded=upgraded)
