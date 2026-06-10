"""Shared helpers for semantic view construction."""

import re
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from archway_diagram_compiler._compat import copy_model
from archway_diagram_compiler.models import Flow, SemanticArchitectureSpec, ServiceNode


def ordered_unique_target_ids(flows: Sequence[Flow]) -> List[str]:
    return sorted({flow.target for flow in flows}, key=natural_key)


def target_position(target_id: str, ordered_target_ids: Sequence[str]) -> int:
    try:
        return list(ordered_target_ids).index(target_id)
    except ValueError:
        return 1_000_000


def natural_key(value: str):
    return tuple(int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(value)))


def append_visible_flow(
    visible: List[Flow],
    seen_edges: Set[Tuple[str, str, str]],
    flow: Flow,
) -> None:
    edge_key = (flow.source, flow.target, flow.metadata.get("edge_kind", flow.edge_type or "request"))
    if edge_key in seen_edges:
        visible[:] = [
            existing
            for existing in visible
            if (existing.source, existing.target, existing.metadata.get("edge_kind", existing.edge_type or "request")) != edge_key
        ]
    seen_edges.add(edge_key)
    visible.append(flow)


def copy_view(
    spec: SemanticArchitectureSpec,
    view_name: str,
    title: str,
    nodes: Sequence[ServiceNode],
    flows: Sequence[Flow],
    direction: str,
) -> SemanticArchitectureSpec:
    return copy_model(
        spec,
        deep=True,
        update={
            "title": title,
            "nodes": [copy_model(node, deep=True) for node in nodes],
            "flows": [copy_model(flow, deep=True) for flow in flows],
            "metadata": {**spec.metadata, "diagram_view": view_name, "direction": direction},
        },
    )


def ordered_node_ids(spec: SemanticArchitectureSpec, allowed_ids: Iterable[str]) -> List[str]:
    allowed = set(allowed_ids)
    first_seen: Dict[str, int] = {}
    for index, flow in enumerate(spec.flows):
        first_seen.setdefault(flow.source, index)
        first_seen.setdefault(flow.target, index)
    return sorted(allowed, key=lambda node_id: (first_seen.get(node_id, 10_000), node_id))


def node_ids_from_flows(flows: Iterable[Flow]) -> Set[str]:
    node_ids: Set[str] = set()
    for flow in flows:
        node_ids.add(flow.source)
        node_ids.add(flow.target)
    return node_ids


def base_title(title: str) -> str:
    return title.replace(" - Production logical service flow", "")


def is_vpc_resident(scope: Optional[str]) -> bool:
    return scope in {"vpc_workload", "vpc_data", "vpc_resident"}


def safe_identifier(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower())
    return cleaned.strip("_") or "targets"
