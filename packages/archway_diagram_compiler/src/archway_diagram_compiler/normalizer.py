"""Deterministic graph normalization rules."""

from collections import defaultdict
from typing import Dict, List, Set, Tuple

from archway_diagram_compiler._compat import copy_model
from archway_diagram_compiler.catalog import classify_node, is_vpc_scope
from archway_diagram_compiler.providers import get_provider_catalog
from archway_diagram_compiler.models import Diagnostic, Flow, SemanticArchitectureSpec, ServiceNode


def normalize_spec(spec: SemanticArchitectureSpec) -> Tuple[SemanticArchitectureSpec, List[Diagnostic]]:
    diagnostics: List[Diagnostic] = []
    normalized_nodes: List[ServiceNode] = []

    for node in spec.nodes:
        node = copy_model(node, deep=True)
        if node.annotation:
            normalized_nodes.append(node)
            continue

        try:
            provider_catalog = get_provider_catalog(node.provider)
        except KeyError:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="unsupported_provider",
                    message=f"Provider is not supported: {node.provider}.",
                    node_id=node.id,
                )
            )
            normalized_nodes.append(node)
            continue

        canonical_service = provider_catalog.canonicalize_service(node.service)
        is_catalog_fallback = bool(
            node.provider == "aws"
            and hasattr(provider_catalog, "is_fallback_service")
            and provider_catalog.is_fallback_service(canonical_service)
        )
        catalog_scope = classify_node(copy_model(node, update={"service": canonical_service}))
        if catalog_scope is None:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="unknown_service",
                    message="Service is not present in the AWS placement catalog.",
                    node_id=node.id,
                )
            )
            normalized_nodes.append(node)
            continue
        if is_catalog_fallback:
            fallback_info = provider_catalog.get_service_info(canonical_service)
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="aws_service_catalog_fallback",
                    message=(
                        f"{canonical_service} is not explicitly modeled in the AWS catalog; "
                        f"using inferred {catalog_scope} placement and {fallback_info.category} category."
                    ),
                    node_id=node.id,
                )
            )

        if node.scope is not None and node.scope != catalog_scope:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="invalid_scope",
                    message=f"{node.service} must be placed as {catalog_scope}, not {node.scope}.",
                    node_id=node.id,
                )
            )
        node.service = canonical_service
        node.scope = catalog_scope
        node.category = node.category or provider_catalog.get_default_category(canonical_service)

        if not is_vpc_scope(catalog_scope) and (node.vpc_id or node.subnet_id or node.az):
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="moved_outside_vpc",
                    message=f"{node.service} is a {catalog_scope} service and was moved outside VPC boundaries.",
                    node_id=node.id,
                )
            )
            node.vpc_id = None
            node.subnet_id = None
            node.az = None

        normalized_nodes.append(node)

    normalized_nodes, flows, endpoint_diags = _collapse_vpc_endpoints(normalized_nodes, spec.flows)
    diagnostics.extend(endpoint_diags)

    normalized_nodes, flows, replica_diags = _collapse_az_replicas(normalized_nodes, flows)
    diagnostics.extend(replica_diags)

    diagnostics.extend(_find_orphans(normalized_nodes, flows))

    normalized = copy_model(
        spec,
        deep=True,
        update={
            "nodes": sorted(normalized_nodes, key=lambda item: item.id),
            "flows": sorted(flows, key=lambda item: item.id),
        },
    )
    return normalized, diagnostics


def _collapse_vpc_endpoints(
    nodes: List[ServiceNode], flows: List[Flow]
) -> Tuple[List[ServiceNode], List[Flow], List[Diagnostic]]:
    diagnostics: List[Diagnostic] = []
    node_by_id = {node.id: node for node in nodes}
    endpoint_nodes = {
        node.id: node
        for node in nodes
        if node.service.strip().lower().replace("-", "_").replace(" ", "_") == "vpc_endpoint"
    }
    if not endpoint_nodes:
        return nodes, list(flows), diagnostics

    replacements: Dict[str, str] = {}
    for endpoint_id, endpoint in endpoint_nodes.items():
        target_id = endpoint.metadata.get("target_node_id")
        target_service = endpoint.metadata.get("target_service")
        if not target_id and target_service:
            matches = [
                node.id
                for node in nodes
                if node.id != endpoint_id and node.service.lower() == str(target_service).lower()
            ]
            target_id = sorted(matches)[0] if matches else None
        if target_id and target_id in node_by_id:
            replacements[endpoint_id] = str(target_id)
            diagnostics.append(
                Diagnostic(
                    severity="info",
                    code="endpoint_access_path",
                    message="VPC endpoint was represented as an endpoint access path.",
                    node_id=endpoint_id,
                )
            )
        else:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="unresolved_endpoint_target",
                    message="VPC endpoint must reference an existing target service node.",
                    node_id=endpoint_id,
                )
            )

    rewritten: List[Flow] = []
    seen: Set[Tuple[str, str, str, str]] = set()
    for flow in flows:
        source = replacements.get(flow.source, flow.source)
        target = replacements.get(flow.target, flow.target)
        if source == target and (flow.source != flow.target):
            continue
        metadata = dict(flow.metadata)
        if flow.source in replacements or flow.target in replacements:
            metadata["endpoint_access_path"] = True
        rewritten_flow = copy_model(flow, update={"source": source, "target": target, "metadata": metadata})
        key = (
            rewritten_flow.source,
            rewritten_flow.target,
            rewritten_flow.label or "",
            rewritten_flow.protocol or "",
        )
        if key not in seen:
            seen.add(key)
            rewritten.append(rewritten_flow)

    remaining_nodes = [node for node in nodes if node.id not in replacements]
    return remaining_nodes, rewritten, diagnostics


def _collapse_az_replicas(
    nodes: List[ServiceNode], flows: List[Flow]
) -> Tuple[List[ServiceNode], List[Flow], List[Diagnostic]]:
    groups: Dict[Tuple[str, str, str, str], List[ServiceNode]] = defaultdict(list)
    for node in nodes:
        if node.annotation or node.active_active:
            continue
        group = node.logical_group or node.name
        key = (group, node.service.lower(), node.scope or "", node.vpc_id or "")
        groups[key].append(node)

    replacement: Dict[str, str] = {}
    diagnostics: List[Diagnostic] = []
    collapsed_ids: Set[str] = set()
    next_nodes: List[ServiceNode] = []
    replica_sets = {key: value for key, value in groups.items() if len({node.az for node in value}) > 1}

    for node in sorted(nodes, key=lambda item: item.id):
        key = (node.logical_group or node.name, node.service.lower(), node.scope or "", node.vpc_id or "")
        replicas = replica_sets.get(key)
        if not replicas:
            next_nodes.append(node)
            continue
        canonical = sorted(replicas, key=lambda item: item.id)[0]
        if node.id != canonical.id:
            replacement[node.id] = canonical.id
            collapsed_ids.add(node.id)
            continue
        azs = sorted({replica.az for replica in replicas if replica.az})
        metadata = dict(canonical.metadata)
        metadata["collapsed_az_replicas"] = [replica.id for replica in sorted(replicas, key=lambda item: item.id)]
        next_nodes.append(
            copy_model(
                canonical,
                update={
                    "name": canonical.logical_group or canonical.name,
                    "az": None,
                    "metadata": metadata,
                }
            )
        )
        diagnostics.append(
            Diagnostic(
                severity="info",
                code="collapsed_az_replicas",
                message=f"Collapsed duplicate AZ replicas into one logical workload group across {', '.join(azs)}.",
                node_id=canonical.id,
            )
        )

    rewritten_flows: List[Flow] = []
    seen: Set[Tuple[str, str, str, str]] = set()
    for flow in flows:
        source = replacement.get(flow.source, flow.source)
        target = replacement.get(flow.target, flow.target)
        if source == target and (flow.source != flow.target):
            continue
        rewritten_flow = copy_model(flow, update={"source": source, "target": target})
        key = (
            rewritten_flow.source,
            rewritten_flow.target,
            rewritten_flow.label or "",
            rewritten_flow.protocol or "",
        )
        if key not in seen:
            seen.add(key)
            rewritten_flows.append(rewritten_flow)

    return [node for node in next_nodes if node.id not in collapsed_ids], rewritten_flows, diagnostics


def _find_orphans(nodes: List[ServiceNode], flows: List[Flow]) -> List[Diagnostic]:
    connected = set()
    node_ids = {node.id for node in nodes}
    diagnostics: List[Diagnostic] = []
    for flow in flows:
        if flow.source not in node_ids:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="missing_flow_source",
                    message="Flow source does not reference a known node.",
                    flow_id=flow.id,
                )
            )
        if flow.target not in node_ids:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="missing_flow_target",
                    message="Flow target does not reference a known node.",
                    flow_id=flow.id,
                )
            )
        connected.add(flow.source)
        connected.add(flow.target)

    for node in nodes:
        if not node.annotation and node.id not in connected:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="orphan_node",
                    message="Node has no incoming or outgoing flows; rendering as an isolated component.",
                    node_id=node.id,
                )
            )
    return diagnostics
