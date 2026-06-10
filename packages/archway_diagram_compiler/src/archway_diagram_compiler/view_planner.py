"""Data-driven view planning."""

from collections import Counter
from typing import List, Set

from archway_diagram_compiler.models import FlowLedger, SemanticArchitectureSpec
from archway_diagram_compiler.quality_config import DEFAULT_QUALITY_CONFIG
from archway_diagram_compiler.view_config import ViewConfig


def plan_views(spec: SemanticArchitectureSpec, flow_ledger: FlowLedger) -> List[ViewConfig]:
    ai_present = _needs_ai_views(spec, flow_ledger)
    configs = [
        ViewConfig(
            id="logical_service_flow",
            title=_view_title(spec, "production_logical_service_flow", spec.title),
            view_type="logical_service_flow",
            include_node_filter={"mode": "logical"},
            include_flow_filter={"mode": "primary"},
            grouping_dimension="lane",
            lane_template=_logical_lane_template(spec, flow_ledger),
            layout_strategy="lane_orthogonal",
            max_visible_nodes=DEFAULT_QUALITY_CONFIG.max_visible_nodes,
            max_visible_edges=DEFAULT_QUALITY_CONFIG.max_visible_edges,
            split_conditions=[{"type": "high_fanout", "threshold": DEFAULT_QUALITY_CONFIG.max_direct_workload_fanout}],
        ),
        ViewConfig(
            id="network_private_connectivity",
            title=_view_title(spec, "network_private_connectivity", f"{_base_title(spec.title)} - Network and private connectivity"),
            view_type="network_private_connectivity",
            include_node_filter={"mode": "network_private"},
            include_flow_filter={"mode": "network_private"},
            grouping_dimension="placement_scope",
            lane_template="network_private_connectivity",
            layout_strategy="vpc_boundary_with_endpoint_group",
            max_visible_nodes=DEFAULT_QUALITY_CONFIG.max_visible_nodes,
            max_visible_edges=DEFAULT_QUALITY_CONFIG.max_visible_edges,
        ),
    ]
    if ai_present and _explicitly_requested(spec, "ai_logical_service_flow"):
        configs.append(
            ViewConfig(
                id="ai_logical_service_flow",
                title=_view_title(spec, "ai_logical_service_flow", f"{_base_title(spec.title)} - AI logical service flow"),
                view_type="ai_logical_service_flow",
                lane_template="ai_logical",
                layout_strategy="ai_agent_rag_split",
                max_visible_nodes=DEFAULT_QUALITY_CONFIG.max_visible_nodes,
                max_visible_edges=DEFAULT_QUALITY_CONFIG.max_visible_edges,
            )
        )
    if _needs_rag_retrieval_view(spec, flow_ledger):
        configs.append(
            ViewConfig(
                id="rag_retrieval_view",
                title=_view_title(spec, "rag_retrieval_view", f"{_base_title(spec.title)} - RAG retrieval"),
                view_type="rag_retrieval_view",
                lane_template="rag_retrieval",
                layout_strategy="retrieval_runtime",
                max_visible_nodes=DEFAULT_QUALITY_CONFIG.max_visible_nodes,
                max_visible_edges=DEFAULT_QUALITY_CONFIG.max_visible_edges,
            )
        )
    if _needs_rag_ingestion_view(flow_ledger):
        configs.append(
            ViewConfig(
                id="rag_ingestion_view",
                title=_view_title(spec, "rag_ingestion_view", f"{_base_title(spec.title)} - RAG ingestion"),
                view_type="rag_ingestion_view",
                lane_template="rag_ingestion",
                layout_strategy="knowledge_ingestion",
                max_visible_nodes=DEFAULT_QUALITY_CONFIG.max_visible_nodes,
                max_visible_edges=DEFAULT_QUALITY_CONFIG.max_visible_edges,
            )
        )
    if _needs_agent_tool_view(flow_ledger):
        configs.append(
            ViewConfig(
                id="agent_tool_execution_view",
                title=_view_title(spec, "agent_tool_execution_view", f"{_base_title(spec.title)} - Agent tool execution"),
                view_type="agent_tool_execution_view",
                lane_template="agent_tool_execution",
                layout_strategy="agent_tool_execution",
                max_visible_nodes=DEFAULT_QUALITY_CONFIG.max_visible_edges_expanded,
                max_visible_edges=DEFAULT_QUALITY_CONFIG.max_visible_edges_expanded,
            )
        )
    if _needs_agent_memory_view(flow_ledger):
        configs.append(
            ViewConfig(
                id="agent_memory_view",
                title=_view_title(spec, "agent_memory_view", f"{_base_title(spec.title)} - Agent memory"),
                view_type="agent_memory_view",
                lane_template="agent_memory",
                layout_strategy="agent_memory",
                max_visible_nodes=DEFAULT_QUALITY_CONFIG.max_visible_nodes,
                max_visible_edges=DEFAULT_QUALITY_CONFIG.max_visible_edges,
            )
        )
    if _needs_ai_governance_view(flow_ledger):
        configs.append(
            ViewConfig(
                id="ai_security_governance_view",
                title=_view_title(spec, "ai_security_governance_view", f"{_base_title(spec.title)} - AI security and governance"),
                view_type="ai_security_governance_view",
                lane_template="ai_governance",
                layout_strategy="ai_governance_controls",
                max_visible_nodes=DEFAULT_QUALITY_CONFIG.max_visible_nodes,
                max_visible_edges=DEFAULT_QUALITY_CONFIG.max_visible_edges,
            )
        )
    if _explicitly_requested(spec, "data_access_view") or _needs_data_access_view(flow_ledger):
        configs.append(
            ViewConfig(
                id="data_access_view",
                title=_view_title(spec, "data_access_view", f"{_base_title(spec.title)} - Data access"),
                view_type="data_access_view",
                lane_template="data_access",
                layout_strategy="workload_to_data_dependencies",
                max_visible_nodes=DEFAULT_QUALITY_CONFIG.max_visible_nodes,
                max_visible_edges=DEFAULT_QUALITY_CONFIG.max_visible_edges,
            )
        )
    if _needs_async_view(spec, flow_ledger):
        configs.append(
            ViewConfig(
                id="async_flow_view",
                title=_view_title(spec, "async_flow_view", f"{_base_title(spec.title)} - Async flow"),
                view_type="async_flow_view",
                lane_template="event_driven",
                layout_strategy="producer_buffer_consumer",
                max_visible_nodes=DEFAULT_QUALITY_CONFIG.max_visible_nodes,
                max_visible_edges=DEFAULT_QUALITY_CONFIG.max_visible_edges,
            )
        )
    if _needs_media_delivery_view(spec, flow_ledger):
        configs.append(
            ViewConfig(
                id="live_media_delivery_view",
                title=_view_title(spec, "live_media_delivery_view", f"{_base_title(spec.title)} - Live media delivery"),
                view_type="live_media_delivery_view",
                lane_template="semantic_archway",
                layout_strategy="lane_orthogonal",
                max_visible_nodes=DEFAULT_QUALITY_CONFIG.max_visible_nodes,
                max_visible_edges=DEFAULT_QUALITY_CONFIG.max_visible_edges,
            )
        )
    if _needs_media_rights_view(flow_ledger):
        configs.append(
            ViewConfig(
                id="media_rights_ad_decisioning_view",
                title=_view_title(spec, "media_rights_ad_decisioning_view", f"{_base_title(spec.title)} - Rights, DRM, consent, and ads"),
                view_type="media_rights_ad_decisioning_view",
                lane_template="semantic_archway",
                layout_strategy="lane_orthogonal",
                max_visible_nodes=DEFAULT_QUALITY_CONFIG.max_visible_nodes,
                max_visible_edges=DEFAULT_QUALITY_CONFIG.max_visible_edges,
            )
        )
    if _needs_media_qoe_view(flow_ledger):
        configs.append(
            ViewConfig(
                id="media_qoe_analytics_view",
                title=_view_title(spec, "media_qoe_analytics_view", f"{_base_title(spec.title)} - QoE and media analytics"),
                view_type="media_qoe_analytics_view",
                lane_template="semantic_archway",
                layout_strategy="lane_orthogonal",
                max_visible_nodes=DEFAULT_QUALITY_CONFIG.max_visible_nodes,
                max_visible_edges=DEFAULT_QUALITY_CONFIG.max_visible_edges,
            )
        )
    if _needs_fanout_detail_view(spec):
        configs.append(
            ViewConfig(
                id="fanout_detail_view",
                title=_view_title(spec, "fanout_detail_view", f"{_base_title(spec.title)} - Fanout detail"),
                view_type="fanout_detail_view",
                lane_template="event_driven",
                layout_strategy="homogeneous_fanout_detail",
                max_visible_nodes=DEFAULT_QUALITY_CONFIG.max_visible_edges_expanded,
                max_visible_edges=DEFAULT_QUALITY_CONFIG.max_visible_edges_expanded,
            )
        )
    if _explicitly_requested(spec, "security_observability_controls") or _needs_security_view(flow_ledger):
        configs.append(
            ViewConfig(
                id="security_observability_controls",
                title=_view_title(spec, "security_observability_controls", f"{_base_title(spec.title)} - Security and observability"),
                view_type="security_observability_controls",
                lane_template="controls",
                layout_strategy="control_plane",
                max_visible_nodes=DEFAULT_QUALITY_CONFIG.max_visible_nodes,
                max_visible_edges=DEFAULT_QUALITY_CONFIG.max_visible_edges,
            )
        )
    if _explicitly_requested(spec, "rag_view") or _explicitly_requested(spec, "rag_overview_view"):
        configs.append(
            ViewConfig(
                id="rag_view",
                title=_view_title(spec, "rag_view", f"{_base_title(spec.title)} - RAG"),
                view_type="rag_view",
                lane_template="rag",
                layout_strategy="retrieval_and_model_split",
                max_visible_nodes=DEFAULT_QUALITY_CONFIG.max_visible_nodes,
                max_visible_edges=DEFAULT_QUALITY_CONFIG.max_visible_edges,
            )
        )
    if len({node.region for node in spec.nodes if node.region and str(node.region).lower() != "global"}) > 1:
        configs.append(
            ViewConfig(
                id="multi_region_view",
                title=_view_title(spec, "multi_region_view", f"{_base_title(spec.title)} - Multi-region"),
                view_type="multi_region_view",
                lane_template="multi_region",
                layout_strategy="region_grouped",
                max_visible_nodes=DEFAULT_QUALITY_CONFIG.max_visible_edges_expanded,
                max_visible_edges=DEFAULT_QUALITY_CONFIG.max_visible_edges_expanded,
            )
        )
    return configs


def _view_title(spec: SemanticArchitectureSpec, view_id: str, fallback: str) -> str:
    overrides = spec.metadata.get("compiler_view_title_overrides") or {}
    title = overrides.get(view_id)
    return str(title) if title else fallback


def _logical_lane_template(spec: SemanticArchitectureSpec, flow_ledger: FlowLedger) -> str:
    if any(node.logical_group or node.metadata.get("lane_label") for node in spec.nodes):
        return "semantic_archway"
    if _needs_ai_views(spec, flow_ledger):
        return "ai_logical"
    if _needs_rag_retrieval_view(spec, flow_ledger):
        return "rag"
    async_count = sum(1 for entry in flow_ledger.entries if entry.classification in {"async", "event", "notification"})
    if async_count > 1:
        return "retail_fulfillment"
    return "web_api"


def _needs_data_access_view(flow_ledger: FlowLedger) -> bool:
    data_entries = [entry for entry in flow_ledger.entries if entry.classification in {"data_read", "data_write"}]
    by_source = Counter(entry.source for entry in data_entries)
    return any(count > 2 for count in by_source.values()) or len({entry.target for entry in data_entries}) > 3


def _needs_async_view(spec: SemanticArchitectureSpec, flow_ledger: FlowLedger) -> bool:
    async_entries = [entry for entry in flow_ledger.entries if entry.classification in {"async", "event", "notification"}]
    if len(async_entries) <= 2:
        return False
    homogeneous_flow_ids = _homogeneous_fanout_flow_ids(spec)
    if homogeneous_flow_ids and all(entry.flow_id in homogeneous_flow_ids for entry in async_entries):
        return False
    return True


def _needs_media_delivery_view(spec: SemanticArchitectureSpec, flow_ledger: FlowLedger) -> bool:
    services = {node.service for node in spec.nodes}
    return bool({"medialive", "mediapackage", "cloudfront"} & services) and any(entry.classification == "media_delivery" for entry in flow_ledger.entries)


def _needs_media_rights_view(flow_ledger: FlowLedger) -> bool:
    return any(entry.classification in {"media_rights", "media_ad_decision"} for entry in flow_ledger.entries)


def _needs_media_qoe_view(flow_ledger: FlowLedger) -> bool:
    return any(entry.classification == "media_qoe" for entry in flow_ledger.entries)


def _needs_security_view(flow_ledger: FlowLedger) -> bool:
    return sum(1 for entry in flow_ledger.entries if entry.classification in {"auth", "control", "secret_access", "encryption", "audit", "observability", "audit_trace", "model_observability"}) > 3


def _needs_rag_view(spec: SemanticArchitectureSpec, flow_ledger: FlowLedger) -> bool:
    services = {node.service for node in spec.nodes}
    return bool({"bedrock", "bedrock_knowledge_base", "opensearch_serverless", "opensearch_vector_index", "opensearch_hybrid_search", "generic_vector_store"} & services) or any(
        entry.classification in {"rag_retrieval", "model_invocation", "vector_search", "hybrid_search", "source_reference"} for entry in flow_ledger.entries
    )


def _needs_ai_views(spec: SemanticArchitectureSpec, flow_ledger: FlowLedger) -> bool:
    ai_services = {
        "bedrock",
        "bedrock_knowledge_base",
        "bedrock_agent",
        "bedrock_agentcore",
        "bedrock_guardrails",
        "agent_runtime",
        "sagemaker",
    }
    ai_roles = {
        "agent_orchestrator",
        "agent_runtime",
        "planner_agent",
        "worker_agent",
        "reviewer_agent",
        "tool_registry",
        "tool_executor",
        "model_endpoint",
        "foundation_model",
        "conversation_memory",
        "long_term_memory",
        "prompt_template_store",
        "guardrails",
        "eval_runner",
    }
    services = {node.service for node in spec.nodes}
    roles = {str(node.metadata.get("role") or node.metadata.get("ai_role") or node.category or "") for node in spec.nodes}
    return bool(ai_services & services or ai_roles & roles or _ai_edge_types() & {entry.classification for entry in flow_ledger.entries})


def _needs_rag_retrieval_view(spec: SemanticArchitectureSpec, flow_ledger: FlowLedger) -> bool:
    services = {node.service for node in spec.nodes}
    return bool({"bedrock_knowledge_base", "opensearch_vector_index", "opensearch_hybrid_search", "opensearch_serverless", "generic_vector_store"} & services) or any(
        entry.classification in {"rag_retrieval", "vector_search", "hybrid_search", "source_reference"} for entry in flow_ledger.entries
    )


def _needs_rag_ingestion_view(flow_ledger: FlowLedger) -> bool:
    return any(entry.classification in {"document_ingestion", "document_chunking", "document_embedding", "embedding_generation"} for entry in flow_ledger.entries)


def _needs_agent_tool_view(flow_ledger: FlowLedger) -> bool:
    return any(entry.classification == "tool_invocation" for entry in flow_ledger.entries)


def _needs_agent_memory_view(flow_ledger: FlowLedger) -> bool:
    return any(entry.classification in {"memory_read", "memory_write", "prompt_lookup"} for entry in flow_ledger.entries)


def _needs_ai_governance_view(flow_ledger: FlowLedger) -> bool:
    classifications = {entry.classification for entry in flow_ledger.entries}
    categories = set()
    category_map = {
        "guardrail_check": "guardrails",
        "evaluation": "evaluation",
        "human_approval": "human_approval",
        "audit_trace": "audit_trace",
        "model_observability": "model_observability",
        "encryption": "kms_encryption",
        "secret_access": "secrets_manager",
        "audit": "cloudtrail",
        "observability": "cloudwatch_logs",
        "auth": "auth_control",
        "control": "security_control",
    }
    for classification in classifications:
        category = category_map.get(str(classification))
        if category:
            categories.add(category)
    return len(categories) >= 2 and bool(_ai_edge_types() & classifications)


def _explicitly_requested(spec: SemanticArchitectureSpec, view_id: str) -> bool:
    requested = spec.metadata.get("expected_views") or spec.metadata.get("requested_views") or []
    return bool(spec.metadata.get(f"generate_{view_id}")) or view_id in set(str(item) for item in requested)


def _ai_edge_types() -> Set[str]:
    return {
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
    }


def _needs_fanout_detail_view(spec: SemanticArchitectureSpec, threshold: int = 8) -> bool:
    nodes_by_id = {node.id: node for node in spec.nodes}
    outgoing = {}
    for flow in spec.flows:
        if flow.source in nodes_by_id and flow.target in nodes_by_id:
            outgoing.setdefault(flow.source, []).append(flow)
    for flows in outgoing.values():
        local_threshold = _fanout_threshold(flows, nodes_by_id, threshold)
        if len(flows) <= local_threshold:
            continue
        for dimension in ("service", "scope", "role"):
            counts = Counter()
            for flow in flows:
                target = nodes_by_id[flow.target]
                if dimension == "service":
                    key = target.service
                elif dimension == "scope":
                    key = target.scope or ""
                else:
                    key = str(target.metadata.get("role") or target.category or target.logical_group or "")
                if key:
                    counts[key] += 1
            if any(count > local_threshold for count in counts.values()):
                return True
    return False


def _homogeneous_fanout_flow_ids(spec: SemanticArchitectureSpec, threshold: int = 8) -> Set[str]:
    nodes_by_id = {node.id: node for node in spec.nodes}
    outgoing = {}
    for flow in spec.flows:
        if flow.source in nodes_by_id and flow.target in nodes_by_id:
            outgoing.setdefault(flow.source, []).append(flow)
    flow_ids: Set[str] = set()
    for flows in outgoing.values():
        local_threshold = _fanout_threshold(flows, nodes_by_id, threshold)
        if len(flows) <= local_threshold:
            continue
        for dimension in ("service", "scope", "role"):
            groups = {}
            for flow in flows:
                target = nodes_by_id[flow.target]
                if dimension == "service":
                    key = target.service
                elif dimension == "scope":
                    key = target.scope or ""
                else:
                    key = str(target.metadata.get("role") or target.category or target.logical_group or "")
                if key:
                    groups.setdefault(key, []).append(flow)
            for grouped_flows in groups.values():
                if len(grouped_flows) > local_threshold:
                    flow_ids.update(flow.id for flow in grouped_flows)
    return flow_ids


def _fanout_threshold(flows, nodes_by_id, default: int) -> int:
    for flow in flows:
        target = nodes_by_id.get(flow.target)
        target_role = str((target.metadata.get("role") or target.metadata.get("ai_role") or target.category or "") if target else "")
        if (flow.edge_type or flow.metadata.get("classification")) == "tool_invocation" or "tool" in target_role:
            return 5
    return default


def _base_title(title: str) -> str:
    return title.replace(" - Production logical service flow", "")
