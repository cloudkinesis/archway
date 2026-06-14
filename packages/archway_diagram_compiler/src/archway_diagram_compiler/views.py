"""Generic semantic view filtering.

This module intentionally avoids example-specific node ids. It turns
data-driven ViewConfig objects into semantic view specs that feed the
LayoutModel builder.
"""

from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from archway_diagram_compiler._compat import copy_model
from archway_diagram_compiler.models import Flow, SemanticArchitectureSpec, ServiceNode
from archway_diagram_compiler.quality_config import DEFAULT_QUALITY_CONFIG
from archway_diagram_compiler.view_config import ViewConfig
from archway_diagram_compiler.view_utils import (
    append_visible_flow as _append_visible_flow,
    base_title as _base_title,
    copy_view as _copy_view,
    is_vpc_resident as _is_vpc_resident,
    natural_key as _natural_key,
    node_ids_from_flows as _node_ids_from_flows,
    ordered_node_ids as _ordered_node_ids,
    ordered_unique_target_ids as _ordered_unique_target_ids,
    safe_identifier as _safe_identifier,
    target_position as _target_position,
)


SUPPRESSED_LOGICAL_SERVICES = {
    "secrets_manager",
    "kms",
    "cloudwatch",
    "cloudtrail",
    "vpc_endpoint",
    "shield",
}

CONTROL_SERVICES = {"waf", "cognito"}
REQUEST_SERVICES = {"external_actor", "external_user", "route53", "cloudfront", "api_gateway"}
NETWORK_ENTRY_SERVICES = {"api_gateway", "vpc_link"}
DATA_EDGE_TYPES = {"data_read", "data_write", "vpc_endpoint_access"}
ASYNC_EDGE_TYPES = {"async", "event", "notification"}
SECURITY_EDGE_TYPES = {"auth", "control", "secret_access", "encryption", "audit", "observability"}
MEDIA_DELIVERY_EDGE_TYPES = {"media_delivery"}
MEDIA_RIGHTS_EDGE_TYPES = {"media_rights", "media_ad_decision"}
MEDIA_QOE_EDGE_TYPES = {"media_qoe", "observability", "audit"}
RAG_EDGE_TYPES = {"rag_retrieval", "model_invocation", "vector_search", "hybrid_search", "source_reference"}
AI_EDGE_TYPES = {
    "request",
    "auth",
    "control",
    "private_integration",
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
RAG_RETRIEVAL_EDGE_TYPES = {"rag_retrieval", "vector_search", "hybrid_search", "source_reference", "model_invocation"}
RAG_INGESTION_EDGE_TYPES = {"document_ingestion", "document_chunking", "document_embedding", "embedding_generation", "data_write"}
AGENT_TOOL_EDGE_TYPES = {"tool_invocation"}
AGENT_MEMORY_EDGE_TYPES = {"memory_read", "memory_write", "prompt_lookup"}
AI_GOVERNANCE_EDGE_TYPES = {"guardrail_check", "evaluation", "human_approval", "audit_trace", "model_observability", "auth", "control", "secret_access", "encryption", "audit", "observability"}
HOMOGENEOUS_FANOUT_THRESHOLD = DEFAULT_QUALITY_CONFIG.homogeneous_fanout_threshold


def build_diagram_view_specs(
    spec: SemanticArchitectureSpec,
    view_configs: Optional[Sequence[ViewConfig]] = None,
) -> List[SemanticArchitectureSpec]:
    if view_configs is None:
        return [_logical_view(spec), _network_view(spec)]

    views: List[SemanticArchitectureSpec] = []
    for config in view_configs:
        if config.view_type == "logical_service_flow":
            views.append(_with_view_config(_logical_view(spec), config))
        elif config.view_type == "network_private_connectivity":
            views.append(_with_view_config(_network_view(spec), config))
        elif config.view_type == "data_access_view":
            views.append(_edge_type_view(spec, config.id, config.title, DATA_EDGE_TYPES, direction="right"))
        elif config.view_type == "async_flow_view":
            views.append(_edge_type_view(spec, config.id, config.title, ASYNC_EDGE_TYPES, direction="right"))
        elif config.view_type == "security_observability_controls":
            views.append(_edge_type_view(spec, config.id, config.title, SECURITY_EDGE_TYPES, direction="right"))
        elif config.view_type == "live_media_delivery_view":
            views.append(_edge_type_view(spec, config.id, config.title, MEDIA_DELIVERY_EDGE_TYPES, direction="right"))
        elif config.view_type == "media_rights_ad_decisioning_view":
            views.append(_edge_type_view(spec, config.id, config.title, MEDIA_RIGHTS_EDGE_TYPES, direction="right"))
        elif config.view_type == "media_qoe_analytics_view":
            views.append(_edge_type_view(spec, config.id, config.title, MEDIA_QOE_EDGE_TYPES, direction="right"))
        elif config.view_type == "ai_logical_service_flow":
            views.append(_ai_logical_view(spec, config))
        elif config.view_type == "rag_retrieval_view":
            views.append(_ai_edge_type_view(spec, config, RAG_RETRIEVAL_EDGE_TYPES, direction="right"))
        elif config.view_type == "rag_ingestion_view":
            views.append(_ai_edge_type_view(spec, config, RAG_INGESTION_EDGE_TYPES, direction="right"))
        elif config.view_type == "agent_tool_execution_view":
            views.append(_ai_edge_type_view(spec, config, AGENT_TOOL_EDGE_TYPES, direction="right"))
        elif config.view_type == "agent_memory_view":
            views.append(_ai_edge_type_view(spec, config, AGENT_MEMORY_EDGE_TYPES, direction="right"))
        elif config.view_type == "ai_security_governance_view":
            views.append(_ai_edge_type_view(spec, config, AI_GOVERNANCE_EDGE_TYPES, direction="right"))
        elif config.view_type == "rag_view":
            views.append(_rag_view(spec, config))
        elif config.view_type == "fanout_detail_view":
            views.append(_fanout_detail_view(spec, config))
        elif config.view_type == "multi_region_view":
            views.append(_multi_region_view(spec, config))
    return views


def _with_view_config(view_spec: SemanticArchitectureSpec, config: ViewConfig) -> SemanticArchitectureSpec:
    return copy_model(
        view_spec,
        deep=True,
        update={"metadata": {**view_spec.metadata, "lane_template": config.lane_template, "layout_strategy": config.layout_strategy}},
    )


def _logical_view(spec: SemanticArchitectureSpec) -> SemanticArchitectureSpec:
    nodes_by_id = {node.id: node for node in spec.nodes}
    flows = _logical_flows(nodes_by_id, spec.flows)
    flows, subsystem_nodes = _summarize_primary_specialized_subsystems(spec, flows)
    flows, aggregate_nodes = _collapse_homogeneous_fanout(spec, flows)
    node_ids = _node_ids_from_flows(flows)
    node_ids.update(
        node.id
        for node in spec.nodes
        if node.service in CONTROL_SERVICES | REQUEST_SERVICES
    )
    ordered_ids = _ordered_node_ids(spec, node_ids)
    nodes = [_logical_display_node(nodes_by_id[node_id]) for node_id in ordered_ids if node_id in nodes_by_id]
    nodes.extend(subsystem_nodes)
    nodes.extend(aggregate_nodes)
    return _copy_view(
        spec,
        "production_logical_service_flow",
        spec.title,
        nodes,
        flows,
        direction="right",
    )


def _logical_flows(nodes_by_id: Dict[str, ServiceNode], source_flows: Sequence[Flow]) -> List[Flow]:
    visible: List[Flow] = []
    seen_edges: Set[Tuple[str, str, str]] = set()
    flows_by_id = {flow.id: flow for flow in source_flows}
    endpoint_sources = {
        flow.target: flow.source
        for flow in source_flows
        if nodes_by_id.get(flow.target) is not None
        and nodes_by_id[flow.target].service == "vpc_endpoint"
        and nodes_by_id.get(flow.source) is not None
    }
    for flow in source_flows:
        source = nodes_by_id.get(flow.source)
        target = nodes_by_id.get(flow.target)
        if source is None or target is None:
            continue
        if flow.id.startswith("prod_auth_"):
            continue
        if flow.metadata.get("endpoint_access_path") and source.service == "vpc_endpoint":
            if target.service in SUPPRESSED_LOGICAL_SERVICES:
                continue
            logical_source = nodes_by_id.get(endpoint_sources.get(flow.source, ""))
            if logical_source is None:
                continue
            metadata = dict(flow.metadata)
            metadata.pop("endpoint_access_path", None)
            metadata["endpoint_collapsed"] = True
            metadata["source_flow_id"] = _source_flow_id(flow)
            source_flow = flows_by_id.get(metadata["source_flow_id"])
            _append_visible_flow(
                visible,
                seen_edges,
                Flow(
                    id=f"{flow.id}_logical",
                    source=logical_source.id,
                    target=target.id,
                    label=flow.label,
                    protocol=flow.protocol,
                    edge_type=(
                        source_flow.edge_type
                        if source_flow is not None and source_flow.edge_type != "vpc_endpoint_access"
                        else _infer_endpoint_edge_type(target, flow)
                    ),
                    metadata=metadata,
                ),
            )
            continue
        if source.service in SUPPRESSED_LOGICAL_SERVICES or target.service in SUPPRESSED_LOGICAL_SERVICES:
            continue
        if _flow_type(flow) in MEDIA_RIGHTS_EDGE_TYPES | MEDIA_QOE_EDGE_TYPES:
            continue
        if flow.metadata.get("endpoint_access_path"):
            continue
        metadata = dict(flow.metadata)
        classification = metadata.get("classification") or metadata.get("edge_kind")
        if classification == "control" or metadata.get("style") in {"association", "control"}:
            metadata["edge_kind"] = "control"
        if (
            (source.service in {"waf", "cognito"} or target.service in {"waf", "cognito"})
            and metadata.get("edge_kind") != "control"
        ):
            continue
        label = flow.label
        if metadata.get("edge_kind") == "control" and source.service in {"waf", "cognito"}:
            label = None
        if source.service in {"step_functions", "eventbridge"} and target.service in {"s3", "sns"}:
            label = None
        _append_visible_flow(
            visible,
            seen_edges,
            copy_model(flow, deep=True, update={"label": label, "metadata": metadata}),
        )
    return visible


def _network_view(spec: SemanticArchitectureSpec) -> SemanticArchitectureSpec:
    nodes_by_id = {node.id: node for node in spec.nodes}
    node_ids = _network_node_ids(spec)
    flows = [
        flow
        for flow in spec.flows
        if flow.source in node_ids
        and flow.target in node_ids
        and _is_network_flow(flow, nodes_by_id)
    ]
    node_ids, flows = _augment_network_endpoint_targets(spec, node_ids, flows)
    node_ids, flows = _force_endpoint_metadata_targets(spec, node_ids, flows)
    node_ids, flows, extra_nodes = _augment_network_rag_private_targets(spec, node_ids, flows)
    network_spec = copy_model(
        spec,
        deep=True,
        update={"nodes": [*spec.nodes, *extra_nodes]},
    )
    nodes, flows = _collapse_network_homogeneous_targets(network_spec, node_ids, flows)
    nodes = [_logical_display_node(node) for node in nodes]
    return _copy_view(
        spec,
        "network_private_connectivity",
        f"{_base_title(spec.title)} - Network and private connectivity",
        nodes,
        flows,
        direction="down",
    )


def _edge_type_view(
    spec: SemanticArchitectureSpec,
    view_name: str,
    title: str,
    edge_types: Set[str],
    direction: str,
) -> SemanticArchitectureSpec:
    nodes_by_id = {node.id: node for node in spec.nodes}
    flows = [
        copy_model(flow, deep=True)
        for flow in spec.flows
        if _flow_type(flow) in edge_types
        and flow.source in nodes_by_id
        and flow.target in nodes_by_id
        and not _is_endpoint_internal_hop(flow, nodes_by_id)
    ]
    aggregate_nodes: List[ServiceNode] = []
    if view_name == "async_flow_view":
        flows, aggregate_nodes = _collapse_homogeneous_fanout(spec, flows)
    node_ids = _node_ids_from_flows(flows)
    nodes = [nodes_by_id[node_id] for node_id in _ordered_node_ids(spec, node_ids) if node_id in nodes_by_id]
    nodes.extend(aggregate_nodes)
    return _copy_view(
        spec,
        view_name,
        title,
        nodes,
        flows,
        direction=direction,
    )


def _rag_view(spec: SemanticArchitectureSpec, config: ViewConfig) -> SemanticArchitectureSpec:
    nodes_by_id = {node.id: node for node in spec.nodes}
    rag_services = {"bedrock", "bedrock_knowledge_base", "opensearch_serverless", "kendra", "s3"}
    flows = [
        copy_model(flow, deep=True)
        for flow in spec.flows
        if flow.source in nodes_by_id
        and flow.target in nodes_by_id
        and (
            _flow_type(flow) in RAG_EDGE_TYPES
            or nodes_by_id[flow.source].service in rag_services
            or nodes_by_id[flow.target].service in rag_services
        )
        and not _is_endpoint_internal_hop(flow, nodes_by_id)
    ]
    node_ids = _node_ids_from_flows(flows)
    return _copy_view(
        spec,
        config.id,
        config.title,
        [nodes_by_id[node_id] for node_id in _ordered_node_ids(spec, node_ids)],
        flows,
        direction="right",
    )


def _ai_logical_view(spec: SemanticArchitectureSpec, config: ViewConfig) -> SemanticArchitectureSpec:
    nodes_by_id = {node.id: node for node in spec.nodes}
    flows = []
    for flow in spec.flows:
        source = nodes_by_id.get(flow.source)
        target = nodes_by_id.get(flow.target)
        if source is None or target is None or _is_endpoint_internal_hop(flow, nodes_by_id):
            continue
        if _flow_type(flow) in AI_EDGE_TYPES or _is_ai_node(source) or _is_ai_node(target):
            flows.append(copy_model(flow, deep=True))
    flows, aggregate_nodes = _collapse_homogeneous_fanout(spec, flows)
    node_ids = _node_ids_from_flows(flows)
    node_ids.update(node.id for node in spec.nodes if node.service in CONTROL_SERVICES | REQUEST_SERVICES and _connected_to_ai(node.id, spec, nodes_by_id))
    nodes = [_logical_display_node(nodes_by_id[node_id]) for node_id in _ordered_node_ids(spec, node_ids) if node_id in nodes_by_id]
    nodes.extend(aggregate_nodes)
    return _copy_view(spec, config.id, config.title, nodes, flows, direction="right")


def _ai_edge_type_view(
    spec: SemanticArchitectureSpec,
    config: ViewConfig,
    edge_types: Set[str],
    direction: str,
) -> SemanticArchitectureSpec:
    nodes_by_id = {node.id: node for node in spec.nodes}
    candidate_flows = (
        _governance_control_flows(spec, nodes_by_id)
        if config.view_type == "ai_security_governance_view"
        else _logical_flows(nodes_by_id, spec.flows)
    )
    flows = [
        copy_model(flow, deep=True)
        for flow in candidate_flows
        if _flow_type(flow) in edge_types
        and flow.source in nodes_by_id
        and flow.target in nodes_by_id
        and (config.view_type == "ai_security_governance_view" or not _is_endpoint_internal_hop(flow, nodes_by_id))
    ]
    if config.view_type in {"agent_tool_execution_view", "async_flow_view"}:
        flows, aggregate_nodes = _collapse_homogeneous_fanout(spec, flows)
    else:
        aggregate_nodes = []
    node_ids = _node_ids_from_flows(flows)
    nodes = [_logical_display_node(nodes_by_id[node_id]) for node_id in _ordered_node_ids(spec, node_ids) if node_id in nodes_by_id]
    nodes.extend(aggregate_nodes)
    return _copy_view(spec, config.id, config.title, nodes, flows, direction=direction)


def _governance_control_flows(spec: SemanticArchitectureSpec, nodes_by_id: Dict[str, ServiceNode]) -> List[Flow]:
    incoming_to_endpoint = {
        flow.target: flow.source
        for flow in spec.flows
        if flow.target in nodes_by_id and nodes_by_id[flow.target].service == "vpc_endpoint"
    }
    flows: List[Flow] = []
    seen: Set[Tuple[str, str, str]] = set()
    for flow in spec.flows:
        source = nodes_by_id.get(flow.source)
        target = nodes_by_id.get(flow.target)
        if source is None or target is None:
            continue
        flow_type = _flow_type(flow)
        if source.service == "vpc_endpoint":
            if flow.metadata.get("endpoint_security_context"):
                flows.append(copy_model(flow, deep=True))
                continue
            logical_source = incoming_to_endpoint.get(source.id)
            if logical_source is None:
                continue
            logical_flow = Flow(
                id=f"{flow.id}_governance_logical",
                source=logical_source,
                target=target.id,
                label=flow.label,
                edge_type=flow_type,
                metadata={**flow.metadata, "source_flow_id": _source_flow_id(flow), "endpoint_collapsed": True},
            )
            _append_visible_flow(flows, seen, logical_flow)
            continue
        if target.service == "vpc_endpoint":
            continue
        _append_visible_flow(flows, seen, copy_model(flow, deep=True))
    return flows


def _multi_region_view(spec: SemanticArchitectureSpec, config: ViewConfig) -> SemanticArchitectureSpec:
    nodes_by_id = {node.id: node for node in spec.nodes}
    regional_nodes = {node.id for node in spec.nodes if node.region or node.scope in {"global_edge", "external_actor"}}
    flows = [
        copy_model(flow, deep=True)
        for flow in spec.flows
        if flow.source in regional_nodes and flow.target in regional_nodes
    ]
    return _copy_view(
        spec,
        config.id,
        config.title,
        [nodes_by_id[node_id] for node_id in _ordered_node_ids(spec, regional_nodes)],
        flows,
        direction="right",
    )


def _fanout_detail_view(spec: SemanticArchitectureSpec, config: ViewConfig) -> SemanticArchitectureSpec:
    nodes_by_id = {node.id: node for node in spec.nodes}
    groups = _homogeneous_fanout_groups(spec, spec.flows)
    flow_by_id = {flow.id: flow for flow in spec.flows}
    aggregate_nodes: List[ServiceNode] = []
    flows: List[Flow] = []
    node_ids: Set[str] = set()
    for group in groups:
        source_id = str(group["source"])
        aggregate_id = str(group["aggregate_id"])
        group_flow_ids = [str(flow_id) for flow_id in group["flow_ids"]]
        group_target_ids = [str(target_id) for target_id in group.get("target_ids", [])]
        source = nodes_by_id.get(source_id)
        if source is None:
            continue
        aggregate_nodes.append(
            ServiceNode(
                id=aggregate_id,
                name=str(group["label"]),
                service="semantic_group",
                provider=source.provider,
                scope="generic_application",
                annotation=True,
                metadata={
                    "homogeneous_fanout_group": True,
                    "source_node_id": source_id,
                    "collapsed_flow_ids": group_flow_ids,
                    "fanout_detail_group": True,
                },
            )
        )
        node_ids.add(source_id)
        node_ids.add(aggregate_id)
        first_flow = flow_by_id[group_flow_ids[0]]
        flows.append(
            Flow(
                id=f"{aggregate_id}_detail_entry",
                source=source_id,
                target=aggregate_id,
                label=None,
                edge_type=first_flow.edge_type,
                metadata={
                    "fanout_detail_entry": True,
                    "source_flow_ids": group_flow_ids,
                },
            )
        )
        for flow_id in group_flow_ids:
            flow = flow_by_id.get(flow_id)
            if flow is None or flow.target not in nodes_by_id:
                continue
            node_ids.add(flow.target)
        ordered_detail_flows = sorted(
            (flow_by_id[flow_id] for flow_id in group_flow_ids if flow_id in flow_by_id),
            key=lambda item: (_target_position(item.target, group_target_ids), _natural_key(item.target), _natural_key(item.id)),
        )
        for flow in ordered_detail_flows:
            flows.append(
                Flow(
                    id=f"{flow.id}_from_fanout_group",
                    source=aggregate_id,
                    target=flow.target,
                    label=flow.label,
                    edge_type=flow.edge_type,
                    metadata={
                        **flow.metadata,
                        "fanout_detail_edge": True,
                        "source_flow_ids": [flow.id],
                    },
                )
            )
    if not flows:
        return _copy_view(spec, config.id, config.title, [], [], direction="right")
    concrete_nodes = [nodes_by_id[node_id] for node_id in _ordered_node_ids(spec, node_ids) if node_id in nodes_by_id]
    return _copy_view(
        spec,
        config.id,
        config.title,
        [*concrete_nodes, *aggregate_nodes],
        flows,
        direction="right",
    )


def _force_endpoint_metadata_targets(
    spec: SemanticArchitectureSpec,
    node_ids: Set[str],
    flows: Sequence[Flow],
) -> Tuple[Set[str], List[Flow]]:
    nodes_by_id = {node.id: node for node in spec.nodes}
    next_node_ids = set(node_ids)
    next_flows = [copy_model(flow, deep=True) for flow in flows]
    existing_edges = {(flow.source, flow.target) for flow in next_flows}
    original_flow_ids_by_target: Dict[str, List[str]] = defaultdict(list)
    for flow in spec.flows:
        original_flow_ids_by_target[flow.target].append(flow.id)

    for endpoint_id in sorted(node_ids):
        endpoint = nodes_by_id.get(endpoint_id)
        if endpoint is None or endpoint.service != "vpc_endpoint":
            continue
        target_ids = _endpoint_metadata_target_ids(endpoint)
        for target_id in target_ids:
            target = nodes_by_id.get(target_id)
            if target is None or (endpoint_id, target_id) in existing_edges:
                continue
            next_node_ids.add(target_id)
            next_flows.append(
                Flow(
                    id=f"{endpoint_id}_to_{target_id}_metadata_target",
                    source=endpoint_id,
                    target=target_id,
                    label=_endpoint_target_label(endpoint, target),
                    edge_type="vpc_endpoint_access",
                    metadata={
                        "endpoint_access_path": True,
                        "target_node_id": target_id,
                        "target_service": target.service,
                        "source_flow_ids": original_flow_ids_by_target.get(target_id, []),
                        "forced_endpoint_target": True,
                    },
                )
            )
            existing_edges.add((endpoint_id, target_id))
    return next_node_ids, next_flows


def _augment_network_rag_private_targets(
    spec: SemanticArchitectureSpec,
    node_ids: Set[str],
    flows: Sequence[Flow],
) -> Tuple[Set[str], List[Flow], List[ServiceNode]]:
    nodes_by_id = {node.id: node for node in spec.nodes}
    next_node_ids = set(node_ids)
    next_flows = [copy_model(flow, deep=True) for flow in flows]
    extra_nodes: Dict[str, ServiceNode] = {}
    existing_edges = {(flow.source, flow.target) for flow in next_flows}
    endpoint_by_source_family: Dict[Tuple[str, str], str] = {}
    vpc_sources: Set[str] = set()
    downstream_by_source: Dict[str, Set[str]] = defaultdict(set)

    for flow in next_flows:
        source = nodes_by_id.get(flow.source)
        target = nodes_by_id.get(flow.target)
        if source is not None and target is not None and target.service == "vpc_endpoint":
            family = _endpoint_family(target)
            if family:
                endpoint_by_source_family[(source.id, family)] = target.id
        if source is not None and target is not None and source.service == "vpc_endpoint" and target.service == "bedrock_knowledge_base":
            incoming_source = _endpoint_incoming_source(flow.source, next_flows, nodes_by_id)
            if incoming_source:
                vpc_sources.add(incoming_source)
                downstream_by_source[incoming_source].update(_rag_downstream_targets(spec, target.id))

    for source_id in sorted(vpc_sources, key=_natural_key):
        source = nodes_by_id.get(source_id)
        if source is None:
            continue
        for target_id in sorted(downstream_by_source[source_id], key=_natural_key):
            target = nodes_by_id.get(target_id)
            if target is None:
                continue
            family = _managed_service_family(target)
            if family not in {"opensearch", "s3", "dynamodb"}:
                continue
            endpoint_id = endpoint_by_source_family.get((source_id, family))
            if endpoint_id is None:
                endpoint_id = f"{source_id}_{family}_endpoint"
                endpoint = ServiceNode(
                    id=endpoint_id,
                    name=_endpoint_name_for_family(family),
                    service="vpc_endpoint",
                    provider=source.provider,
                    scope="vpc_resident",
                    region=source.region,
                    vpc_id=source.vpc_id,
                    metadata={
                        "target_node_id": target.id,
                        "target_node_ids": [target.id],
                        "endpoint_family": family,
                        "endpoint_type": "gateway endpoint" if family in {"s3", "dynamodb"} else "interface endpoint",
                        "rag_private_dependency": True,
                    },
                )
                extra_nodes[endpoint_id] = endpoint
                nodes_by_id[endpoint_id] = endpoint
                next_node_ids.add(endpoint_id)
                next_flows.append(
                    Flow(
                        id=f"{source_id}_{family}_rag_endpoint",
                        source=source_id,
                        target=endpoint_id,
                        label="gateway endpoint" if family in {"s3", "dynamodb"} else "interface endpoint",
                        edge_type="vpc_endpoint_access",
                        metadata={"rag_private_dependency": True},
                    )
                )
                existing_edges.add((source_id, endpoint_id))
            else:
                endpoint = nodes_by_id.get(endpoint_id)
                if endpoint is not None:
                    target_ids = list(endpoint.metadata.get("target_node_ids") or [])
                    if target.id not in target_ids:
                        target_ids.append(target.id)
                        endpoint.metadata["target_node_ids"] = sorted(target_ids, key=_natural_key)
            if (endpoint_id, target.id) not in existing_edges:
                next_flows.append(
                    Flow(
                        id=f"{endpoint_id}_to_{target.id}_rag_target",
                        source=endpoint_id,
                        target=target.id,
                        label=_endpoint_target_label(nodes_by_id[endpoint_id], target),
                        edge_type="vpc_endpoint_access",
                        metadata={
                            "endpoint_access_path": True,
                            "target_node_id": target.id,
                            "target_service": target.service,
                            "rag_private_dependency": True,
                        },
                    )
                )
                existing_edges.add((endpoint_id, target.id))
            next_node_ids.add(target.id)
    return next_node_ids, next_flows, list(extra_nodes.values())


def _endpoint_incoming_source(endpoint_id: str, flows: Sequence[Flow], nodes_by_id: Dict[str, ServiceNode]) -> Optional[str]:
    for flow in flows:
        if flow.target == endpoint_id and nodes_by_id.get(flow.source) is not None and _is_vpc_resident(nodes_by_id[flow.source].scope):
            return flow.source
    return None


def _rag_downstream_targets(spec: SemanticArchitectureSpec, start_id: str) -> Set[str]:
    nodes_by_id = {node.id: node for node in spec.nodes}
    allowed_services = {
        "opensearch",
        "opensearch_serverless",
        "opensearch_vector_index",
        "opensearch_hybrid_search",
        "generic_vector_store",
        "s3",
        "dynamodb",
    }
    targets: Set[str] = set()
    frontier = {start_id}
    seen = set()
    for _ in range(3):
        next_frontier = set()
        for flow in spec.flows:
            if flow.source not in frontier or flow.target in seen:
                continue
            target = nodes_by_id.get(flow.target)
            if target is None:
                continue
            if target.service in allowed_services:
                targets.add(target.id)
            next_frontier.add(target.id)
        seen.update(frontier)
        frontier = next_frontier
    return targets


def _endpoint_name_for_family(family: str) -> str:
    names = {
        "dynamodb": "DynamoDB gateway endpoint",
        "s3": "S3 gateway endpoint",
        "opensearch": "OpenSearch interface endpoint",
        "bedrock": "Bedrock interface endpoint",
        "sqs": "SQS interface endpoint",
        "secrets_manager": "Secrets Manager interface endpoint",
        "cloudwatch": "CloudWatch Logs interface endpoint",
        "kms": "KMS interface endpoint",
    }
    return names.get(family, f"{family.replace('_', ' ').title()} endpoint")


def _endpoint_metadata_target_ids(endpoint: ServiceNode) -> List[str]:
    target_ids = []
    raw_targets = endpoint.metadata.get("target_node_ids") or []
    if isinstance(raw_targets, str):
        raw_targets = [raw_targets]
    target_ids.extend(str(target_id) for target_id in raw_targets if target_id)
    if endpoint.metadata.get("target_node_id"):
        target_ids.append(str(endpoint.metadata["target_node_id"]))
    if endpoint.metadata.get("target_node_id") is None and endpoint.metadata.get("target_node_ids") is None:
        return []
    return sorted(set(target_ids), key=_natural_key)


def _endpoint_target_label(endpoint: ServiceNode, target: ServiceNode) -> str:
    family = str(endpoint.metadata.get("endpoint_family") or _managed_service_family(target))
    if family == "dynamodb":
        return "DynamoDB access"
    if family == "sqs":
        return "SQS access"
    if family == "s3":
        return "S3 access"
    if family == "opensearch":
        return "OpenSearch access"
    if family == "bedrock":
        return "Bedrock access"
    if family == "secrets_manager":
        return "secrets access"
    if family == "cloudwatch":
        return "logs and metrics"
    return "private access"


def _augment_network_endpoint_targets(
    spec: SemanticArchitectureSpec,
    node_ids: Set[str],
    flows: Sequence[Flow],
) -> Tuple[Set[str], List[Flow]]:
    nodes_by_id = {node.id: node for node in spec.nodes}
    next_node_ids = set(node_ids)
    next_flows = [copy_model(flow, deep=True) for flow in flows]
    existing_edges = {(flow.source, flow.target) for flow in next_flows}
    endpoint_by_source_family: Dict[Tuple[str, str], str] = {}
    for flow in next_flows:
        source = nodes_by_id.get(flow.source)
        target = nodes_by_id.get(flow.target)
        if source is None or target is None or target.service != "vpc_endpoint":
            continue
        family = _endpoint_family(target)
        if family:
            endpoint_by_source_family[(source.id, family)] = target.id

    first_hops_by_source: Dict[str, List[Flow]] = defaultdict(list)
    for flow in spec.flows:
        source = nodes_by_id.get(flow.source)
        target = nodes_by_id.get(flow.target)
        if source is None or target is None or not _is_vpc_resident(source.scope):
            continue
        if target.service in {"lambda", "ecs", "generic_application"} or _flow_type(flow) in {"tool_invocation", "agent_handoff", "agent_orchestration"}:
            first_hops_by_source[source.id].append(flow)

    for source_id, first_hops in first_hops_by_source.items():
        for first_hop in first_hops:
            for second_hop in spec.flows:
                if second_hop.source != first_hop.target:
                    continue
                target = nodes_by_id.get(second_hop.target)
                if target is None or target.service == "vpc_endpoint":
                    continue
                family = _managed_service_family(target)
                endpoint_id = endpoint_by_source_family.get((source_id, family))
                if endpoint_id is None or (endpoint_id, target.id) in existing_edges:
                    continue
                next_node_ids.add(target.id)
                next_flows.append(
                    Flow(
                        id=f"{second_hop.id}_via_{endpoint_id}",
                        source=endpoint_id,
                        target=target.id,
                        label=second_hop.label,
                        edge_type="vpc_endpoint_access",
                        metadata={
                            "endpoint_access_path": True,
                            "source_flow_ids": [first_hop.id, second_hop.id],
                            "transitive_endpoint_target": True,
                        },
                    )
                )
                existing_edges.add((endpoint_id, target.id))
    return next_node_ids, next_flows


def _endpoint_family(node: ServiceNode) -> str:
    label = f"{node.id} {node.name} {node.service}".lower()
    for family in ("dynamodb", "s3", "sqs", "secrets_manager", "opensearch", "bedrock", "cloudwatch", "kms"):
        token = family.replace("_", " ")
        if family in label or token in label:
            return family
    return ""


def _managed_service_family(node: ServiceNode) -> str:
    if node.service in {"dynamodb"}:
        return "dynamodb"
    if node.service in {"s3"}:
        return "s3"
    if node.service in {"sqs"}:
        return "sqs"
    if node.service in {"secrets_manager"}:
        return "secrets_manager"
    if node.service in {"opensearch", "opensearch_serverless", "opensearch_vector_index", "opensearch_hybrid_search"}:
        return "opensearch"
    if node.service in {"bedrock", "bedrock_knowledge_base"}:
        return "bedrock"
    if node.service in {"cloudwatch"}:
        return "cloudwatch"
    if node.service in {"kms"}:
        return "kms"
    return node.service


def _network_node_ids(spec: SemanticArchitectureSpec) -> Set[str]:
    nodes_by_id = {node.id: node for node in spec.nodes}
    node_ids: Set[str] = set()
    for node in spec.nodes:
        if (_is_vpc_resident(node.scope) and not (node.service == "lambda" and not node.vpc_id)) or node.service in NETWORK_ENTRY_SERVICES:
            node_ids.add(node.id)
    for flow in spec.flows:
        source = nodes_by_id.get(flow.source)
        target = nodes_by_id.get(flow.target)
        if source is None or target is None:
            continue
        if target.service == "lambda" and not target.vpc_id:
            continue
        if _is_network_flow(flow, nodes_by_id):
            node_ids.add(flow.source)
            node_ids.add(flow.target)
    return node_ids


def _collapse_network_homogeneous_targets(
    spec: SemanticArchitectureSpec,
    node_ids: Set[str],
    flows: Sequence[Flow],
) -> Tuple[List[ServiceNode], List[Flow]]:
    nodes_by_id = {node.id: node for node in spec.nodes}
    groups = _homogeneous_fanout_groups(spec, flows)
    if not groups:
        return [nodes_by_id[node_id] for node_id in _ordered_node_ids(spec, node_ids)], [copy_model(flow, deep=True) for flow in flows]

    collapsed_flow_ids: Set[str] = set()
    aggregate_nodes: List[ServiceNode] = []
    next_flows: List[Flow] = []
    next_node_ids = set(node_ids)
    flow_by_id = {flow.id: flow for flow in flows}
    for group in groups:
        group_flow_ids = [str(flow_id) for flow_id in group["flow_ids"] if str(flow_id) in flow_by_id]
        group_target_ids = [str(target_id) for target_id in group.get("target_ids", []) if str(target_id) in nodes_by_id]
        if len(group_target_ids) <= HOMOGENEOUS_FANOUT_THRESHOLD:
            continue
        targets = [nodes_by_id[target_id] for target_id in group_target_ids]
        if not targets or not all(_is_vpc_resident(target.scope) for target in targets):
            continue
        if _has_meaningful_network_differences(targets):
            continue
        source_id = str(group["source"])
        source = nodes_by_id.get(source_id)
        if source is None:
            continue
        aggregate_id = str(group["aggregate_id"])
        reason = str(group.get("reason") or "homogeneous fan-out summarized to reduce crossings")
        aggregate_nodes.append(
            ServiceNode(
                id=aggregate_id,
                name=str(group["label"]),
                service="semantic_group",
                provider=source.provider,
                scope="vpc_resident",
                vpc_id=_common_value(targets, "vpc_id"),
                annotation=True,
                metadata={
                    "homogeneous_fanout_group": True,
                    "network_aggregate": True,
                    "source_node_id": source_id,
                    "collapsed_flow_ids": group_flow_ids,
                    "collapse_reason": reason,
                },
            )
        )
        collapsed_flow_ids.update(group_flow_ids)
        for target_id in group_target_ids:
            next_node_ids.discard(target_id)
        next_node_ids.add(source_id)
        next_node_ids.add(aggregate_id)
        first_flow = flow_by_id[group_flow_ids[0]]
        next_flows.append(
            Flow(
                id=f"{aggregate_id}_network_summary",
                source=source_id,
                target=aggregate_id,
                label=first_flow.label,
                edge_type=first_flow.edge_type,
                metadata={
                    "homogeneous_fanout_group": True,
                    "network_aggregate": True,
                    "source_flow_ids": group_flow_ids,
                },
            )
        )

    next_flows.extend(copy_model(flow, deep=True) for flow in flows if flow.id not in collapsed_flow_ids)
    concrete_nodes = [nodes_by_id[node_id] for node_id in _ordered_node_ids(spec, next_node_ids) if node_id in nodes_by_id]
    return [*concrete_nodes, *aggregate_nodes], next_flows


def _has_meaningful_network_differences(nodes: Sequence[ServiceNode]) -> bool:
    fields = [
        {node.vpc_id for node in nodes if node.vpc_id},
        {node.subnet_id for node in nodes if node.subnet_id},
        {node.az for node in nodes if node.az},
        {str(node.metadata.get("security_group") or node.metadata.get("security_groups") or "") for node in nodes if node.metadata.get("security_group") or node.metadata.get("security_groups")},
        {str(node.metadata.get("route_path") or "") for node in nodes if node.metadata.get("route_path")},
        {str(node.metadata.get("endpoint") or "") for node in nodes if node.metadata.get("endpoint")},
        {str(node.metadata.get("account") or "") for node in nodes if node.metadata.get("account")},
        {str(node.metadata.get("role") or "") for node in nodes if node.metadata.get("role")},
    ]
    return any(len(values) > 1 for values in fields)


def _common_value(nodes: Sequence[ServiceNode], field: str) -> Optional[str]:
    values = {getattr(node, field) for node in nodes if getattr(node, field)}
    return next(iter(values)) if len(values) == 1 else None


def _is_network_flow(flow: Flow, nodes_by_id: Dict[str, ServiceNode]) -> bool:
    source = nodes_by_id[flow.source]
    target = nodes_by_id[flow.target]
    private_integration = _flow_type(flow) == "private_integration"
    endpoint_related = flow.metadata.get("endpoint_access_path") or "endpoint" in flow.id or flow.metadata.get("endpoint")
    bridge_related = "vpc_link" in flow.id or source.service == "vpc_link" or target.service == "vpc_link"
    load_balancer_related = "lb" in flow.id or source.service in {"alb", "nlb", "load_balancer"} or target.service in {"alb", "nlb", "load_balancer"}
    vpc_related = _is_vpc_resident(source.scope) or _is_vpc_resident(target.scope)
    return bool(private_integration or endpoint_related or bridge_related or load_balancer_related or vpc_related)


def _flow_type(flow: Flow) -> str:
    metadata_type = flow.metadata.get("classification") or flow.metadata.get("edge_type") or flow.metadata.get("edge_kind")
    if flow.edge_type and flow.edge_type != "request":
        return flow.edge_type
    return metadata_type or flow.edge_type or "request"


def _is_endpoint_internal_hop(flow: Flow, nodes_by_id: Dict[str, ServiceNode]) -> bool:
    source = nodes_by_id.get(flow.source)
    target = nodes_by_id.get(flow.target)
    return bool(
        source is not None
        and target is not None
        and source.service == "vpc_endpoint"
        and flow.metadata.get("endpoint_access_path")
    )


def _infer_endpoint_edge_type(target: ServiceNode, flow: Flow) -> str:
    if flow.edge_type and flow.edge_type != "vpc_endpoint_access":
        return flow.edge_type
    label = (flow.label or "").lower()
    if target.service in {"sqs"}:
        return "async"
    if target.service in {"sns"}:
        return "notification"
    if target.service in {"secrets_manager"}:
        return "secret_access"
    if target.service in {"cloudwatch"}:
        return "observability"
    if target.service in {"bedrock_knowledge_base"}:
        return "rag_retrieval"
    if target.service in {"bedrock"}:
        return "model_invocation"
    if target.service in {"dynamodb", "s3", "opensearch_serverless", "opensearch_vector_index", "opensearch_hybrid_search", "opensearch_domain", "generic_vector_store"}:
        return "data_write" if any(token in label for token in ("write", "store", "reserve", "put")) else "data_read"
    return "request"


def _logical_display_node(node: ServiceNode) -> ServiceNode:
    if node.service == "waf" and "Edge protection" not in node.name:
        return copy_model(node, deep=True, update={"name": f"{node.name} / Edge protection"})
    if node.service == "cognito" and "Identity provider" not in node.name:
        return copy_model(node, deep=True, update={"name": f"{node.name} / Identity provider"})
    if node.service == "vpc_link":
        return copy_model(node, deep=True, update={"name": "VPC Link"})
    if node.service == "opensearch_vector_index" and node.name.lower() in {"vector index", "opensearch vector index"}:
        return copy_model(node, deep=True, update={"name": "OpenSearch Serverless vector index"})
    if node.service == "opensearch_hybrid_search" and "OpenSearch" not in node.name:
        return copy_model(node, deep=True, update={"name": "OpenSearch hybrid search index"})
    if node.service == "opensearch_log_analytics_index" and "OpenSearch" not in node.name:
        return copy_model(node, deep=True, update={"name": "OpenSearch log analytics index"})
    if node.service == "opensearch_application_search_index" and "OpenSearch" not in node.name:
        return copy_model(node, deep=True, update={"name": "OpenSearch application search index"})
    if node.service == "opensearch_domain" and "OpenSearch" not in node.name:
        return copy_model(node, deep=True, update={"name": "OpenSearch VPC domain"})
    if node.service == "generic_vector_store" and "Vector" not in node.name:
        return copy_model(node, deep=True, update={"name": "Vector Store"})
    return copy_model(node, deep=True)


def _is_ai_node(node: ServiceNode) -> bool:
    role = str(node.metadata.get("role") or node.metadata.get("ai_role") or node.category or "")
    return (
        node.service
        in {
            "bedrock",
            "bedrock_knowledge_base",
            "bedrock_agent",
            "bedrock_agentcore",
            "bedrock_guardrails",
            "agent_runtime",
            "sagemaker",
            "opensearch_vector_index",
            "opensearch_hybrid_search",
            "opensearch_log_analytics_index",
            "opensearch_application_search_index",
            "opensearch_domain",
            "generic_vector_store",
        }
        or node.category in {"ai", "ai_application"}
        or role
        in {
            "agent_orchestrator",
            "agent_runtime",
            "planner_agent",
            "worker_agent",
            "reviewer_agent",
            "tool_registry",
            "tool_executor",
            "lambda_tool",
            "ecs_tool",
            "external_tool",
            "model_endpoint",
            "foundation_model",
            "embedding_model",
            "reranker",
            "retrieval_layer",
            "conversation_memory",
            "long_term_memory",
            "prompt_template_store",
            "guardrails",
            "eval_runner",
            "human_approval",
        }
    )


def _connected_to_ai(node_id: str, spec: SemanticArchitectureSpec, nodes_by_id: Dict[str, ServiceNode]) -> bool:
    neighbors = set()
    for flow in spec.flows:
        if flow.source == node_id:
            neighbors.add(flow.target)
        if flow.target == node_id:
            neighbors.add(flow.source)
    return any(neighbor in nodes_by_id and _is_ai_node(nodes_by_id[neighbor]) for neighbor in neighbors)


def _collapse_homogeneous_fanout(
    spec: SemanticArchitectureSpec,
    logical_flows: Sequence[Flow],
) -> Tuple[List[Flow], List[ServiceNode]]:
    groups = _homogeneous_fanout_groups(spec, logical_flows)
    if not groups:
        return list(logical_flows), []
    collapsed_flow_ids = {flow_id for group in groups for flow_id in group["flow_ids"]}
    next_flows = [copy_model(flow, deep=True) for flow in logical_flows if flow.id not in collapsed_flow_ids]
    aggregate_nodes: List[ServiceNode] = []
    flow_by_id = {flow.id: flow for flow in logical_flows}
    for group in groups:
        source_id = str(group["source"])
        group_flow_ids = [str(flow_id) for flow_id in group["flow_ids"]]
        aggregate_id = str(group["aggregate_id"])
        reason = str(group.get("reason") or "homogeneous fan-out summarized to reduce crossings")
        aggregate_nodes.append(
            ServiceNode(
                id=aggregate_id,
                name=str(group["label"]),
                service="semantic_group",
                provider="aws",
                scope="generic_application",
                annotation=True,
                metadata={
                    "homogeneous_fanout_group": True,
                    "source_node_id": source_id,
                    "collapsed_flow_ids": group_flow_ids,
                    "collapse_reason": reason,
                },
            )
        )
        first_flow = flow_by_id[group_flow_ids[0]]
        next_flows.append(
            Flow(
                id=f"{aggregate_id}_summary",
                source=source_id,
                target=aggregate_id,
                label=None,
                edge_type=first_flow.edge_type,
                metadata={
                    "homogeneous_fanout_group": True,
                    "collapsed_flow_ids": group_flow_ids,
                    "source_flow_ids": group_flow_ids,
                    "group_id": aggregate_id,
                    "collapse_reason": reason,
                },
            )
        )
    return next_flows, aggregate_nodes


def _summarize_primary_specialized_subsystems(
    spec: SemanticArchitectureSpec,
    logical_flows: Sequence[Flow],
) -> Tuple[List[Flow], List[ServiceNode]]:
    flow_types = {_flow_type(flow) for flow in spec.flows}
    summary_specs = []
    if flow_types & RAG_RETRIEVAL_EDGE_TYPES and flow_types & RAG_INGESTION_EDGE_TYPES:
        summary_specs.append(
            (
                "ai_ml_layer",
                "AI/ML layer",
                RAG_RETRIEVAL_EDGE_TYPES | RAG_INGESTION_EDGE_TYPES,
                "AI/ML summary",
            )
        )
    elif flow_types & {"rag_retrieval", "vector_search", "hybrid_search", "source_reference"}:
        summary_specs.append(
            (
                "rag_subsystem",
                "RAG subsystem",
                {"rag_retrieval", "vector_search", "hybrid_search", "source_reference"},
                "RAG retrieval",
            )
        )
    if flow_types & AGENT_MEMORY_EDGE_TYPES:
        summary_specs.append(("agent_memory_summary", "Agent memory", AGENT_MEMORY_EDGE_TYPES, "Memory access"))
    if not summary_specs:
        return list(logical_flows), []

    nodes_by_id = {node.id: node for node in spec.nodes}
    summary_nodes: List[ServiceNode] = []
    next_flows = list(logical_flows)
    for summary_id, label, summarized_types, edge_label in summary_specs:
        matching = [flow for flow in next_flows if _flow_type(flow) in summarized_types]
        if len(matching) < 3:
            continue
        summarized_flow_ids = {flow.id for flow in matching}
        involved_targets = {flow.target for flow in matching}
        candidate_sources = [flow.source for flow in matching if flow.source not in involved_targets]
        source_id = candidate_sources[0] if candidate_sources else matching[0].source
        source = nodes_by_id.get(source_id)
        if source is None:
            continue
        next_flows = [flow for flow in next_flows if flow.id not in summarized_flow_ids]
        summary_nodes.append(
            ServiceNode(
                id=summary_id,
                name=label,
                service="semantic_group",
                provider=source.provider,
                scope="generic_application",
                annotation=True,
                metadata={
                    "specialized_subsystem_summary": True,
                    "source_node_id": source_id,
                    "collapsed_flow_ids": sorted(summarized_flow_ids),
                    "collapse_reason": "specialized view summarizes detailed subsystem internals",
                },
            )
        )
        next_flows.append(
            Flow(
                id=f"{summary_id}_overview",
                source=source_id,
                target=summary_id,
                label=edge_label,
                edge_type=matching[0].edge_type,
                metadata={
                    "specialized_subsystem_summary": True,
                    "source_flow_ids": sorted(summarized_flow_ids),
                    "collapse_reason": "specialized view summarizes detailed subsystem internals",
                },
            )
        )
    return next_flows, summary_nodes


def _homogeneous_fanout_groups(spec: SemanticArchitectureSpec, flows: Sequence[Flow]) -> List[Dict[str, object]]:
    nodes_by_id = {node.id: node for node in spec.nodes}
    outgoing: Dict[str, List[Flow]] = defaultdict(list)
    for flow in flows:
        if flow.source in nodes_by_id and flow.target in nodes_by_id:
            outgoing[flow.source].append(flow)

    groups: List[Dict[str, object]] = []
    consumed_flow_ids: Set[str] = set()
    for source_id, source_flows in sorted(outgoing.items()):
        local_threshold = _fanout_threshold(source_flows, nodes_by_id)
        if len(source_flows) <= local_threshold:
            continue
        candidates: List[Tuple[str, str, List[Flow]]] = []
        for dimension in ("service", "scope", "role"):
            by_key: Dict[str, List[Flow]] = defaultdict(list)
            for flow in source_flows:
                target = nodes_by_id[flow.target]
                key = _homogeneous_key(target, dimension)
                if key:
                    by_key[key].append(flow)
            for key, grouped_flows in by_key.items():
                if len(grouped_flows) > local_threshold:
                    candidates.append((dimension, key, grouped_flows))
        if not candidates:
            continue
        candidates.sort(key=lambda item: ({"role": 0, "service": 1, "scope": 2}[item[0]], -len(item[2]), item[1]))
        dimension, key, grouped_flows = candidates[0]
        eligible_flows = [flow for flow in grouped_flows if flow.id not in consumed_flow_ids]
        target_ids = _ordered_unique_target_ids(eligible_flows)
        if len(target_ids) <= local_threshold:
            continue
        flow_ids = [
            flow.id
            for flow in sorted(
                eligible_flows,
                key=lambda item: (_target_position(item.target, target_ids), _natural_key(item.target), _natural_key(item.id)),
            )
        ]
        consumed_flow_ids.update(flow_ids)
        source = nodes_by_id[source_id]
        targets = [nodes_by_id[target_id] for target_id in target_ids]
        aggregate_id = f"{source_id}_{_safe_identifier(key)}_fanout_group"
        groups.append(
            {
                "source": source_id,
                "dimension": dimension,
                "key": key,
                "flow_ids": flow_ids,
                "target_ids": target_ids,
                "aggregate_id": aggregate_id,
                "label": _homogeneous_fanout_label(source, targets, key, len(target_ids)),
                "reason": _homogeneous_fanout_reason(source, targets, source_flows),
            }
        )
    return groups


def _homogeneous_key(node: ServiceNode, dimension: str) -> str:
    if dimension == "service":
        return node.service
    if dimension == "scope":
        return node.scope or ""
    role = node.metadata.get("role") or node.metadata.get("ai_role") or node.logical_group
    return str(role or "")


def _homogeneous_fanout_label(source: ServiceNode, targets: Sequence[ServiceNode], key: str, count: int) -> str:
    target_services = {target.service for target in targets}
    target_roles = {str(target.metadata.get("role") or target.metadata.get("ai_role") or target.category or "") for target in targets}
    source_role = str(source.metadata.get("role") or source.metadata.get("ai_role") or source.service)
    if any("tool" in role for role in target_roles) or (target_services <= {"lambda", "ecs"} and "agent" in source_role):
        return f"Agent tools ×{count}"
    if source.service == "sns" and target_services == {"sqs"}:
        return f"SQS subscriber queues ×{count}"
    if source.service == "eventbridge":
        return f"Event targets ×{count}"
    if key == "lambda" or target_services == {"lambda"}:
        return f"Lambda workers ×{count}"
    if source.service == "step_functions":
        return f"Parallel worker tasks ×{count}"
    first_target = targets[0] if targets else None
    base = (first_target.category if first_target and first_target.category else key).replace("_", " ").title()
    return f"{base} targets ×{count}"


def _homogeneous_fanout_reason(source: ServiceNode, targets: Sequence[ServiceNode], flows: Sequence[Flow]) -> str:
    target_roles = {str(target.metadata.get("role") or target.metadata.get("ai_role") or target.category or "") for target in targets}
    if any((flow.edge_type or flow.metadata.get("classification")) == "tool_invocation" for flow in flows) or any("tool" in role for role in target_roles):
        return "agent tool fan-out summarized to reduce crossings"
    return "homogeneous fan-out summarized to reduce crossings"


def _fanout_threshold(flows: Sequence[Flow], nodes_by_id: Dict[str, ServiceNode]) -> int:
    for flow in flows:
        target = nodes_by_id.get(flow.target)
        role = str((target.metadata.get("role") or target.metadata.get("ai_role") or target.category or "") if target else "")
        if (flow.edge_type or flow.metadata.get("classification")) == "tool_invocation" or "tool" in role:
            return 5
    return HOMOGENEOUS_FANOUT_THRESHOLD


def _source_flow_id(flow: Flow) -> str:
    return flow.id
