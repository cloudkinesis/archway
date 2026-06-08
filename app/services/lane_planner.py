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

