"""Deterministic LayoutModel repair helpers.

This first repair pass keeps the contract intentionally narrow: it mutates the
LayoutModel, never the semantic graph, and records every action in metadata so
artifacts can explain what happened.
"""

from collections import defaultdict
from typing import Dict, List

from archway_diagram_compiler._compat import copy_model
from archway_diagram_compiler.models import LayoutEdge, LayoutModel, LayoutNode, QAReport


def repair_layout(layout_model: LayoutModel, qa_report: QAReport) -> LayoutModel:
    repaired = copy_model(layout_model, deep=True)
    actions: List[str] = list(repaired.metadata.get("repair_actions", []))
    codes = {diagnostic.code for diagnostic in qa_report.diagnostics}

    if "too_many_incoming_edges" in codes:
        repaired = _group_shared_incoming_edges(repaired)
        actions.append("group_shared_incoming_edges")
    if "too_many_visible_edges" in codes:
        repaired = _collapse_secondary_edges(repaired)
        actions.append("collapse_secondary_edges")
    if "edge_label_overlap" in codes:
        repaired = _reduce_edge_label_density(repaired)
        actions.append("reduce_edge_label_density")
    if "diagram_aspect_ratio_too_wide" in codes or "diagram_aspect_ratio_too_narrow" in codes:
        repaired = _increase_lane_spacing(repaired)
        actions.append("increase_lane_spacing")
    if "node_overlap" in codes:
        repaired = _increase_lane_spacing(repaired)
        actions.append("increase_lane_spacing")
    if "too_many_edge_crossings" in codes:
        repaired = _increase_lane_spacing(repaired)
        repaired = _reduce_edge_label_density(repaired)
        actions.append("reduce_edge_crossing_density")
    if "diagonal_connector_segments" in codes or "edge_crosses_node" in codes or "too_many_edge_crossings" in codes:
        repaired = _force_orthogonal_edges(repaired)
        actions.append("reroute_edge_orthogonally")

    repaired.metadata["repair_actions"] = sorted(set(actions))
    return repaired


def _hide_secondary_edge_labels(layout_model: LayoutModel) -> LayoutModel:
    edges = [
        copy_model(edge, deep=True, update={"label": None})
        if edge.criticality != "primary"
        else copy_model(edge, deep=True)
        for edge in layout_model.edges
    ]
    return copy_model(layout_model, deep=True, update={"edges": edges})


def _reduce_edge_label_density(layout_model: LayoutModel) -> LayoutModel:
    metadata = dict(layout_model.metadata)
    attempt = int(metadata.get("label_repair_attempt", 0)) + 1
    metadata["label_repair_attempt"] = attempt
    edges = []
    for edge in layout_model.edges:
        hide = edge.criticality != "primary"
        if attempt == 1:
            hide = hide or edge.style != "solid" or bool(edge.label and len(edge.label) > 14)
        else:
            hide = True
        edges.append(copy_model(edge, deep=True, update={"label": None}) if hide else copy_model(edge, deep=True))
    return copy_model(layout_model, deep=True, update={"edges": edges, "metadata": metadata})


def _collapse_secondary_edges(layout_model: LayoutModel) -> LayoutModel:
    visible_edges = list(layout_model.edges)
    if len(visible_edges) <= 24:
        return layout_model
    secondary = [edge for edge in visible_edges if edge.criticality != "primary" or edge.style != "solid"]
    if not secondary:
        return layout_model
    collapsed_ids = {edge.id for edge in secondary}
    kept_edges = [edge for edge in visible_edges if edge.id not in collapsed_ids]
    nodes_by_id = {node.id: node for node in layout_model.nodes}
    first = secondary[0]
    source = nodes_by_id.get(first.source) or layout_model.nodes[0]
    target = nodes_by_id.get(first.target) or source
    group_id = "collapsed_secondary_relationships"
    nodes = list(layout_model.nodes)
    if group_id not in nodes_by_id:
        nodes.append(
            LayoutNode(
                id=group_id,
                source_node_ids=[],
                label="Secondary relationships",
                subtitle=None,
                service="semantic_group",
                provider=source.provider,
                icon=None,
                lane_id=target.lane_id,
                rank=target.rank,
                order=target.order,
                placement_scope=target.placement_scope,
                role="collapsed_relationships",
                is_virtual=True,
                metadata={"collapsed_edge_count": len(secondary)},
            )
        )
    kept_edges.append(
        LayoutEdge(
            id="collapsed_secondary_relationships_edge",
            source=source.id,
            target=group_id,
            source_flow_ids=[flow_id for edge in secondary for flow_id in edge.source_flow_ids],
            label="secondary relationships",
            edge_type="control",
            style="dashed",
            route_preference="orthogonal",
            criticality="secondary",
            metadata={"collapsed_edge_ids": sorted(collapsed_ids)},
        )
    )
    return copy_model(layout_model, deep=True, update={"nodes": nodes, "edges": kept_edges})


def _group_shared_incoming_edges(layout_model: LayoutModel, threshold: int = 5) -> LayoutModel:
    nodes_by_id: Dict[str, LayoutNode] = {node.id: node for node in layout_model.nodes}
    incoming: Dict[str, List[LayoutEdge]] = defaultdict(list)
    for edge in layout_model.edges:
        target = nodes_by_id.get(edge.target)
        source = nodes_by_id.get(edge.source)
        if target is None or target.is_virtual:
            continue
        if layout_model.view_id == "network_private_connectivity" and source is not None and source.service == "vpc_endpoint":
            continue
        incoming[edge.target].append(edge)

    nodes = list(layout_model.nodes)
    edges = list(layout_model.edges)
    for target_id, target_edges in sorted(incoming.items()):
        if len(target_edges) <= threshold:
            continue
        target = nodes_by_id[target_id]
        group_id = f"{target_id}_repair_shared_access"
        if group_id not in nodes_by_id:
            group = LayoutNode(
                id=group_id,
                source_node_ids=[],
                label="Shared dependency",
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
                metadata={"repair_group": "too_many_incoming_edges", "target_node_id": target_id},
            )
            nodes_by_id[group_id] = group
            nodes.append(group)
        edge_ids = {edge.id for edge in target_edges}
        edges = [edge for edge in edges if edge.id not in edge_ids]
        for edge in target_edges:
            edges.append(
                copy_model(
                    edge,
                    deep=True,
                    update={
                        "target": group_id,
                        "id": f"{edge.id}_to_repair_shared_group",
                        "metadata": {**edge.metadata, "repair_group": "too_many_incoming_edges"},
                    },
                )
            )
        edges.append(
            LayoutEdge(
                id=f"{group_id}_to_{target_id}",
                source=group_id,
                target=target_id,
                source_flow_ids=[flow_id for edge in target_edges for flow_id in edge.source_flow_ids],
                label="shared access",
                edge_type=target_edges[0].edge_type,
                style="solid",
                route_preference="orthogonal",
                criticality="primary",
                metadata={"repair_group": "too_many_incoming_edges"},
            )
        )
    return copy_model(layout_model, deep=True, update={"nodes": nodes, "edges": edges})


def _increase_lane_spacing(layout_model: LayoutModel) -> LayoutModel:
    metadata = dict(layout_model.metadata)
    metadata["spacing"] = "expanded"
    metadata["spacing_attempt"] = int(metadata.get("spacing_attempt", 0)) + 1
    return copy_model(layout_model, deep=True, update={"metadata": metadata})


def _force_orthogonal_edges(layout_model: LayoutModel) -> LayoutModel:
    edges = [
        copy_model(edge, deep=True, update={"route_preference": "orthogonal"})
        for edge in layout_model.edges
    ]
    return copy_model(layout_model, deep=True, update={"edges": edges})
