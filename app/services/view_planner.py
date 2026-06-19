from enum import Enum
from pydantic import BaseModel

from app.domain.capabilities import ArchitectureCapability


class DiagramViewType(str, Enum):
    LOGICAL_SERVICE_FLOW = "logical_service_flow"
    LIVE_MEDIA_DELIVERY = "live_media_delivery_view"
    MEDIA_RIGHTS_AD_DECISIONING = "media_rights_ad_decisioning_view"
    MEDIA_QOE_ANALYTICS = "media_qoe_analytics_view"
    TELEMETRY_INGESTION = "telemetry_ingestion_view"
    STREAM_PROCESSING = "stream_processing_view"
    PREDICTIVE_FAILURE_DETECTION = "predictive_failure_detection_view"
    DISPATCH_WORKFLOW = "dispatch_workflow_view"
    APPROVAL_WORKFLOW = "approval_workflow_view"
    DATA_LAKE_MODEL_LIFECYCLE = "data_lake_model_lifecycle_view"
    SECURITY_OBSERVABILITY = "security_observability_view"
    NETWORK_PRIVATE_CONNECTIVITY = "network_private_connectivity_view"
    RAG_RETRIEVAL = "rag_retrieval_view"
    RAG_INGESTION = "rag_ingestion_view"
    AGENT_TOOL_EXECUTION = "agent_tool_execution_view"


class DiagramViewMapping(BaseModel):
    semantic_view_id: str
    compiler_view_id: str
    user_title: str
    user_description: str
    rendered_as_native_view: bool
    fallback_reason: str | None = None


SEMANTIC_TO_COMPILER_VIEW = {
    DiagramViewType.LOGICAL_SERVICE_FLOW.value: "production_logical_service_flow",
    DiagramViewType.LIVE_MEDIA_DELIVERY.value: "live_media_delivery_view",
    DiagramViewType.MEDIA_RIGHTS_AD_DECISIONING.value: "media_rights_ad_decisioning_view",
    DiagramViewType.MEDIA_QOE_ANALYTICS.value: "media_qoe_analytics_view",
    DiagramViewType.TELEMETRY_INGESTION.value: "async_flow_view",
    DiagramViewType.STREAM_PROCESSING.value: "async_flow_view",
    DiagramViewType.PREDICTIVE_FAILURE_DETECTION.value: "ai_security_governance_view",
    DiagramViewType.DISPATCH_WORKFLOW.value: "async_flow_view",
    DiagramViewType.APPROVAL_WORKFLOW.value: "ai_security_governance_view",
    DiagramViewType.DATA_LAKE_MODEL_LIFECYCLE.value: "data_access_view",
    DiagramViewType.SECURITY_OBSERVABILITY.value: "security_observability_controls",
    DiagramViewType.NETWORK_PRIVATE_CONNECTIVITY.value: "network_private_connectivity",
    DiagramViewType.RAG_RETRIEVAL.value: "rag_retrieval_view",
    DiagramViewType.RAG_INGESTION.value: "data_access_view",
    DiagramViewType.AGENT_TOOL_EXECUTION.value: "agent_tool_execution_view",
}


NATIVE_COMPILER_EQUIVALENTS = {
    DiagramViewType.NETWORK_PRIVATE_CONNECTIVITY.value: "network_private_connectivity",
}


VIEW_COPY = {
    DiagramViewType.LOGICAL_SERVICE_FLOW.value: (
        "Production Service Flow",
        "Primary AWS service topology and the major workload responsibilities each service owns.",
    ),
    DiagramViewType.LIVE_MEDIA_DELIVERY.value: (
        "Live Ingest, Encoding, And Origin Packaging",
        "Live feed contribution, channel encoding, origin packaging, CDN delivery, and edge request path.",
    ),
    DiagramViewType.MEDIA_RIGHTS_AD_DECISIONING.value: (
        "DRM, Geo-Rights, Blackout, Consent, And Ads",
        "Playback protection, entitlement/blackout policy, privacy consent, and server-side ad decision flow.",
    ),
    DiagramViewType.MEDIA_QOE_ANALYTICS.value: (
        "QoE Telemetry And Latency Monitoring",
        "Playback quality, startup time, rebuffering, latency, archive, audit, and operational signal flow.",
    ),
    DiagramViewType.TELEMETRY_INGESTION.value: (
        "Telemetry Ingestion",
        "How devices, applications, or producers enter the platform and are buffered for downstream processing.",
    ),
    DiagramViewType.STREAM_PROCESSING.value: (
        "Streaming Analytics",
        "Real-time processing, feature extraction, and event enrichment before storage, action, or model invocation.",
    ),
    DiagramViewType.PREDICTIVE_FAILURE_DETECTION.value: (
        "AI Detection And Governance",
        "Model invocation, monitoring, audit, and controls around automated or human-approved decisions.",
    ),
    DiagramViewType.DISPATCH_WORKFLOW.value: (
        "Dispatch And Integration Workflow",
        "Event, queue, workflow, and adapter path used for downstream operational actions.",
    ),
    DiagramViewType.APPROVAL_WORKFLOW.value: (
        "Approval, Obligation, And Metadata Workflow",
        "Approval gates, obligation review, metadata update, tool execution, and audit paths for governed workflow actions.",
    ),
    DiagramViewType.DATA_LAKE_MODEL_LIFECYCLE.value: (
        "Data Lake And Model Lifecycle",
        "Storage, curated datasets, training data, retention, replay, and analytical access paths.",
    ),
    DiagramViewType.SECURITY_OBSERVABILITY.value: (
        "Security And Observability Controls",
        "Identity, encryption, audit, monitoring, and operational control responsibilities.",
    ),
    DiagramViewType.NETWORK_PRIVATE_CONNECTIVITY.value: (
        "Network And Private Connectivity",
        "Private access, integration boundaries, external systems, and managed-service connectivity posture.",
    ),
    DiagramViewType.RAG_RETRIEVAL.value: (
        "RAG Retrieval Flow",
        "How source content is retrieved and grounded before model generation.",
    ),
    DiagramViewType.RAG_INGESTION.value: (
        "Knowledge Ingestion Flow",
        "Document ingestion, processing, chunking, indexing, and retention path.",
    ),
    DiagramViewType.AGENT_TOOL_EXECUTION.value: (
        "Agent Tool Execution",
        "Tool approval, invocation, state, and audit path for governed agentic actions.",
    ),
}


def plan_semantic_views(capabilities: list[str], *, production: bool, network_required: bool = False) -> list[str]:
    caps = set(capabilities)
    views = [DiagramViewType.LOGICAL_SERVICE_FLOW.value]
    is_video_streaming = ArchitectureCapability.VIDEO_STREAMING.value in caps
    if is_video_streaming:
        views.extend([
            DiagramViewType.LIVE_MEDIA_DELIVERY.value,
            DiagramViewType.MEDIA_RIGHTS_AD_DECISIONING.value,
            DiagramViewType.MEDIA_QOE_ANALYTICS.value,
        ])
    if not is_video_streaming and _has(caps, ArchitectureCapability.DEVICE_TELEMETRY, ArchitectureCapability.STREAM_INGESTION):
        views.append(DiagramViewType.TELEMETRY_INGESTION.value)
    if not is_video_streaming and _has(caps, ArchitectureCapability.STREAM_PROCESSING, ArchitectureCapability.FEATURE_ENGINEERING):
        views.append(DiagramViewType.STREAM_PROCESSING.value)
    if _has(caps, ArchitectureCapability.ML_INFERENCE, ArchitectureCapability.REAL_TIME_ANOMALY_DETECTION, ArchitectureCapability.ANOMALY_DETECTION):
        views.append(DiagramViewType.PREDICTIVE_FAILURE_DETECTION.value)
    if _has(caps, ArchitectureCapability.EVENT_DRIVEN_ORCHESTRATION, ArchitectureCapability.EXTERNAL_WORKFLOW_INTEGRATION, ArchitectureCapability.EXTERNAL_SYSTEM_INTEGRATION):
        if _has(caps, ArchitectureCapability.HUMAN_APPROVAL, ArchitectureCapability.SECURITY_GOVERNANCE, ArchitectureCapability.RAG_RETRIEVAL, ArchitectureCapability.DOCUMENT_INGESTION, ArchitectureCapability.AGENT_TOOL_EXECUTION):
            views.append(DiagramViewType.APPROVAL_WORKFLOW.value)
        else:
            views.append(DiagramViewType.DISPATCH_WORKFLOW.value)
    if ArchitectureCapability.INVENTORY_OR_DEPOT_INTEGRATION.value in caps and DiagramViewType.DISPATCH_WORKFLOW.value not in views:
        views.append(DiagramViewType.DISPATCH_WORKFLOW.value)
    if not is_video_streaming and _has(caps, ArchitectureCapability.DATA_LAKE, ArchitectureCapability.ML_TRAINING, ArchitectureCapability.MODEL_MONITORING, ArchitectureCapability.TIME_SERIES_STORAGE):
        views.append(DiagramViewType.DATA_LAKE_MODEL_LIFECYCLE.value)
    if _has(caps, ArchitectureCapability.SECURITY_GOVERNANCE, ArchitectureCapability.AUDIT_TRAIL, ArchitectureCapability.FULL_AUDIT_TRAIL, ArchitectureCapability.OBSERVABILITY):
        views.append(DiagramViewType.SECURITY_OBSERVABILITY.value)
    if network_required or production and _has(caps, ArchitectureCapability.PRIVATE_CONNECTIVITY, ArchitectureCapability.EXTERNAL_SYSTEM_INTEGRATION):
        views.append(DiagramViewType.NETWORK_PRIVATE_CONNECTIVITY.value)
    if ArchitectureCapability.RAG_RETRIEVAL.value in caps:
        views.append(DiagramViewType.RAG_RETRIEVAL.value)
    if ArchitectureCapability.DOCUMENT_INGESTION.value in caps:
        views.append(DiagramViewType.RAG_INGESTION.value)
    if ArchitectureCapability.AGENT_TOOL_EXECUTION.value in caps:
        views.append(DiagramViewType.AGENT_TOOL_EXECUTION.value)
    return list(dict.fromkeys(views))


def compiler_views_for_semantic(semantic_views: list[str]) -> list[str]:
    views = ["production_logical_service_flow"]
    for view in semantic_views:
        compiler_view = SEMANTIC_TO_COMPILER_VIEW.get(view)
        if compiler_view:
            views.append(compiler_view)
    return list(dict.fromkeys(views))


def semantic_to_compiler_mapping(semantic_views: list[str]) -> dict[str, str]:
    return {
        view: SEMANTIC_TO_COMPILER_VIEW.get(view, "unsupported_by_current_compiler")
        for view in semantic_views
    }


def diagram_view_mappings(semantic_views: list[str], workload_title: str | None = None) -> list[DiagramViewMapping]:
    compiler_counts: dict[str, int] = {}
    for view in semantic_views:
        compiler_id = SEMANTIC_TO_COMPILER_VIEW.get(view, "unsupported_by_current_compiler")
        compiler_counts[compiler_id] = compiler_counts.get(compiler_id, 0) + 1
    mappings: list[DiagramViewMapping] = []
    for view in semantic_views:
        compiler_id = SEMANTIC_TO_COMPILER_VIEW.get(view, "unsupported_by_current_compiler")
        title, description = VIEW_COPY.get(view, (view.replace("_", " ").title(), "Customer-requested architecture view."))
        title = _workload_title(title, workload_title)
        native = compiler_id == view or NATIVE_COMPILER_EQUIVALENTS.get(view) == compiler_id
        fallback_reason = None
        if compiler_id == "unsupported_by_current_compiler":
            fallback_reason = "No dedicated rendered view exists for this semantic view yet."
        elif not native:
            fallback_reason = (
                "Rendered through the closest supported architecture view. "
                "The semantic intent is preserved in metadata and diagram titles."
            )
        mappings.append(
            DiagramViewMapping(
                semantic_view_id=view,
                compiler_view_id=compiler_id,
                user_title=title,
                user_description=description,
                rendered_as_native_view=native,
                fallback_reason=fallback_reason,
            )
        )
    return mappings


def _workload_title(title: str, workload_title: str | None) -> str:
    if not workload_title:
        return title
    generic_prefixes = ("Production", "Telemetry", "Streaming", "AI", "Dispatch", "Data", "Security", "Network", "RAG", "Knowledge", "Agent")
    if title.startswith(generic_prefixes):
        return f"{workload_title} - {title}"
    return title


def customer_title_for_compiler_view(compiler_view_id: str, mappings: list[dict] | list[DiagramViewMapping]) -> str:
    candidates = [
        mapping if isinstance(mapping, DiagramViewMapping) else DiagramViewMapping(**mapping)
        for mapping in mappings
        if (mapping.compiler_view_id if isinstance(mapping, DiagramViewMapping) else mapping.get("compiler_view_id")) == compiler_view_id
    ]
    if not candidates:
        return compiler_view_id.replace("_", " ").title()
    native = [mapping for mapping in candidates if mapping.rendered_as_native_view]
    selected = native[0] if native else candidates[0]
    if len(candidates) > 1 and not native:
        return f"{selected.user_title} ({len(candidates)} Semantic Views)"
    return selected.user_title


def _has(caps: set[str], *capabilities: ArchitectureCapability) -> bool:
    return any(capability.value in caps for capability in capabilities)
