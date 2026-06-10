"""Visual and layout QA gates."""

from pathlib import Path
from typing import Dict, Optional

from archway_diagram_compiler.models import Diagnostic, Flow, LayoutModel, QAReport, SemanticArchitectureSpec
from archway_diagram_compiler.qa import run_view_qa


def run_visual_layout_qa(
    view_spec: SemanticArchitectureSpec,
    artifact_paths: Dict[str, Path],
    max_aspect_ratio: float,
    max_visible_edges: int,
    min_aspect_ratio: Optional[float] = None,
    layout_model: Optional[LayoutModel] = None,
) -> QAReport:
    if layout_model is not None:
        view_spec = _view_spec_from_layout(view_spec, layout_model)
    report = run_view_qa(
        view_spec,
        artifact_paths,
        max_aspect_ratio=max_aspect_ratio,
        max_visible_edges=max_visible_edges,
        min_aspect_ratio=min_aspect_ratio,
    )
    if layout_model is not None and layout_model.view_id == "network_private_connectivity":
        diagnostics = list(report.diagnostics)
        metrics = dict(report.metrics)
        network_diagnostics = [
            diagnostic
            for diagnostic in (
                _network_source_diagnostic(layout_model),
                *_network_endpoint_target_diagnostics(layout_model),
                *_endpoint_chain_diagnostics(layout_model),
            )
            if diagnostic is not None
        ]
        if network_diagnostics:
            diagnostics.extend(network_diagnostics)
            metrics["error_count"] = int(metrics.get("error_count", 0)) + len(network_diagnostics)
            return QAReport(passed=False, diagnostics=diagnostics, metrics=metrics)
    if layout_model is not None and layout_model.view_id == "fanout_detail_view":
        order_diagnostic = _fanout_detail_order_diagnostic(layout_model)
        if order_diagnostic is not None:
            diagnostics = list(report.diagnostics)
            metrics = dict(report.metrics)
            diagnostics.append(order_diagnostic)
            metrics["error_count"] = int(metrics.get("error_count", 0)) + 1
            return QAReport(passed=False, diagnostics=diagnostics, metrics=metrics)
    return report


def _view_spec_from_layout(view_spec: SemanticArchitectureSpec, layout_model: LayoutModel) -> SemanticArchitectureSpec:
    node_ids = {node.id for node in layout_model.nodes}
    nodes_by_id = {node.id: node for node in view_spec.nodes}
    synthetic_nodes = [nodes_by_id[node_id] for node_id in node_ids if node_id in nodes_by_id]
    for layout_node in layout_model.nodes:
        if layout_node.id in nodes_by_id:
            continue
        synthetic_nodes.append(
            nodes_by_id.get(layout_node.source_node_ids[0])
            if layout_node.source_node_ids and layout_node.source_node_ids[0] in nodes_by_id
            else _synthetic_node(view_spec, layout_node)
        )
    synthetic_flows = [
        Flow(
            id=edge.id,
            source=edge.source,
            target=edge.target,
            label=edge.label,
            edge_type=edge.edge_type,
            metadata=dict(edge.metadata),
        )
        for edge in layout_model.edges
    ]
    if hasattr(view_spec, "model_copy"):
        return view_spec.model_copy(update={"nodes": synthetic_nodes, "flows": synthetic_flows})
    return view_spec.copy(update={"nodes": synthetic_nodes, "flows": synthetic_flows})


def _synthetic_node(view_spec: SemanticArchitectureSpec, layout_node):
    from archway_diagram_compiler.models import ServiceNode

    return ServiceNode(
        id=layout_node.id,
        name=layout_node.label,
        service=layout_node.service,
        provider=layout_node.provider,
        scope=layout_node.placement_scope if layout_node.placement_scope != "unknown" else None,
        annotation=layout_node.is_virtual,
        metadata=dict(layout_node.metadata),
    )


def _network_source_diagnostic(layout_model: LayoutModel):
    nodes_by_id = {node.id: node for node in layout_model.nodes}
    has_vpc_source = any(
        edge.source in nodes_by_id
        and _is_vpc_resident(nodes_by_id[edge.source].placement_scope)
        and not nodes_by_id[edge.source].is_virtual
        for edge in layout_model.edges
    )
    has_private_path = any(
        "endpoint" in edge.id
        or "vpc_link" in edge.id
        or edge.metadata.get("endpoint_access_path")
        or _edge_type(edge) == "private_integration"
        or nodes_by_id.get(edge.source) is not None
        and nodes_by_id[edge.source].service in _PRIVATE_PATH_SERVICES
        or nodes_by_id.get(edge.target) is not None
        and nodes_by_id[edge.target].service in _PRIVATE_PATH_SERVICES
        or edge.source in nodes_by_id
        and edge.target in nodes_by_id
        and _is_vpc_resident(nodes_by_id[edge.source].placement_scope)
        and _is_vpc_resident(nodes_by_id[edge.target].placement_scope)
        for edge in layout_model.edges
    )
    has_meaningful_target = any(
        edge.target in nodes_by_id
        and nodes_by_id[edge.target].service not in {"vpc_endpoint", "vpc_link"}
        and edge.source != edge.target
        for edge in layout_model.edges
    )
    if has_vpc_source and has_private_path and has_meaningful_target:
        return None
    return Diagnostic(
        severity="error",
        code="network_view_missing_private_path",
        message="network_private_connectivity must include a VPC-resident source workload, private access path, and target service.",
    )


def _edge_type(edge) -> str:
    return str(
        edge.edge_type
        if edge.edge_type and edge.edge_type != "request"
        else edge.metadata.get("classification") or edge.metadata.get("edge_type") or edge.metadata.get("edge_kind") or edge.edge_type or ""
    )


def _network_endpoint_target_diagnostics(layout_model: LayoutModel):
    nodes_by_id = {node.id: node for node in layout_model.nodes}
    diagnostics = []
    for node in layout_model.nodes:
        if node.service != "vpc_endpoint":
            continue
        has_target = _endpoint_has_direct_managed_target(node.id, nodes_by_id, layout_model.edges)
        if not has_target:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="network_endpoint_missing_target",
                    message=f"{node.label} must show at least one managed service target behind the endpoint.",
                )
            )
    return diagnostics


def _endpoint_chain_diagnostics(layout_model: LayoutModel):
    nodes_by_id = {node.id: node for node in layout_model.nodes}
    diagnostics = []
    for edge in layout_model.edges:
        source = nodes_by_id.get(edge.source)
        target = nodes_by_id.get(edge.target)
        if source is not None and target is not None and source.service == "vpc_endpoint" and target.service == "vpc_endpoint":
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="network_endpoint_false_sequence",
                    message="VPC endpoints must render as parallel access paths, not endpoint-to-endpoint chains.",
                )
            )
    return diagnostics


def _fanout_detail_order_diagnostic(layout_model: LayoutModel):
    lane_order = {lane.id: lane.order for lane in layout_model.lanes}
    for group in layout_model.parallel_groups:
        if group.group_type not in {"homogeneous_fanout", "tool_fanout"}:
            continue
        source = _node_for_id(layout_model, group.source_node_id)
        branch_nodes = [_node_for_id(layout_model, node_id) for node_id in group.branch_node_ids]
        branch_nodes = [node for node in branch_nodes if node is not None]
        if source is None or not branch_nodes:
            continue
        source_lane_order = lane_order.get(source.lane_id, 0)
        if any(lane_order.get(node.lane_id, 0) < source_lane_order for node in branch_nodes):
            return Diagnostic(
                severity="error",
                code="fanout_detail_right_to_left",
                message="Fanout detail targets must not be placed before the fanout source.",
            )
    return None


def _node_for_id(layout_model: LayoutModel, node_id: str):
    return next((node for node in layout_model.nodes if node.id == node_id), None)


def _endpoint_has_direct_managed_target(endpoint_id: str, nodes_by_id, edges) -> bool:
    return any(
        edge.source == endpoint_id
        and edge.target in nodes_by_id
        and nodes_by_id[edge.target].service not in {"vpc_endpoint", "vpc_link", "semantic_group"}
        and not nodes_by_id[edge.target].is_virtual
        for edge in edges
    )


def _is_vpc_resident(scope: str) -> bool:
    return scope in {"vpc_resident", "vpc_workload", "vpc_data"}


_PRIVATE_PATH_SERVICES = {
    "vpc_endpoint",
    "vpc_link",
    "transit_gateway",
    "direct_connect",
    "vpn",
    "privatelink_service",
    "rds_proxy",
    "nat_gateway",
}
