from pydantic import BaseModel, Field

from app.domain.capabilities import ArchitectureCapability
from app.models.domain import ArchitectureComponent


class LaneDefinition(BaseModel):
    lane_id: str
    label: str
    capabilities: list[ArchitectureCapability]
    priority: int
    allowed_component_roles: list[str]


class LanePlan(BaseModel):
    lanes: list[LaneDefinition]
    assignment_reasoning: dict[str, str] = Field(default_factory=dict)


CAPABILITY_LANE_CATALOG = [
    LaneDefinition(
        lane_id="sources_edge",
        label="Sources and edge",
        capabilities=[ArchitectureCapability.DEVICE_TELEMETRY, ArchitectureCapability.EDGE_PROCESSING],
        priority=10,
        allowed_component_roles=["device", "sensor", "edge_gateway", "external_source", "field_asset"],
    ),
    LaneDefinition(
        lane_id="ingestion",
        label="Telemetry ingestion",
        capabilities=[ArchitectureCapability.STREAM_INGESTION, ArchitectureCapability.HIGH_VOLUME_EVENT_INGESTION],
        priority=20,
        allowed_component_roles=["iot_broker", "stream_ingestion", "message_ingestion"],
    ),
    LaneDefinition(
        lane_id="stream_analytics",
        label="Streaming analytics",
        capabilities=[ArchitectureCapability.STREAM_PROCESSING, ArchitectureCapability.FEATURE_ENGINEERING, ArchitectureCapability.REAL_TIME_ANALYTICS],
        priority=30,
        allowed_component_roles=["stream_processor", "feature_extractor", "analytics"],
    ),
    LaneDefinition(
        lane_id="prediction_scoring",
        label="Prediction and scoring",
        capabilities=[ArchitectureCapability.ML_INFERENCE, ArchitectureCapability.REAL_TIME_ANOMALY_DETECTION, ArchitectureCapability.ANOMALY_DETECTION],
        priority=40,
        allowed_component_roles=["model_endpoint", "anomaly_detector", "scoring_service"],
    ),
    LaneDefinition(
        lane_id="workflow_integrations",
        label="Workflow and integrations",
        capabilities=[ArchitectureCapability.EVENT_DRIVEN_ORCHESTRATION, ArchitectureCapability.EXTERNAL_WORKFLOW_INTEGRATION, ArchitectureCapability.INVENTORY_OR_DEPOT_INTEGRATION, ArchitectureCapability.EXTERNAL_SYSTEM_INTEGRATION],
        priority=50,
        allowed_component_roles=["workflow", "queue", "integration_adapter", "external_system", "event_router"],
    ),
    LaneDefinition(
        lane_id="data_model_lifecycle",
        label="Data and model lifecycle",
        capabilities=[ArchitectureCapability.TIME_SERIES_STORAGE, ArchitectureCapability.DATA_LAKE, ArchitectureCapability.ML_TRAINING, ArchitectureCapability.MODEL_MONITORING, ArchitectureCapability.MODEL_REGISTRY],
        priority=60,
        allowed_component_roles=["data_lake", "time_series_store", "training_job", "model_registry", "feature_store", "operational_state"],
    ),
    LaneDefinition(
        lane_id="observability_audit",
        label="Observability and audit",
        capabilities=[ArchitectureCapability.OBSERVABILITY, ArchitectureCapability.AUDIT_TRAIL, ArchitectureCapability.FULL_AUDIT_TRAIL, ArchitectureCapability.SECURITY_GOVERNANCE],
        priority=70,
        allowed_component_roles=["monitoring", "logging", "audit", "kms", "iam", "security"],
    ),
]


ROLE_BY_COMPONENT_ID = {
    "devices": "field_asset",
    "iot": "iot_broker",
    "stream": "stream_ingestion",
    "analytics": "stream_processor",
    "ml": "model_endpoint",
    "events": "event_router",
    "workflow": "workflow",
    "queue": "queue",
    "adapter": "integration_adapter",
    "workforce": "external_system",
    "inventory": "external_system",
    "timeseries": "time_series_store",
    "lake": "data_lake",
    "features": "feature_store",
    "training": "training_job",
    "registry": "model_registry",
    "state": "operational_state",
    "logs": "monitoring",
    "audit": "audit",
    "kms": "kms",
}


def plan_lanes(capabilities: list[str], components: list[ArchitectureComponent]) -> LanePlan:
    capability_values = set(capabilities)
    selected = [
        lane
        for lane in CAPABILITY_LANE_CATALOG
        if any(capability.value in capability_values for capability in lane.capabilities)
        or any(_component_role(component) in lane.allowed_component_roles for component in components)
    ]
    selected = sorted(selected, key=lambda lane: lane.priority)
    reasoning = {}
    for component in components:
        role = _component_role(component)
        for lane in selected:
            if role in lane.allowed_component_roles:
                reasoning[component.id] = f"Assigned to {lane.label} from component role {role}."
                break
    return LanePlan(lanes=selected, assignment_reasoning=reasoning)


def lane_label_for_component(component: ArchitectureComponent, lane_plan: LanePlan) -> str | None:
    role = _component_role(component)
    for lane in lane_plan.lanes:
        if role in lane.allowed_component_roles:
            return lane.label
    return None


def _component_role(component: ArchitectureComponent) -> str:
    return str(component.metadata.get("role") or ROLE_BY_COMPONENT_ID.get(component.id) or component.logical_group or "").lower().replace(" ", "_")


# ---------------------------------------------------------------------------
# Domain-aware lane framework
#
# The generic capability/role lane catalog above stays the default for every
# workload (IoT, web, data, AI, ...). Some domains have a strong, well-known
# operational topology where a domain-specific lane ordering produces a much
# cleaner logical service-flow diagram. Those domains can register a
# ``DomainLaneModel`` here; unknown domains keep the generic fallback.
#
# Important compiler contract: the external diagram compiler only honors a
# fixed set of recognized semantic lane labels for its ``semantic_archway``
# lane template. A domain lane therefore carries BOTH a friendly
# ``semantic_group`` (used for dossier/metadata/grouping) and a
# ``compiler_lane`` that MUST be one of the recognized labels so the compiler
# lays the lane out in the intended column order.
# ---------------------------------------------------------------------------

# Recognized semantic lane labels honored by the external compiler's
# ``semantic_archway`` template, in their canonical left-to-right order.
RECOGNIZED_COMPILER_LANES = (
    "Sources and edge",
    "Telemetry ingestion",
    "Streaming analytics",
    "Prediction and scoring",
    "Workflow and integrations",
    "Data and model lifecycle",
    "Observability and audit",
    "Notifications",
    "Security",
    "External",
)


class DomainLane(BaseModel):
    lane_id: str
    semantic_group: str  # friendly/clinical container label (dossier + metadata)
    compiler_lane: str  # must be one of RECOGNIZED_COMPILER_LANES
    order: int
    sidecar: bool = False
    component_ids: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    services: tuple[str, ...] = ()


class DomainLaneModel(BaseModel):
    model_id: str
    description: str = ""
    lanes: list[DomainLane]

    def lane_for(self, component: ArchitectureComponent) -> "DomainLane | None":
        """Resolve a component to a lane by id, then role intent, then service intent."""
        component_id = component.id
        role = _component_role(component)
        service = str(component.service or "").lower()
        for lane in self.lanes:
            if component_id in lane.component_ids:
                return lane
        for lane in self.lanes:
            if role and role in lane.roles:
                return lane
        for lane in self.lanes:
            if service and service in lane.services:
                return lane
        return None

    @property
    def ordered_compiler_lanes(self) -> list[str]:
        return [lane.compiler_lane for lane in sorted(self.lanes, key=lambda item: item.order)]


# First domain adapter: healthcare OR operations scheduling.
# Clinical flow order: clinical sources -> private integration -> PHI-safe
# operational state -> decision intelligence -> approval/command, with
# governance/observability and the PHI security boundary as sidecars.
HEALTHCARE_OPERATIONS_LANE_MODEL = DomainLaneModel(
    model_id="healthcare_operations_scheduling",
    description=(
        "Healthcare OR operations lanes: Clinical Source Systems -> Private Integration -> "
        "PHI-safe Operational State -> Decision Intelligence -> Approval & Command Center, "
        "with Governance & Observability as a sidecar."
    ),
    lanes=[
        DomainLane(
            lane_id="clinical_sources",
            semantic_group="Clinical Source Systems",
            compiler_lane="Sources and edge",
            order=10,
            component_ids=("ehr", "staffing", "sterile_processing", "occupancy_metadata"),
            roles=("video_metadata_processor",),
        ),
        DomainLane(
            lane_id="private_integration",
            semantic_group="Private Integration",
            compiler_lane="Telemetry ingestion",
            order=20,
            component_ids=("private_connectivity", "adapter"),
            roles=("integration_adapter",),
            services=("direct_connect",),
        ),
        DomainLane(
            lane_id="phi_operational_state",
            semantic_group="PHI-safe Operational State",
            compiler_lane="Streaming analytics",
            order=30,
            component_ids=("events", "queue", "state"),
            roles=("operational_state",),
        ),
        DomainLane(
            lane_id="decision_intelligence",
            semantic_group="Decision Intelligence",
            compiler_lane="Prediction and scoring",
            order=40,
            component_ids=("ml",),
            roles=("model_endpoint", "scoring_service"),
            services=("sagemaker",),
        ),
        DomainLane(
            lane_id="approval_command",
            semantic_group="Approval & Command Center",
            compiler_lane="Workflow and integrations",
            order=50,
            component_ids=("proposed_changes", "policy_evaluator", "workflow", "command_center", "writeback_adapter", "auth"),
            roles=("guardrails", "approved_writeback_adapter", "proposed_action_store"),
            services=("step_functions", "cognito"),
        ),
        DomainLane(
            lane_id="governance_observability",
            semantic_group="Governance & Observability",
            compiler_lane="Observability and audit",
            order=70,
            sidecar=True,
            component_ids=("logs", "audit", "audit_lake"),
            roles=("audit", "audit_evidence_store", "monitoring"),
            services=("cloudwatch", "cloudtrail"),
        ),
        DomainLane(
            lane_id="phi_security_boundary",
            semantic_group="Governance & Observability",
            compiler_lane="Security",
            order=90,
            sidecar=True,
            component_ids=("kms",),
            roles=("kms", "iam"),
            services=("kms",),
        ),
    ],
)


_DOMAIN_LANE_MODELS: tuple[DomainLaneModel, ...] = (HEALTHCARE_OPERATIONS_LANE_MODEL,)


def resolve_domain_lane_model(
    domain: str | None, workload_families: "list[str] | tuple[str, ...] | None"
) -> "DomainLaneModel | None":
    """Select a domain-specific lane model, or None to use the generic fallback."""
    families = set(workload_families or ())
    if "healthcare_operations_scheduling" in families:
        return HEALTHCARE_OPERATIONS_LANE_MODEL
    return None


def apply_domain_lane_model(model: DomainLaneModel, components: list[ArchitectureComponent]) -> dict[str, str]:
    """Assign lanes/groups onto components from a domain lane model.

    Sets the compiler-recognized ``logical_group``/``lane_label`` so the
    diagram compiler lays the lane out in order, while preserving the friendly
    ``semantic_group`` for the dossier/tests. Components the model does not
    recognize keep their existing grouping (generic fallback).
    """
    reasoning: dict[str, str] = {}
    for component in components:
        lane = model.lane_for(component)
        if lane is None:
            continue
        component.logical_group = lane.compiler_lane
        component.metadata["lane_id"] = lane.lane_id
        component.metadata["lane_label"] = lane.compiler_lane
        component.metadata["semantic_group"] = lane.semantic_group
        component.metadata.setdefault("semantic_role", lane.semantic_group)
        if lane.sidecar:
            component.metadata["sidecar"] = True
        reasoning[component.id] = f"{component.id} -> {lane.semantic_group} ({lane.compiler_lane})"
    return reasoning

