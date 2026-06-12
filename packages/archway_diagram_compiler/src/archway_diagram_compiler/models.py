"""Public data models for semantic architecture compilation."""

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


PlacementScope = Literal[
    "global_edge",
    "global_edge_control",
    "regional_entry",
    "regional_identity",
    "edge_or_regional_control",
    "vpc_resident",
    "vpc_workload",
    "vpc_data",
    "regional_compute",
    "regional_managed_data",
    "regional_managed_ai",
    "regional_orchestration",
    "regional_security",
    "regional_integration",
    "regional_observability",
    "regional_audit",
    "external_actor",
    "generic_application",
    "observability",
    "audit",
]

Severity = Literal["info", "warning", "error"]
EdgeType = Literal[
    "request",
    "auth",
    "control",
    "data_read",
    "data_write",
    "async",
    "event",
    "notification",
    "secret_access",
    "encryption",
    "audit",
    "observability",
    "private_integration",
    "vpc_endpoint_access",
    "rag_retrieval",
    "model_invocation",
    "agent_orchestration",
    "agent_handoff",
    "tool_invocation",
    "embedding_generation",
    "vector_search",
    "hybrid_search",
    "document_ingestion",
    "document_chunking",
    "document_embedding",
    "memory_read",
    "memory_write",
    "prompt_lookup",
    "guardrail_check",
    "evaluation",
    "human_approval",
    "audit_trace",
    "model_observability",
    "source_reference",
    "media_delivery",
    "media_rights",
    "media_ad_decision",
    "media_qoe",
]


class Diagnostic(BaseModel):
    severity: Severity
    code: str
    message: str
    node_id: Optional[str] = None
    flow_id: Optional[str] = None


class ServiceNode(BaseModel):
    id: str
    name: str
    service: str
    provider: str = "aws"
    scope: Optional[PlacementScope] = None
    region: Optional[str] = None
    vpc_id: Optional[str] = None
    subnet_id: Optional[str] = None
    az: Optional[str] = None
    category: Optional[str] = None
    tags: Dict[str, Any] = Field(default_factory=dict)
    logical_group: Optional[str] = None
    active_active: bool = False
    annotation: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Flow(BaseModel):
    id: str
    source: str
    target: str
    label: Optional[str] = None
    edge_type: Optional[EdgeType] = None
    protocol: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SemanticArchitectureSpec(BaseModel):
    title: str
    nodes: List[ServiceNode]
    flows: List[Flow] = Field(default_factory=list)
    regions: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DiagramView(BaseModel):
    name: str
    title: str
    d2_text: str
    artifact_paths: Dict[str, Path] = Field(default_factory=dict)
    view_id: Optional[str] = None
    view_type: Optional[str] = None
    included_nodes: List[str] = Field(default_factory=list)
    included_flows: List[str] = Field(default_factory=list)
    collapsed_flows: List[str] = Field(default_factory=list)
    omitted_flows_with_reason: Dict[str, str] = Field(default_factory=dict)
    layout_strategy: Optional[str] = None
    qa_status: Optional[str] = None


class UserVisibleArtifact(BaseModel):
    view_id: str
    format: str
    path: Path
    name: str


class QAReport(BaseModel):
    passed: bool
    diagnostics: List[Diagnostic] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)


class DiagramBundle(BaseModel):
    d2_text: str
    artifact_paths: Dict[str, Path] = Field(default_factory=dict)
    diagnostics: List[Diagnostic] = Field(default_factory=list)
    qa_report: QAReport
    views: List[DiagramView] = Field(default_factory=list)
    normalized_spec: SemanticArchitectureSpec
    flow_ledger: Optional["FlowLedger"] = None
    layout_models: List["LayoutModel"] = Field(default_factory=list)
    user_visible_artifacts: List[UserVisibleArtifact] = Field(default_factory=list)


class ServiceInfo(BaseModel):
    service: str
    provider: str
    placement_scope: str
    category: str
    icon: Optional[str] = None
    can_be_vpc_resident: bool = False
    endpoint_type: Optional[str] = None


class IconRef(BaseModel):
    service: str
    path: Optional[str] = None
    fallback: Optional[str] = None


class FlowClassification(BaseModel):
    flow_id: str
    edge_type: EdgeType
    reason: str


FlowLedgerStatus = Literal[
    "rendered_explicitly",
    "collapsed_into_group",
    "rendered_in_another_view",
    "omitted_with_reason",
]


class FlowLedgerEntry(BaseModel):
    flow_id: str
    source: str
    target: str
    label: Optional[str] = None
    classification: EdgeType
    status: FlowLedgerStatus
    view_id: Optional[str] = None
    group_id: Optional[str] = None
    reason: Optional[str] = None


class FlowLedger(BaseModel):
    entries: List[FlowLedgerEntry] = Field(default_factory=list)


class LayoutGroup(BaseModel):
    id: str
    label: str
    parent_id: Optional[str] = None
    group_type: str
    order: int


class LayoutLane(BaseModel):
    id: str
    label: str
    group_id: str
    order: int
    orientation: Literal["vertical", "horizontal"]
    max_nodes: int = 24


class LayoutNode(BaseModel):
    id: str
    source_node_ids: List[str]
    label: str
    subtitle: Optional[str] = None
    service: str
    provider: str
    icon: Optional[str] = None
    lane_id: str
    rank: int
    order: int
    placement_scope: str
    role: str
    is_virtual: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LayoutEdge(BaseModel):
    id: str
    source: str
    target: str
    source_flow_ids: List[str]
    label: Optional[str] = None
    edge_type: EdgeType
    style: Literal["solid", "dashed", "dotted"] = "solid"
    route_preference: Literal["orthogonal", "straight"] = "orthogonal"
    criticality: Literal["primary", "secondary", "annotation"] = "primary"
    metadata: Dict[str, Any] = Field(default_factory=dict)


ParallelGroupType = Literal[
    "homogeneous_fanout",
    "endpoint_access_group",
    "tool_fanout",
    "data_access_group",
    "observability_access_group",
    "security_access_group",
]

ParallelRenderMode = Literal[
    "summary_only",
    "bus_and_branches",
    "detail_grid",
    "side_by_side_branches",
]

PreferredDirection = Literal["left_to_right", "top_to_bottom"]


class LayoutParallelGroup(BaseModel):
    id: str
    source_node_id: str
    group_label: str
    group_type: ParallelGroupType
    branch_node_ids: List[str] = Field(default_factory=list)
    target_node_ids: List[str] = Field(default_factory=list)
    source_flow_ids: List[str] = Field(default_factory=list)
    render_mode: ParallelRenderMode = "bus_and_branches"
    preferred_direction: PreferredDirection = "left_to_right"
    max_branches_per_lane: int = 4
    detail_view_id: Optional[str] = None


class LayoutRank(BaseModel):
    id: str
    node_ids: List[str]
    order: int


class LayoutConstraint(BaseModel):
    type: str
    nodes: List[str]
    value: Dict[str, Any] = Field(default_factory=dict)


class LayoutModel(BaseModel):
    view_id: str
    title: str
    groups: List[LayoutGroup] = Field(default_factory=list)
    lanes: List[LayoutLane] = Field(default_factory=list)
    nodes: List[LayoutNode] = Field(default_factory=list)
    edges: List[LayoutEdge] = Field(default_factory=list)
    parallel_groups: List[LayoutParallelGroup] = Field(default_factory=list)
    ranks: List[LayoutRank] = Field(default_factory=list)
    constraints: List[LayoutConstraint] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


if hasattr(DiagramBundle, "model_rebuild"):
    DiagramBundle.model_rebuild()
else:
    DiagramBundle.update_forward_refs()
