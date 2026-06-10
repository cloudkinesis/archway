"""High-fanout layout checks.

The grouping rewrite lives in ``layout_ir`` because it needs to edit the
LayoutModel while it is being built. This module exposes the QA-facing finder
used by tests and the compiler.
"""

from collections import defaultdict
from typing import Dict, List

from pydantic import BaseModel

from archway_diagram_compiler.models import Diagnostic, LayoutModel, LayoutNode


class FanoutFinding(BaseModel):
    node_id: str
    outgoing_edge_count: int
    threshold: int


BUSINESS_EDGE_TYPES = {
    "request",
    "data_read",
    "data_write",
    "vpc_endpoint_access",
    "async",
    "event",
    "notification",
    "secret_access",
    "observability",
    "rag_retrieval",
    "model_invocation",
}


def detect_high_fanout(layout_model: LayoutModel, threshold: int = 3) -> List[FanoutFinding]:
    nodes_by_id: Dict[str, LayoutNode] = {node.id: node for node in layout_model.nodes}
    counts: Dict[str, int] = defaultdict(int)
    for edge in layout_model.edges:
        source = nodes_by_id.get(edge.source)
        if source is None or source.is_virtual:
            continue
        if edge.metadata.get("fanout_group"):
            continue
        if source.placement_scope not in {"vpc_resident", "vpc_workload", "vpc_data", "regional_compute", "generic_application"}:
            continue
        if edge.edge_type not in BUSINESS_EDGE_TYPES or edge.criticality == "annotation":
            continue
        counts[edge.source] += 1
    return [
        FanoutFinding(node_id=node_id, outgoing_edge_count=count, threshold=threshold)
        for node_id, count in sorted(counts.items())
        if count > threshold
    ]


def high_fanout_diagnostics(layout_models: List[LayoutModel], threshold: int = 3) -> List[Diagnostic]:
    diagnostics: List[Diagnostic] = []
    for layout_model in layout_models:
        if layout_model.view_id == "fanout_detail_view":
            continue
        for finding in detect_high_fanout(layout_model, threshold=threshold):
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="high_direct_fanout",
                    message=(
                        f"{layout_model.view_id} has {finding.outgoing_edge_count} direct outgoing "
                        f"business edges from {finding.node_id}; limit is {threshold}."
                    ),
                    node_id=finding.node_id,
                )
            )
    return diagnostics
