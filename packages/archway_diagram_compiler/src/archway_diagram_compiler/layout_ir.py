"""Transitional LayoutModel builder.

This module makes layout explicit while the renderer is being migrated away
from raw SemanticArchitectureSpec consumption.
"""

from collections import defaultdict
import re
from typing import Dict, List, Optional, Sequence, Tuple

from archway_diagram_compiler._compat import copy_model
from archway_diagram_compiler.lane_templates import lane_ids_for_template
from archway_diagram_compiler.models import (
    Flow,
    LayoutConstraint,
    LayoutEdge,
    LayoutGroup,
    LayoutLane,
    LayoutModel,
    LayoutNode,
    LayoutParallelGroup,
    SemanticArchitectureSpec,
)


def build_layout_model_from_view(spec: SemanticArchitectureSpec) -> LayoutModel:
    view_id = spec.metadata.get("diagram_view", "view")
    nodes_by_id = {node.id: node for node in spec.nodes}
    lane_by_node = _assign_lanes(spec)
    lane_ids = _materialized_lane_ids(spec, lane_by_node.values())
    group = LayoutGroup(id=f"{view_id}_root", label=spec.title, parent_id=None, group_type="view", order=0)
    lanes = [
        LayoutLane(
            id=lane_id,
            label=_lane_label_for_spec(spec, lane_id),
            group_id=group.id,
            order=index,
            orientation="vertical",
            max_nodes=24,
        )
        for index, lane_id in enumerate(lane_ids)
    ]
    layout_nodes: List[LayoutNode] = []
    node_orders = _node_orders(spec, lane_by_node)
    for order, node in enumerate(sorted(spec.nodes, key=lambda item: node_orders.get(item.id, (99, 99, item.id)))):
        lane_id = lane_by_node.get(node.id, "unassigned")
        layout_nodes.append(
            LayoutNode(
                id=node.id,
                source_node_ids=[node.id],
                label=node.name,
                subtitle=None,
                service=node.service,
                provider=node.provider,
                icon=None,
                lane_id=lane_id,
                rank=node_orders.get(node.id, (99, 99, node.id))[1],
                order=order,
                placement_scope=node.scope or "unknown",
                role=str(node.metadata.get("role") or node.category or node.service),
                is_virtual=node.annotation,
                metadata=dict(node.metadata),
            )
        )
    layout_edges = [
        _layout_edge(flow)
        for flow in sorted(spec.flows, key=lambda item: _natural_key(item.id))
        if flow.source in nodes_by_id and flow.target in nodes_by_id
    ]
    layout_nodes, layout_edges = _apply_high_fanout_grouping(view_id, layout_nodes, layout_edges)
    layout_nodes, layout_edges = _apply_shared_incoming_grouping(view_id, layout_nodes, layout_edges)
    layout_nodes, layout_edges = _materialize_self_loops(layout_nodes, layout_edges)
    layout_nodes, layout_edges = _apply_endpoint_access_grouping(view_id, layout_nodes, layout_edges)
    layout_nodes, layout_edges = _separate_same_lane_fanout_targets(view_id, layout_nodes, layout_edges)
    layout_nodes = _wrap_large_fanout_targets(view_id, layout_nodes, layout_edges)
    parallel_groups = _parallel_groups_from_layout(view_id, layout_nodes, layout_edges)
    fanout_lane_labels = _fanout_lane_labels(layout_nodes)
    lane_ids = _materialized_lane_ids(spec, (node.lane_id for node in layout_nodes))
    lanes = [
        LayoutLane(
            id=lane_id,
            label=fanout_lane_labels.get(lane_id, _lane_label_for_spec(spec, lane_id)),
            group_id=group.id,
            order=index,
            orientation="vertical",
            max_nodes=24,
        )
        for index, lane_id in enumerate(lane_ids)
    ]
    constraints = [
        LayoutConstraint(type="route_orthogonal", nodes=[edge.source, edge.target], value={"edge_id": edge.id})
        for edge in layout_edges
    ]
    return LayoutModel(
        view_id=view_id,
        title=spec.title,
        groups=[group],
        lanes=lanes,
        nodes=layout_nodes,
        edges=layout_edges,
        parallel_groups=parallel_groups,
        constraints=constraints,
        metadata={"source": "semantic_view_transitional"},
    )


def _materialized_lane_ids(spec: SemanticArchitectureSpec, lane_ids: Sequence[str]) -> List[str]:
    used_lanes = set(lane_ids)
    ordered_lanes = [lane_id for lane_id in _lane_order(spec) if lane_id in used_lanes]
    extra_lanes = sorted(used_lanes - set(ordered_lanes), key=_natural_key)
    return ordered_lanes + extra_lanes


def _materialize_self_loops(nodes: List[LayoutNode], edges: List[LayoutEdge]) -> Tuple[List[LayoutNode], List[LayoutEdge]]:
    nodes_by_id = {node.id: node for node in nodes}
    next_nodes = list(nodes)
    next_edges: List[LayoutEdge] = []
    for edge in edges:
        if edge.source != edge.target:
            next_edges.append(edge)
            continue
        source = nodes_by_id.get(edge.source)
        if source is None:
            continue
        loop_node_id = f"{edge.id}_self_reference"
        next_nodes.append(
            LayoutNode(
                id=loop_node_id,
                source_node_ids=[],
                label=edge.label or "Self reference",
                subtitle=None,
                service="semantic_group",
                provider=source.provider,
                icon=None,
                lane_id=source.lane_id,
                rank=source.rank + 1,
                order=source.order + 1,
                placement_scope=source.placement_scope,
                role="self_loop",
                is_virtual=True,
                metadata={"self_loop": True, "source_node_id": source.id, "source_flow_ids": edge.source_flow_ids},
            )
        )
        next_edges.append(
            copy_model(
                edge,
                deep=True,
                update={
                    "target": loop_node_id,
                    "label": edge.label or "self reference",
                    "metadata": {**edge.metadata, "self_loop_rendered_as": loop_node_id},
                },
            )
        )
    return next_nodes, next_edges


def _layout_edge(flow: Flow) -> LayoutEdge:
    edge_type = flow.edge_type or flow.metadata.get("edge_type") or flow.metadata.get("classification") or "request"
    if edge_type == "data":
        edge_type = "request"
    style = "dashed" if edge_type in {"auth", "control", "encryption", "guardrail_check", "evaluation", "human_approval"} or flow.metadata.get("edge_kind") == "control" else "solid"
    if edge_type in {"audit", "observability", "audit_trace", "model_observability"}:
        style = "dotted"
    return LayoutEdge(
        id=flow.id,
        source=flow.source,
        target=flow.target,
        source_flow_ids=[str(item) for item in flow.metadata.get("source_flow_ids", [flow.id])],
        label=flow.label,
        edge_type=edge_type,  # type: ignore[arg-type]
        style=style,  # type: ignore[arg-type]
        route_preference="orthogonal",
        criticality="secondary" if style != "solid" else "primary",
        metadata=dict(flow.metadata),
    )


def _apply_high_fanout_grouping(
    view_id: str,
    nodes: List[LayoutNode],
    edges: List[LayoutEdge],
    threshold: int = 3,
) -> Tuple[List[LayoutNode], List[LayoutEdge]]:
    if view_id not in {"production_logical_service_flow", "logical_service_flow", "network_private_connectivity", "ai_logical_service_flow"}:
        return nodes, edges

    nodes_by_id = {node.id: node for node in nodes}
    outgoing: Dict[str, List[LayoutEdge]] = defaultdict(list)
    for edge in edges:
        source = nodes_by_id.get(edge.source)
        if source is None or not _can_group_source(source):
            continue
        if edge.edge_type not in {
            "data_read",
            "data_write",
            "vpc_endpoint_access",
            "async",
            "event",
            "notification",
            "secret_access",
            "observability",
            "control",
            "request",
            "tool_invocation",
            "agent_orchestration",
            "agent_handoff",
            "memory_read",
            "memory_write",
            "prompt_lookup",
            "rag_retrieval",
            "model_invocation",
        }:
            continue
        outgoing[edge.source].append(edge)

    next_nodes = list(nodes)
    next_edges = list(edges)
    for source_id, source_edges in sorted(outgoing.items()):
        if len(source_edges) <= threshold:
            continue
        grouped = defaultdict(list)
        for edge in source_edges:
            grouped[_fanout_group_key(edge)].append(edge)
        for group_order, (group_key, group_edges) in enumerate(sorted(grouped.items())):
            source = nodes_by_id[source_id]
            group_id = f"{source_id}_{group_key}_group"
            if group_id not in nodes_by_id:
                is_logical_parallel = view_id in {"production_logical_service_flow", "logical_service_flow"}
                group_node = LayoutNode(
                    id=group_id,
                    source_node_ids=[],
                    label=_fanout_group_label(group_key),
                    subtitle=None,
                    service="semantic_group",
                    provider=source.provider,
                    icon=None,
                    lane_id=source.lane_id,
                    rank=source.rank + group_order + 1,
                    order=source.order + group_order + 1,
                    placement_scope=source.placement_scope,
                    role=group_key,
                    is_virtual=True,
                    metadata={
                        "fanout_group": True,
                        "group_key": group_key,
                        "source_node_id": source_id,
                        "parallel_dependency_group": is_logical_parallel,
                    },
                )
                nodes_by_id[group_id] = group_node
                next_nodes.append(group_node)
            original_ids = {edge.id for edge in group_edges}
            next_edges = [edge for edge in next_edges if edge.id not in original_ids]
            next_edges.append(
                LayoutEdge(
                    id=f"{source_id}_{group_key}_fanout",
                    source=source_id,
                    target=group_id,
                    source_flow_ids=[flow_id for edge in group_edges for flow_id in edge.source_flow_ids],
                    label=_fanout_group_label(group_key),
                    edge_type=group_edges[0].edge_type,
                    style="solid",
                    route_preference="orthogonal",
                    criticality="primary",
                    metadata={"collapsed_flow_ids": [edge.id for edge in group_edges], "fanout_group": group_key},
                )
            )
            for edge in group_edges:
                next_edges.append(
                    copy_model(
                        edge,
                        deep=True,
                        update={
                            "source": group_id,
                            "id": f"{edge.id}_from_group",
                            "metadata": {**edge.metadata, "fanout_group": group_key, "source_flow_ids": edge.source_flow_ids},
                        },
                    )
                )
    return next_nodes, next_edges


def _apply_shared_incoming_grouping(
    view_id: str,
    nodes: List[LayoutNode],
    edges: List[LayoutEdge],
    threshold: int = 5,
) -> Tuple[List[LayoutNode], List[LayoutEdge]]:
    if view_id not in {"production_logical_service_flow", "logical_service_flow", "data_access_view", "network_private_connectivity"}:
        return nodes, edges
    nodes_by_id = {node.id: node for node in nodes}
    incoming: Dict[str, List[LayoutEdge]] = defaultdict(list)
    for edge in edges:
        target = nodes_by_id.get(edge.target)
        source = nodes_by_id.get(edge.source)
        if source is None or target is None or target.is_virtual:
            continue
        if view_id == "network_private_connectivity" and source.service == "vpc_endpoint":
            continue
        if edge.edge_type not in {"data_read", "data_write", "vpc_endpoint_access", "request", "async"}:
            continue
        if target.placement_scope not in {
            "regional_managed_data",
            "vpc_resident",
            "vpc_data",
            "regional_integration",
            "regional_managed_ai",
        }:
            continue
        incoming[edge.target].append(edge)

    next_nodes = list(nodes)
    next_edges = list(edges)
    for target_id, target_edges in sorted(incoming.items()):
        if len(target_edges) <= threshold:
            continue
        target = nodes_by_id[target_id]
        group_id = f"{target_id}_shared_access_group"
        if group_id not in nodes_by_id:
            group_node = LayoutNode(
                id=group_id,
                source_node_ids=[],
                label="Shared data access",
                subtitle=None,
                service="semantic_group",
                provider=target.provider,
                icon=None,
                lane_id=target.lane_id,
                rank=max(0, target.rank - 1),
                order=max(0, target.order - 1),
                placement_scope=target.placement_scope,
                role="shared_dependency",
                is_virtual=True,
                metadata={"incoming_group": True, "target_node_id": target_id},
            )
            nodes_by_id[group_id] = group_node
            next_nodes.append(group_node)
        original_ids = {edge.id for edge in target_edges}
        next_edges = [edge for edge in next_edges if edge.id not in original_ids]
        for edge in target_edges:
            next_edges.append(
                copy_model(
                    edge,
                    deep=True,
                    update={
                        "target": group_id,
                        "id": f"{edge.id}_to_shared_group",
                        "metadata": {**edge.metadata, "incoming_group": "shared_data_access"},
                    },
                )
            )
        next_edges.append(
            LayoutEdge(
                id=f"{group_id}_to_{target_id}",
                source=group_id,
                target=target_id,
                source_flow_ids=[flow_id for edge in target_edges for flow_id in edge.source_flow_ids],
                label="shared dependency",
                edge_type=target_edges[0].edge_type,
                style="solid",
                route_preference="orthogonal",
                criticality="primary",
                metadata={"collapsed_flow_ids": [edge.id for edge in target_edges], "incoming_group": "shared_data_access"},
            )
        )
    return next_nodes, next_edges


def _apply_endpoint_access_grouping(
    view_id: str,
    nodes: List[LayoutNode],
    edges: List[LayoutEdge],
    threshold: int = 2,
) -> Tuple[List[LayoutNode], List[LayoutEdge]]:
    if view_id != "network_private_connectivity":
        return nodes, edges
    nodes_by_id = {node.id: node for node in nodes}
    endpoint_edges: Dict[str, List[LayoutEdge]] = defaultdict(list)
    for edge in edges:
        source = nodes_by_id.get(edge.source)
        target = nodes_by_id.get(edge.target)
        if source is None or target is None:
            continue
        if target.service == "vpc_endpoint" and _is_vpc_workload(source):
            endpoint_edges[edge.source].append(edge)

    next_nodes = list(nodes)
    next_edges = list(edges)
    for source_id, source_edges in sorted(endpoint_edges.items()):
        if len(source_edges) <= threshold:
            continue
        source = nodes_by_id[source_id]
        group_id = f"{source_id}_private_access_group"
        group_label = _endpoint_access_group_label(source_edges, nodes_by_id)
        group_node = LayoutNode(
            id=group_id,
            source_node_ids=[],
            label=group_label,
            subtitle=None,
            service="semantic_group",
            provider=source.provider,
            icon=None,
            lane_id=source.lane_id,
            rank=source.rank + 1,
            order=source.order + 1,
            placement_scope=source.placement_scope,
            role="endpoint_access_group",
            is_virtual=True,
            metadata={
                "endpoint_access_group": True,
                "endpoint_access_explanation": "Parallel access paths",
                "source_node_id": source_id,
                "branch_node_ids": [edge.target for edge in source_edges],
                "source_flow_ids": [flow_id for edge in source_edges for flow_id in edge.source_flow_ids],
            },
        )
        if group_id not in nodes_by_id:
            nodes_by_id[group_id] = group_node
            next_nodes.append(group_node)
        original_ids = {edge.id for edge in source_edges}
        next_edges = [edge for edge in next_edges if edge.id not in original_ids]
        next_edges.append(
            LayoutEdge(
                id=f"{source_id}_private_access_group_edge",
                source=source_id,
                target=group_id,
                source_flow_ids=[flow_id for edge in source_edges for flow_id in edge.source_flow_ids],
                label="private access",
                edge_type="vpc_endpoint_access",
                style="solid",
                route_preference="orthogonal",
                criticality="primary",
                metadata={"endpoint_access_group": True, "branch_node_ids": [edge.target for edge in source_edges]},
            )
        )
        for index, edge in enumerate(sorted(source_edges, key=lambda item: _natural_key(item.target))):
            endpoint = nodes_by_id[edge.target]
            nodes_by_id[edge.target] = copy_model(
                endpoint,
                deep=True,
                update={
                    "lane_id": "private_access_paths",
                    "rank": index,
                    "order": group_node.order + index + 1,
                    "metadata": {**endpoint.metadata, "endpoint_access_branch": True, "source_node_id": source_id},
                },
            )
            next_nodes = [nodes_by_id[item.id] if item.id == edge.target else item for item in next_nodes]
            next_edges.append(
                copy_model(
                    edge,
                    deep=True,
                    update={
                        "source": group_id,
                        "id": f"{edge.id}_from_private_access_group",
                        "label": None,
                        "metadata": {**edge.metadata, "endpoint_access_group": group_id},
                    },
                )
            )
    return next_nodes, next_edges


def _endpoint_access_group_label(source_edges: Sequence[LayoutEdge], nodes_by_id: Dict[str, LayoutNode]) -> str:
    endpoint_labels = " ".join(nodes_by_id[edge.target].label.lower() for edge in source_edges if edge.target in nodes_by_id)
    if any(token in endpoint_labels for token in ("bedrock", "opensearch", "vector")):
        return "Private AI service access"
    if any(token in endpoint_labels for token in ("dynamodb", "s3", "rds", "data")):
        return "Private data access"
    return "Private AWS service access"


def _is_vpc_workload(node: LayoutNode) -> bool:
    return node.placement_scope in {"vpc_resident", "vpc_workload", "vpc_data"}


def _separate_same_lane_fanout_targets(
    view_id: str,
    nodes: List[LayoutNode],
    edges: List[LayoutEdge],
    threshold: int = 2,
) -> Tuple[List[LayoutNode], List[LayoutEdge]]:
    if view_id not in {"production_logical_service_flow", "logical_service_flow"}:
        return nodes, edges
    nodes_by_id = {node.id: node for node in nodes}
    outgoing: Dict[str, List[LayoutEdge]] = defaultdict(list)
    for edge in edges:
        source = nodes_by_id.get(edge.source)
        target = nodes_by_id.get(edge.target)
        if source is None or target is None or target.is_virtual:
            continue
        if source.lane_id == target.lane_id:
            outgoing[edge.source].append(edge)
    next_nodes = list(nodes)
    next_edges = list(edges)
    for source_id, source_edges in sorted(outgoing.items()):
        if len(source_edges) < threshold:
            continue
        source = nodes_by_id[source_id]
        group_id = f"{source_id}_dependency_handoff"
        if group_id not in nodes_by_id:
            group = LayoutNode(
                id=group_id,
                source_node_ids=[],
                label="Parallel dependencies",
                subtitle=None,
                service="semantic_group",
                provider=source.provider,
                icon=None,
                lane_id=source.lane_id,
                rank=source.rank + 1,
                order=source.order + 1,
                placement_scope=source.placement_scope,
                role="dependency_handoff",
                is_virtual=True,
                metadata={"same_lane_fanout_group": True, "source_node_id": source_id},
            )
            nodes_by_id[group_id] = group
            next_nodes.append(group)
        edge_ids = {edge.id for edge in source_edges}
        next_edges = [edge for edge in next_edges if edge.id not in edge_ids]
        next_edges.append(
            LayoutEdge(
                id=f"{source_id}_dependency_handoff_edge",
                source=source_id,
                target=group_id,
                source_flow_ids=[flow_id for edge in source_edges for flow_id in edge.source_flow_ids],
                label="dependencies",
                edge_type=source_edges[0].edge_type,
                style="solid",
                route_preference="orthogonal",
                criticality="primary",
                metadata={"same_lane_fanout_group": True, "collapsed_edge_ids": sorted(edge_ids)},
            )
        )
        for edge in source_edges:
            target = nodes_by_id[edge.target]
            target_lane = "service_dependencies" if target.lane_id == source.lane_id else target.lane_id
            nodes_by_id[edge.target] = copy_model(target, deep=True, update={"lane_id": target_lane})
            next_nodes = [
                nodes_by_id[item.id] if item.id == edge.target else item
                for item in next_nodes
            ]
            next_edges.append(
                copy_model(
                    edge,
                    deep=True,
                    update={
                        "source": group_id,
                        "id": f"{edge.id}_from_dependency_handoff",
                        "label": edge.label or _short_edge_label(edge),
                        "metadata": {**edge.metadata, "same_lane_fanout_group": True},
                    },
                )
            )
    return next_nodes, next_edges


def _wrap_large_fanout_targets(
    view_id: str,
    nodes: List[LayoutNode],
    edges: List[LayoutEdge],
    chunk_size: int = 4,
) -> List[LayoutNode]:
    if view_id not in {"production_logical_service_flow", "logical_service_flow", "fanout_detail_view"}:
        return nodes
    nodes_by_id = {node.id: node for node in nodes}
    incoming_by_source: Dict[str, List[LayoutEdge]] = defaultdict(list)
    for edge in edges:
        incoming_by_source[edge.source].append(edge)
    updates: Dict[str, LayoutNode] = {}
    for source_id, source_edges in incoming_by_source.items():
        targets = [nodes_by_id[edge.target] for edge in source_edges if edge.target in nodes_by_id and not nodes_by_id[edge.target].is_virtual]
        if len(targets) <= chunk_size:
            continue
        source = nodes_by_id.get(source_id)
        base_order = source.order if source is not None else 0
        for index, target in enumerate(sorted(targets, key=lambda item: _natural_key(item.id))):
            lane_id = f"fanout_targets_{index // chunk_size + 1}"
            updates[target.id] = copy_model(
                target,
                deep=True,
                update={
                    "lane_id": lane_id,
                    "rank": index % chunk_size,
                    "order": base_order + index + 1,
                    "metadata": {**target.metadata, "fanout_wrapped": True, "fanout_source_id": source_id},
                },
            )
    return [updates.get(node.id, node) for node in nodes]


def _parallel_groups_from_layout(
    view_id: str,
    nodes: List[LayoutNode],
    edges: List[LayoutEdge],
) -> List[LayoutParallelGroup]:
    nodes_by_id = {node.id: node for node in nodes}
    outgoing: Dict[str, List[LayoutEdge]] = defaultdict(list)
    for edge in edges:
        outgoing[edge.source].append(edge)

    groups: List[LayoutParallelGroup] = []
    for node in nodes:
        if node.metadata.get("endpoint_access_group"):
            branch_node_ids = [str(item) for item in node.metadata.get("branch_node_ids", [])]
            target_node_ids = _target_ids_reached_by_branches(branch_node_ids, outgoing)
            groups.append(
                LayoutParallelGroup(
                    id=node.id,
                    source_node_id=str(node.metadata.get("source_node_id") or ""),
                    group_label=node.label,
                    group_type="endpoint_access_group",
                    branch_node_ids=branch_node_ids,
                    target_node_ids=target_node_ids,
                    source_flow_ids=[str(item) for item in node.metadata.get("source_flow_ids", [])],
                    render_mode="bus_and_branches",
                    preferred_direction="left_to_right",
                    max_branches_per_lane=4,
                )
            )
        if node.metadata.get("homogeneous_fanout_group") or node.metadata.get("fanout_group"):
            branch_edges = outgoing.get(node.id, [])
            group_type = "tool_fanout" if "tool" in node.label.lower() else "homogeneous_fanout"
            groups.append(
                LayoutParallelGroup(
                    id=node.id,
                    source_node_id=str(node.metadata.get("source_node_id") or ""),
                    group_label=node.label,
                    group_type=group_type,
                    branch_node_ids=[edge.target for edge in branch_edges],
                    target_node_ids=[edge.target for edge in branch_edges],
                    source_flow_ids=[flow_id for edge in branch_edges for flow_id in edge.source_flow_ids],
                    render_mode="detail_grid" if view_id == "fanout_detail_view" else "summary_only",
                    preferred_direction="left_to_right",
                    max_branches_per_lane=4,
                    detail_view_id="fanout_detail_view" if view_id != "fanout_detail_view" else None,
                )
            )
    return groups


def _target_ids_reached_by_branches(branch_node_ids: Sequence[str], outgoing: Dict[str, List[LayoutEdge]]) -> List[str]:
    target_ids: List[str] = []
    for branch_id in branch_node_ids:
        for edge in outgoing.get(branch_id, []):
            if edge.target not in target_ids:
                target_ids.append(edge.target)
    return target_ids


def _short_edge_label(edge: LayoutEdge) -> str:
    if edge.edge_type in {"data_read", "data_write"}:
        return "data"
    if edge.edge_type in {"request"}:
        return "request"
    return edge.edge_type.replace("_", " ")


def _can_group_source(node: LayoutNode) -> bool:
    return (
        node.placement_scope in {"vpc_resident", "vpc_workload", "vpc_data", "regional_compute", "generic_application"}
        or node.service in {"ecs", "eks", "ec2", "lambda", "generic_application", "bedrock_agent", "bedrock_agentcore", "agent_runtime"}
        or node.role in {"agent_orchestrator", "agent_runtime", "planner_agent", "worker_agent", "reviewer_agent"}
    )


def _fanout_group_key(edge: LayoutEdge) -> str:
    if edge.edge_type in {"data_read", "data_write", "vpc_endpoint_access"}:
        return "data_access"
    if edge.edge_type in {"async", "event", "notification"}:
        return "async_trigger"
    if edge.edge_type in {"secret_access", "encryption"}:
        return "secrets_access"
    if edge.edge_type in {"observability", "audit"}:
        return "observability"
    if edge.edge_type in {"model_invocation"}:
        return "model_invocation"
    if edge.edge_type in {"rag_retrieval", "vector_search", "hybrid_search", "source_reference"}:
        return "rag_retrieval"
    if edge.edge_type in {"tool_invocation"}:
        return "tool_invocation"
    if edge.edge_type in {"agent_orchestration", "agent_handoff"}:
        return "agent_orchestration"
    if edge.edge_type in {"memory_read", "memory_write", "prompt_lookup"}:
        return "agent_memory"
    if edge.edge_type in {"guardrail_check", "evaluation", "human_approval"}:
        return "ai_governance"
    if edge.edge_type in {"control", "auth"}:
        return "control_dependency"
    return "service_dependencies"


def _fanout_group_label(group_key: str) -> str:
    labels = {
        "data_access": "Business data writes",
        "async_trigger": "Async fulfillment",
        "secrets_access": "Secrets access",
        "observability": "Observability",
        "model_invocation": "Model invocation",
        "rag_retrieval": "RAG retrieval",
        "tool_invocation": "Tool fan-out",
        "agent_orchestration": "Agent orchestration",
        "agent_memory": "Memory access",
        "ai_governance": "AI governance",
        "control_dependency": "Payment validation",
        "service_dependencies": "Service dependencies",
    }
    return labels[group_key]


def _assign_lanes(spec: SemanticArchitectureSpec) -> Dict[str, str]:
    chain_lanes = _chain_wrap_lanes(spec)
    if chain_lanes:
        return chain_lanes
    is_network_view = spec.metadata.get("diagram_view") == "network_private_connectivity"
    lanes: Dict[str, str] = {}
    for node in spec.nodes:
        if spec.metadata.get("lane_template") == "semantic_archway":
            semantic_lane = _semantic_lane_id(node.metadata.get("lane_label") or node.logical_group)
            if semantic_lane:
                lanes[node.id] = semantic_lane
                continue
        role = str(node.metadata.get("role") or node.metadata.get("ai_role") or node.category or node.service)
        if is_network_view and (node.scope in {"vpc_resident", "vpc_workload", "vpc_data"} or node.service in {"vpc_link", "alb", "nlb", "vpc_endpoint"}):
            lanes[node.id] = "private_backend"
        elif node.service in {"waf", "cognito"}:
            lanes[node.id] = "edge_identity_controls"
        elif node.service in {"external_actor", "external_user", "route53", "cloudfront", "api_gateway"}:
            lanes[node.id] = "request_path"
        elif node.service in {"bedrock_agent", "bedrock_agentcore", "agent_runtime"} or role in {"agent_orchestrator", "agent_runtime", "planner_agent", "worker_agent", "reviewer_agent"}:
            lanes[node.id] = "agent_orchestration"
        elif role in {"tool_registry"}:
            lanes[node.id] = "tool_registry"
        elif role in {"tool_executor", "lambda_tool", "ecs_tool", "external_tool"}:
            lanes[node.id] = "tool_execution"
        elif role in {"embedding_generation"} or (spec.metadata.get("diagram_view") == "rag_ingestion_view" and role in {"embedding_model", "reranker"}):
            lanes[node.id] = "embedding_generation"
        elif node.service in {"bedrock", "sagemaker"} or role in {"model_endpoint", "foundation_model", "embedding_model", "reranker"}:
            lanes[node.id] = "model_invocation"
        elif node.service in {"bedrock_knowledge_base"} or role in {"retrieval_layer"}:
            lanes[node.id] = "rag_retrieval"
        elif node.service in {"opensearch_vector_index", "opensearch_hybrid_search", "opensearch_serverless", "generic_vector_store"} or role in {"vector_index", "vector_store", "hybrid_search_index"}:
            lanes[node.id] = "vector_search"
        elif node.service in {"opensearch_log_analytics_index"} or role in {"log_analytics_index", "audit_store"}:
            lanes[node.id] = "ai_governance"
        elif node.service in {"opensearch_application_search_index", "opensearch_domain"} or role in {"application_search_index", "opensearch_domain"}:
            lanes[node.id] = "managed_data"
        elif role in {"document_store", "source_documents", "data_source"}:
            lanes[node.id] = "data_sources"
        elif role in {"document_ingestion"}:
            lanes[node.id] = "document_ingestion"
        elif role in {"chunking", "document_chunker"}:
            lanes[node.id] = "document_processing"
        elif role in {"conversation_memory", "long_term_memory", "memory_store"}:
            lanes[node.id] = "memory"
        elif role in {"prompt_template_store"}:
            lanes[node.id] = "prompt_templates"
        elif node.service in {"bedrock_guardrails"} or role in {"guardrails", "eval_runner", "human_approval"}:
            lanes[node.id] = "ai_governance"
        elif node.scope in {"vpc_resident", "vpc_workload", "vpc_data"} or node.service in {"vpc_link", "alb", "nlb"}:
            lanes[node.id] = "private_backend"
        elif node.service in {"lambda", "sqs", "dynamodb"}:
            lanes[node.id] = "service_dependencies"
        elif node.service in {"step_functions", "eventbridge"}:
            lanes[node.id] = "fulfillment_flow"
        elif node.service in {"sns", "s3"}:
            lanes[node.id] = "outputs"
        elif node.category in {"data", "ai"} or node.scope in {"regional_managed_data", "regional_managed_ai"}:
            lanes[node.id] = "managed_data"
        elif node.category in {"integration", "orchestration"}:
            lanes[node.id] = "integration_orchestration"
        elif node.category in {"security", "audit", "observability"}:
            lanes[node.id] = "controls"
        else:
            lanes[node.id] = "application"
    return lanes


def _semantic_lane_id(label: Optional[str]) -> Optional[str]:
    if not label:
        return None
    normalized = "".join(char.lower() if char.isalnum() else "_" for char in str(label)).strip("_")
    aliases = {
        "sources_and_edge": "sources_and_edge",
        "telemetry_ingestion": "telemetry_ingestion",
        "streaming_analytics": "streaming_analytics",
        "prediction_and_scoring": "prediction_and_scoring",
        "workflow_and_integrations": "workflow_and_integrations",
        "data_and_model_lifecycle": "data_and_model_lifecycle",
        "observability_and_audit": "observability_and_audit",
        "notifications": "notifications",
        "security": "security",
        "external": "external",
    }
    return aliases.get(normalized)


def _chain_wrap_lanes(spec: SemanticArchitectureSpec, chunk_size: int = 4) -> Dict[str, str]:
    if spec.metadata.get("diagram_view") == "network_private_connectivity":
        return {}
    if spec.metadata.get("diagram_view") in {"rag_ingestion_view", "rag_retrieval_view"}:
        return {}
    node_ids = {node.id for node in spec.nodes}
    if len(node_ids) < chunk_size + 1 or len(spec.flows) < len(node_ids) - 1:
        return {}
    simple_edges = [
        flow
        for flow in spec.flows
        if flow.source in node_ids and flow.target in node_ids and flow.source != flow.target
    ]
    incoming = defaultdict(int)
    outgoing = defaultdict(int)
    successors: Dict[str, List[str]] = defaultdict(list)
    for flow in simple_edges:
        outgoing[flow.source] += 1
        incoming[flow.target] += 1
        successors[flow.source].append(flow.target)
    if any(count > 1 for count in incoming.values()) or any(count > 1 for count in outgoing.values()):
        return {}
    starts = sorted(node_id for node_id in node_ids if incoming[node_id] == 0)
    if len(starts) != 1:
        return {}
    ordered = []
    current = starts[0]
    seen = set()
    while current not in seen:
        ordered.append(current)
        seen.add(current)
        next_nodes = successors.get(current, [])
        if not next_nodes:
            break
        current = sorted(next_nodes)[0]
    if len(ordered) != len(node_ids):
        return {}
    return {node_id: f"chain_stage_{index // chunk_size + 1}" for index, node_id in enumerate(ordered)}


def _lane_label(lane_id: str) -> str:
    semantic_labels = {
        "sources_and_edge": "Sources and edge",
        "telemetry_ingestion": "Telemetry ingestion",
        "streaming_analytics": "Streaming analytics",
        "prediction_and_scoring": "Prediction and scoring",
        "workflow_and_integrations": "Workflow and integrations",
        "data_and_model_lifecycle": "Data and model lifecycle",
        "observability_and_audit": "Observability and audit",
        "notifications": "Notifications",
        "security": "Security",
        "external": "External",
    }
    if lane_id in semantic_labels:
        return semantic_labels[lane_id]
    if lane_id.startswith("chain_stage_"):
        return "Request path"
    if lane_id == "vector_search":
        return "Vector Index"
    if lane_id.startswith("fanout_targets_"):
        return f"Fanout {lane_id.rsplit('_', 1)[-1]}"
    if lane_id == "parallel_dependencies":
        return "Parallel Dependencies"
    if lane_id == "private_access_paths":
        return "Private Access Paths"
    if lane_id == "data_sources":
        return "Source Documents"
    return lane_id.replace("_", " ").title()


def _lane_label_for_spec(spec: SemanticArchitectureSpec, lane_id: str) -> str:
    if not lane_id.startswith("chain_stage_"):
        return _lane_label(lane_id)
    stage = int(lane_id.rsplit("_", 1)[-1])
    edge_types = {_flow_type(flow) for flow in spec.flows}
    services = {node.service for node in spec.nodes}
    if edge_types & {"guardrail_check", "evaluation", "human_approval", "audit_trace", "model_observability"}:
        return "Governance workflow" if stage == 1 else "Evaluation and audit"
    if edge_types & {"rag_retrieval", "vector_search", "hybrid_search", "source_reference", "model_invocation"}:
        return "RAG retrieval" if stage == 1 else "Agent workflow"
    if edge_types & {"tool_invocation", "agent_orchestration", "agent_handoff"}:
        return "Agent workflow" if stage == 1 else "Tool execution"
    if edge_types & {"memory_read", "memory_write", "prompt_lookup"}:
        return "Memory access"
    if edge_types & {"private_integration"}:
        return "Request path" if stage == 1 else "Private backend"
    if services & {"api_gateway", "cloudfront", "route53"}:
        return "Request path" if stage == 1 else "Private backend"
    return "Agent workflow" if services & {"bedrock_agent", "bedrock_agentcore", "agent_runtime"} else "Request path"


def _flow_type(flow: Flow) -> str:
    return str(flow.edge_type or flow.metadata.get("edge_type") or flow.metadata.get("classification") or flow.metadata.get("edge_kind") or "request")


def _fanout_lane_labels(nodes: List[LayoutNode]) -> Dict[str, str]:
    fanout_nodes = [node for node in nodes if node.lane_id.startswith("fanout_targets_")]
    if not fanout_nodes:
        return {}
    ordered = sorted(fanout_nodes, key=lambda item: (_fanout_lane_index(item.lane_id), item.rank, _natural_key(item.id)))
    labels: Dict[str, str] = {}
    by_lane: Dict[str, List[LayoutNode]] = defaultdict(list)
    for node in ordered:
        by_lane[node.lane_id].append(node)
    position = 1
    for lane_id in sorted(by_lane, key=_fanout_lane_index):
        lane_nodes = by_lane[lane_id]
        start = position
        end = position + len(lane_nodes) - 1
        position = end + 1
        labels[lane_id] = f"{_fanout_target_label(lane_nodes)} {start}-{end}"
    return labels


def _fanout_lane_index(lane_id: str) -> int:
    try:
        return int(lane_id.rsplit("_", 1)[-1])
    except ValueError:
        return 999


def _fanout_target_label(nodes: List[LayoutNode]) -> str:
    services = {node.service for node in nodes}
    if services == {"lambda"}:
        return "Lambda targets"
    if services == {"sqs"}:
        return "SQS queues"
    if services == {"ecs"}:
        return "Worker tasks"
    if len(services) == 1:
        return f"{next(iter(services)).replace('_', ' ').title()} targets"
    return "Target batch"


def _natural_key(value: str):
    return tuple(int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(value)))


def _lane_order(spec: SemanticArchitectureSpec) -> List[str]:
    if spec.metadata.get("diagram_view") == "fanout_detail_view":
        return [
            "private_backend",
            "fulfillment_flow",
            "integration_orchestration",
            "outputs",
            "agent_orchestration",
            "application",
            "fanout_targets_1",
            "fanout_targets_2",
            "fanout_targets_3",
            "fanout_targets_4",
            "fanout_targets_5",
            "fanout_targets_6",
        ]
    template_name = spec.metadata.get("lane_template")
    if template_name:
        template_lanes = lane_ids_for_template(template_name)
        if "private_backend" in template_lanes and "parallel_dependencies" not in template_lanes:
            insertion_index = template_lanes.index("private_backend") + 1
            template_lanes = template_lanes[:insertion_index] + ["parallel_dependencies"] + template_lanes[insertion_index:]
        fallback = [lane_id for lane_id in _default_lane_order(spec) if lane_id not in template_lanes]
        return template_lanes + fallback
    return _default_lane_order(spec)


def _default_lane_order(spec: SemanticArchitectureSpec) -> List[str]:
    if spec.metadata.get("diagram_view") == "network_private_connectivity":
        return [
            "request_path",
            "private_backend",
            "private_access_paths",
            "managed_data",
            "model_invocation",
            "rag_retrieval",
            "vector_search",
            "data_sources",
            "controls",
            "integration_orchestration",
            "application",
        ]
    return [
        "edge_identity_controls",
        "request_path",
        "private_backend",
        "parallel_dependencies",
        "chain_stage_1",
        "chain_stage_2",
        "chain_stage_3",
        "chain_stage_4",
        "chain_stage_5",
        "service_dependencies",
        "agent_orchestration",
        "tool_registry",
        "tool_execution",
        "model_invocation",
        "rag_retrieval",
        "vector_search",
        "data_sources",
        "document_ingestion",
        "document_processing",
        "embedding_generation",
        "memory",
        "prompt_templates",
        "ai_governance",
        "fanout_targets_1",
        "fanout_targets_2",
        "fanout_targets_3",
        "fanout_targets_4",
        "fulfillment_flow",
        "outputs",
        "managed_data",
        "integration_orchestration",
        "controls",
        "application",
    ]


def _node_orders(spec: SemanticArchitectureSpec, lane_by_node: Dict[str, str]) -> Dict[str, Tuple[int, int, str]]:
    flow_seen: Dict[str, int] = {}
    for index, flow in enumerate(spec.flows):
        flow_seen.setdefault(flow.source, index)
        flow_seen.setdefault(flow.target, index)
    lane_index = {lane_id: index for index, lane_id in enumerate(_lane_order(spec))}
    graph_rank = _graph_ranks(spec)
    service_order = {
        "external_actor": 0,
        "external_user": 0,
        "route53": 1,
        "cloudfront": 2,
        "api_gateway": 3,
        "vpc_link": 0,
        "alb": 1,
        "nlb": 1,
        "load_balancer": 1,
        "ecs": 2,
        "eks": 2,
        "ec2": 2,
        "lambda": 0,
        "sqs": 1,
        "dynamodb": 2,
        "step_functions": 0,
        "eventbridge": 1,
        "sns": 0,
        "s3": 1,
        "waf": 0,
        "cognito": 1,
    }
    result: Dict[str, Tuple[int, int, str]] = {}
    for node in spec.nodes:
        lane = lane_by_node.get(node.id, "application")
        result[node.id] = (
            lane_index.get(lane, 99),
            graph_rank.get(node.id, service_order.get(node.service, flow_seen.get(node.id, 50))),
            node.id,
        )
    return result


def _graph_ranks(spec: SemanticArchitectureSpec) -> Dict[str, int]:
    nodes = {node.id for node in spec.nodes}
    incoming = {node_id: 0 for node_id in nodes}
    outgoing: Dict[str, List[str]] = {node_id: [] for node_id in nodes}
    for flow in spec.flows:
        if flow.source not in nodes or flow.target not in nodes:
            continue
        outgoing[flow.source].append(flow.target)
        incoming[flow.target] += 1

    queue = sorted(node_id for node_id, count in incoming.items() if count == 0)
    ranks = {node_id: 0 for node_id in queue}
    while queue:
        node_id = queue.pop(0)
        for target_id in sorted(outgoing.get(node_id, [])):
            ranks[target_id] = max(ranks.get(target_id, 0), ranks.get(node_id, 0) + 1)
            incoming[target_id] -= 1
            if incoming[target_id] == 0:
                queue.append(target_id)
                queue.sort()

    unresolved = [node_id for node_id in sorted(nodes) if node_id not in ranks]
    if unresolved:
        first_seen = {}
        for index, flow in enumerate(spec.flows):
            first_seen.setdefault(flow.source, index)
            first_seen.setdefault(flow.target, index)
        for node_id in unresolved:
            ranks[node_id] = first_seen.get(node_id, 50)
    return ranks
