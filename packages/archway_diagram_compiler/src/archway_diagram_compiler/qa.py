"""QA checks for normalized graph and rendered artifacts."""

from pathlib import Path
from html import unescape
import re
from typing import Dict, Iterable, List, Optional, Tuple

from archway_diagram_compiler.models import Diagnostic, QAReport, SemanticArchitectureSpec
from archway_diagram_compiler.quality_config import DEFAULT_QUALITY_CONFIG


def run_graph_qa(spec: SemanticArchitectureSpec, diagnostics: Iterable[Diagnostic]) -> QAReport:
    all_diagnostics = list(diagnostics)
    node_ids = {node.id for node in spec.nodes}
    duplicate_node_ids = len(node_ids) != len(spec.nodes)
    if duplicate_node_ids:
        all_diagnostics.append(
            Diagnostic(
                severity="error",
                code="duplicate_node_id",
                message="Semantic spec contains duplicate node ids.",
            )
        )

    for flow in spec.flows:
        if flow.source not in node_ids:
            all_diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="qa_missing_flow_source",
                    message="Flow source is missing from normalized graph.",
                    flow_id=flow.id,
                )
            )
        if flow.target not in node_ids:
            all_diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="qa_missing_flow_target",
                    message="Flow target is missing from normalized graph.",
                    flow_id=flow.id,
                )
            )

    all_diagnostics.extend(_architecture_advisories(spec))
    metrics = {
        "node_count": len(spec.nodes),
        "flow_count": len(spec.flows),
        "error_count": sum(1 for item in all_diagnostics if item.severity == "error"),
        "warning_count": sum(1 for item in all_diagnostics if item.severity == "warning"),
    }
    return QAReport(
        passed=metrics["error_count"] == 0,
        diagnostics=all_diagnostics,
        metrics=metrics,
    )


def run_view_qa(
    spec: SemanticArchitectureSpec,
    artifact_paths: Dict[str, Path],
    max_aspect_ratio: float,
    max_visible_edges: int,
    min_aspect_ratio: Optional[float] = None,
) -> QAReport:
    diagnostics: List[Diagnostic] = []
    if not spec.nodes:
        return QAReport(
            passed=True,
            diagnostics=[],
            metrics={
                "visible_edge_count": 0,
                "cross_region_edge_count": 0,
                "suspicious_cross_region_edge_count": 0,
                "max_incoming_edges": 0,
                "aspect_ratio": None,
                "diagonal_connector_count": None,
                "node_overlap_count": None,
                "edge_label_overlap_count": None,
                "edge_crosses_node_count": None,
                "edge_crossing_count": None,
                "node_label_icon_overlap_count": None,
                "error_count": 0,
                "warning_count": 0,
            },
        )
    visible_edges = len(spec.flows)
    incoming_counts: Dict[str, int] = {}
    nodes_by_id = {node.id: node for node in spec.nodes}
    regions = {node.id: _region_key(node) for node in spec.nodes}
    cross_region_edges = 0
    suspicious_cross_region_edges = 0

    for flow in spec.flows:
        source_node = nodes_by_id.get(flow.source)
        if (
            (not nodes_by_id.get(flow.target) or not nodes_by_id[flow.target].annotation)
            and (source_node is None or source_node.service != "vpc_endpoint")
        ):
            incoming_counts[flow.target] = incoming_counts.get(flow.target, 0) + 1
        if _regions_differ(regions.get(flow.source), regions.get(flow.target)):
            cross_region_edges += 1
            if _is_suspicious_cross_region_flow(flow, nodes_by_id):
                suspicious_cross_region_edges += 1

    max_incoming = max(incoming_counts.values()) if incoming_counts else 0
    if visible_edges > max_visible_edges:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="too_many_visible_edges",
                message=f"{spec.metadata.get('diagram_view')} has {visible_edges} visible edges; limit is {max_visible_edges}.",
            )
        )
    if suspicious_cross_region_edges > 3:
        diagnostics.append(
            Diagnostic(
                severity="warning",
                code="too_many_cross_region_edges",
                message=(
                    f"{spec.metadata.get('diagram_view')} has {suspicious_cross_region_edges} non-ingress "
                    "region-boundary edges; limit is 3."
                ),
            )
        )
    if max_incoming > 5:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="too_many_incoming_edges",
                message=f"{spec.metadata.get('diagram_view')} has a node with {max_incoming} incoming edges; limit is 5.",
            )
        )

    aspect_ratio = _svg_aspect_ratio(artifact_paths.get("svg"))
    if aspect_ratio is not None and aspect_ratio > max_aspect_ratio:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="diagram_aspect_ratio_too_wide",
                message=(
                    f"{spec.metadata.get('diagram_view')} aspect ratio is {aspect_ratio:.2f}; "
                    f"limit is {max_aspect_ratio:.2f}."
                ),
            )
        )
    if spec.metadata.get("diagram_view") == "production_logical_service_flow":
        diagnostics.extend(_logical_service_flow_qa(spec))
    if min_aspect_ratio is not None and aspect_ratio is not None and aspect_ratio < min_aspect_ratio:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="diagram_aspect_ratio_too_narrow",
                message=(
                    f"{spec.metadata.get('diagram_view')} aspect ratio is {aspect_ratio:.2f}; "
                    f"minimum is {min_aspect_ratio:.2f}."
                ),
            )
        )
    diagonal_edge_count = _svg_diagonal_connection_count(artifact_paths.get("svg"))
    if (
        spec.metadata.get("diagram_view") == "production_logical_service_flow"
        and diagonal_edge_count is not None
        and diagonal_edge_count > 0
    ):
        diagnostics.append(
            Diagnostic(
                severity="warning",
                code="diagonal_connector_segments",
                message=f"Logical service flow has {diagonal_edge_count} diagonal connector segment(s); connectors must be orthogonal.",
            )
        )
    node_overlap_count = _svg_node_overlap_count(artifact_paths.get("svg"))
    if node_overlap_count is not None and node_overlap_count > 0:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="node_overlap",
                message=f"{spec.metadata.get('diagram_view')} has {node_overlap_count} overlapping node card pair(s).",
            )
        )
    edge_label_overlap_count = _svg_edge_label_overlap_count(artifact_paths.get("svg"))
    if edge_label_overlap_count is not None and edge_label_overlap_count > 0:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="edge_label_overlap",
                message=f"{spec.metadata.get('diagram_view')} has {edge_label_overlap_count} edge label overlap(s).",
            )
        )
    edge_crosses_node_count = _svg_edge_crosses_node_count(artifact_paths.get("svg"))
    if edge_crosses_node_count is not None and edge_crosses_node_count > 0:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="edge_crosses_node",
                message=f"{spec.metadata.get('diagram_view')} has {edge_crosses_node_count} connector segment(s) crossing node cards.",
            )
        )
    edge_crossing_count = _svg_edge_crossing_count(artifact_paths.get("svg"))
    diagram_view = spec.metadata.get("diagram_view")
    max_edge_crossings = DEFAULT_QUALITY_CONFIG.max_edge_crossings_for_view(
        diagram_view,
        target_count=_fanout_detail_target_count(spec) if diagram_view == "fanout_detail_view" else 0,
    )
    if edge_crossing_count is not None and edge_crossing_count > max_edge_crossings:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="too_many_edge_crossings",
                message=(
                    f"{spec.metadata.get('diagram_view')} has {edge_crossing_count} visible edge crossing(s); "
                    f"limit is {max_edge_crossings}."
                ),
            )
        )
    node_label_icon_overlap_count = _svg_node_label_icon_overlap_count(artifact_paths.get("svg"))
    if node_label_icon_overlap_count is not None and node_label_icon_overlap_count > 0:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="node_label_icon_overlap",
                message=(
                    f"{spec.metadata.get('diagram_view')} has {node_label_icon_overlap_count} "
                    "node label/icon overlap(s)."
                ),
            )
        )

    metrics = {
        "visible_edge_count": visible_edges,
        "cross_region_edge_count": cross_region_edges,
        "suspicious_cross_region_edge_count": suspicious_cross_region_edges,
        "max_incoming_edges": max_incoming,
        "aspect_ratio": aspect_ratio,
        "diagonal_connector_count": diagonal_edge_count,
        "node_overlap_count": node_overlap_count,
        "edge_label_overlap_count": edge_label_overlap_count,
        "edge_crosses_node_count": edge_crosses_node_count,
        "edge_crossing_count": edge_crossing_count,
        "node_label_icon_overlap_count": node_label_icon_overlap_count,
        "error_count": sum(1 for item in diagnostics if item.severity == "error"),
        "warning_count": sum(1 for item in diagnostics if item.severity == "warning"),
    }
    return QAReport(passed=metrics["error_count"] == 0, diagnostics=diagnostics, metrics=metrics)


def _fanout_detail_target_count(spec: SemanticArchitectureSpec) -> int:
    node_ids = {node.id for node in spec.nodes if node.metadata.get("fanout_group")}
    if node_ids:
        return len({flow.target for flow in spec.flows if flow.source in node_ids and flow.target != flow.source})
    return max(0, len([node for node in spec.nodes if not node.annotation]) - 1)


def _architecture_advisories(spec: SemanticArchitectureSpec) -> List[Diagnostic]:
    diagnostics: List[Diagnostic] = []
    nodes_by_id = {node.id: node for node in spec.nodes}
    flows_by_target: Dict[str, List] = {}
    flows_by_source: Dict[str, List] = {}
    for flow in spec.flows:
        flows_by_target.setdefault(flow.target, []).append(flow)
        flows_by_source.setdefault(flow.source, []).append(flow)

    auth_services = {"cognito", "iam"}
    auth_edges = {"auth", "secret_access"}
    for node in spec.nodes:
        if node.service not in {"api_gateway", "appsync"}:
            continue
        has_public_incoming = any(
            (
                nodes_by_id.get(flow.source)
                and nodes_by_id[flow.source].service in {"external_actor", "external_user", "route53", "cloudfront"}
                and nodes_by_id[flow.source].service not in {"waf", "shield"}
            )
            for flow in flows_by_target.get(node.id, [])
        )
        has_auth = any(
            (nodes_by_id.get(flow.source) and nodes_by_id[flow.source].service in auth_services)
            or (flow.edge_type in auth_edges)
            or ("auth" in str(flow.label or "").lower())
            for flow in spec.flows
            if flow.source == node.id or flow.target == node.id
        )
        intentionally_public = node.metadata.get("auth_mode") == "public_demo" or node.metadata.get("intentionally_public") is True
        if has_public_incoming and not has_auth and node.metadata.get("auth") not in {"cognito_jwt", "iam", "jwt"}:
            diagnostics.append(
                Diagnostic(
                    severity="info" if intentionally_public else "warning",
                    code="architecture_advisory_public_entry_without_auth",
                    message=(
                        f"{node.name} is intentionally public for a demo/test architecture."
                        if intentionally_public
                        else f"{node.name} is public-facing but has no visible auth provider or authorizer."
                    ),
                    node_id=node.id,
                )
            )

    datastore_services = {
        "rds",
        "dynamodb",
        "s3",
        "opensearch_serverless",
        "opensearch_vector_index",
        "opensearch_hybrid_search",
        "opensearch_domain",
        "generic_vector_store",
        "redshift",
        "elasticache",
    }
    for node in spec.nodes:
        if node.service not in datastore_services or node.annotation:
            continue
        datastore_role = _datastore_role(node, flows_by_target.get(node.id, []))
        if datastore_role in {"read_only_source", "audit_sink", "registry", "artifact_store", "pre_existing"}:
            continue
        incoming = flows_by_target.get(node.id, [])
        has_writer = any(
            (
                flow.edge_type in {"data_write", "memory_write", "document_ingestion", "document_embedding", "embedding_generation", "audit_trace", "observability", "model_observability"}
                or any(token in str(flow.label or "").lower() for token in ("write", "store", "put", "load", "index", "archive", "audit", "trace", "log", "reserve", "update", "save", "create"))
            )
            for flow in incoming
        )
        if incoming and not has_writer:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="architecture_advisory_datastore_without_writer",
                    message=f"{node.name} has incoming access but no explicit write/store flow.",
                    node_id=node.id,
                )
            )
        if node.service in {"rds", "elasticache"} and node.metadata.get("public_access") is True:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="architecture_advisory_public_stateful_service",
                    message=f"{node.name} is marked public; stateful services should normally stay private.",
                    node_id=node.id,
                )
            )
    return diagnostics


def _datastore_role(node, incoming_flows: List) -> str:
    explicit = node.metadata.get("datastore_role") or node.metadata.get("data_store_role") or node.metadata.get("data_role")
    if explicit:
        return str(explicit)
    if node.metadata.get("pre_existing") is True or node.metadata.get("external") is True:
        return "pre_existing"
    role_text = " ".join(
        str(value)
        for value in (
            node.metadata.get("role"),
            node.metadata.get("data_type"),
            node.category,
            node.name,
        )
        if value
    ).lower()
    if any(token in role_text for token in ("source_document", "source documents", "document source", "read_only", "read-only", "knowledge source")):
        return "read_only_source"
    if any(token in role_text for token in ("audit", "log archive", "transcript archive")):
        return "audit_sink"
    if any(token in role_text for token in ("registry", "catalog", "tool registry", "prompt_template")):
        return "registry"
    if any(token in role_text for token in ("artifact", "model artifacts")):
        return "artifact_store"
    if any((flow.edge_type in {"audit_trace", "observability", "model_observability"} or any(token in str(flow.label or "").lower() for token in ("audit", "trace", "log", "archive"))) for flow in incoming_flows):
        return "audit_sink"
    if any((flow.edge_type in {"rag_retrieval", "source_reference", "data_read", "hybrid_search", "vector_search"} or any(token in str(flow.label or "").lower() for token in ("read", "lookup", "search", "retrieve", "reference"))) for flow in incoming_flows):
        return "read_only_source"
    return "write_target"


def _is_suspicious_cross_region_flow(flow, nodes_by_id: Dict) -> bool:
    source = nodes_by_id.get(flow.source)
    target = nodes_by_id.get(flow.target)
    if source is None or target is None:
        return False
    expected_edge_services = {"external_actor", "external_user", "route53", "cloudfront", "waf", "shield"}
    expected_entry_services = {"cloudfront", "api_gateway", "appsync", "cognito"}
    if source.service in expected_edge_services and target.service in expected_entry_services:
        return False
    if flow.edge_type in {"auth", "control", "audit", "observability"}:
        return False
    if source.region == "global" or target.region == "global":
        return False
    return True


def _region_key(node) -> str:
    if node.region:
        return node.region
    if node.scope in {"global_edge", "global_edge_control", "external_actor"}:
        return "global"
    return "regional_unspecified"


def _regions_differ(source_region: Optional[str], target_region: Optional[str]) -> bool:
    if not source_region or not target_region or source_region == target_region:
        return False
    if "regional_unspecified" in {source_region, target_region}:
        return False
    return True


def _logical_service_flow_qa(spec: SemanticArchitectureSpec) -> List[Diagnostic]:
    diagnostics: List[Diagnostic] = []
    node_ids = {node.id for node in spec.nodes}
    nodes_by_id = {node.id: node for node in spec.nodes}
    control_node_ids = {"waf", "cognito"}
    degree_counts = {node.id: 0 for node in spec.nodes}

    for flow in spec.flows:
        if flow.source in degree_counts:
            degree_counts[flow.source] += 1
        if flow.target in degree_counts:
            degree_counts[flow.target] += 1
        if (
            (flow.source in control_node_ids or flow.target in control_node_ids)
            and flow.metadata.get("edge_kind") != "control"
        ):
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="control_rendered_as_request_path",
                    message="WAF and identity providers must be rendered as side controls, not request-path nodes.",
                    flow_id=flow.id,
                )
            )
    control_services = {"waf", "cognito", "shield", "cloudtrail", "cloudwatch", "kms", "secrets_manager"}
    for node_id, degree in degree_counts.items():
        node = nodes_by_id[node_id]
        if degree > 0 or node.annotation or node.service in control_services:
            continue
        diagnostics.append(
            Diagnostic(
                severity="warning",
                code="logical_orphan_node",
                message="Logical service flow contains an isolated non-control node.",
                node_id=node_id,
            )
        )

    return diagnostics


def _svg_aspect_ratio(path: Optional[Path]) -> Optional[float]:
    if path is None or not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")[:1000]
    viewbox = re.search(r'viewBox="([^"]+)"', text)
    if viewbox:
        values = [float(part) for part in viewbox.group(1).replace(",", " ").split()]
        if len(values) == 4:
            width = values[2]
            height = values[3]
            return width / height if height else None
    width_match = re.search(r'width="([\d.]+)"', text)
    height_match = re.search(r'height="([\d.]+)"', text)
    if width_match and height_match:
        height = float(height_match.group(1))
        return float(width_match.group(1)) / height if height else None
    return None


def _svg_diagonal_connection_count(path: Optional[Path], threshold: float = 1.0) -> Optional[int]:
    if path is None or not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    count = 0
    for path_match in re.finditer(r'<path d="([^"]+)"[^>]*class="connection"[^>]*>', text):
        points = [
            (float(x), float(y))
            for x, y in re.findall(r"[ML]\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)", path_match.group(1))
        ]
        if len(points) < 2:
            continue
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            if abs(x2 - x1) > threshold and abs(y2 - y1) > threshold:
                count += 1
    return count


def _svg_node_overlap_count(path: Optional[Path], tolerance: float = 0.5) -> Optional[int]:
    if path is None or not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    rects = _svg_node_rects(text)
    overlaps = 0
    for index, first in enumerate(rects):
        for second in rects[index + 1:]:
            if _rects_overlap(first, second, tolerance):
                overlaps += 1
    return overlaps


def _svg_edge_label_overlap_count(path: Optional[Path], padding: float = 1.0) -> Optional[int]:
    if path is None or not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    labels = _svg_edge_label_rects(text, padding=padding)
    nodes = _svg_node_rects(text)
    overlaps = 0
    for label in labels:
        if any(_rects_overlap(label, node, tolerance=0) for node in nodes):
            overlaps += 1
    for index, first in enumerate(labels):
        for second in labels[index + 1:]:
            if _rects_overlap(first, second, tolerance=0):
                overlaps += 1
    return overlaps


def _svg_edge_crosses_node_count(path: Optional[Path], node_inset: float = 8.0) -> Optional[int]:
    if path is None or not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    rects = [_inset_rect(rect, node_inset) for rect in _svg_node_rects(text)]
    rects = [rect for rect in rects if rect[0] < rect[2] and rect[1] < rect[3]]
    crossings = 0
    masked = _svg_uses_global_card_mask(text)
    for points in _svg_connection_points(text):
        for start, end in zip(points, points[1:]):
            if _segment_length(start, end) < 1:
                continue
            for rect in rects:
                if _point_in_rect(start, rect) or _point_in_rect(end, rect):
                    continue
                if masked and _is_axis_aligned_segment(start, end):
                    continue
                if _segment_intersects_rect(start, end, rect):
                    crossings += 1
                    break
    return crossings


def _svg_edge_crossing_count(path: Optional[Path]) -> Optional[int]:
    if path is None or not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    paths = _svg_connection_points(text)
    crossings = 0
    for first_index, first in enumerate(paths):
        for second in paths[first_index + 1:]:
            for first_start, first_end in zip(first, first[1:]):
                for second_start, second_end in zip(second, second[1:]):
                    if _segments_share_endpoint(first_start, first_end, second_start, second_end):
                        continue
                    if _segments_intersect(first_start, first_end, second_start, second_end):
                        crossings += 1
                        break
                else:
                    continue
                break
    return crossings


def _svg_node_label_icon_overlap_count(path: Optional[Path], padding: float = 1.0) -> Optional[int]:
    if path is None or not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    labels = _svg_node_label_rects(text, padding=padding)
    icons = _svg_icon_rects(text)
    overlaps = 0
    for label in labels:
        for icon in icons:
            if _rects_overlap(label, icon, tolerance=0):
                overlaps += 1
                break
    return overlaps


def _svg_node_rects(text: str) -> List[Tuple[float, float, float, float]]:
    rects = []
    for rect_match in re.finditer(r"<rect\s+([^>]+)>", text):
        attrs = rect_match.group(1)
        if 'stroke="#94A3B8"' not in attrs:
            continue
        values = {}
        for key in ("x", "y", "width", "height"):
            match = re.search(rf'{key}="(-?\d+(?:\.\d+)?)"', attrs)
            if not match:
                break
            values[key] = float(match.group(1))
        if len(values) == 4:
            rects.append((values["x"], values["y"], values["x"] + values["width"], values["y"] + values["height"]))
    return rects


def _svg_icon_rects(text: str) -> List[Tuple[float, float, float, float]]:
    icons = []
    for image_match in re.finditer(r"<image\s+([^>]+)>", text):
        attrs = image_match.group(1)
        values = {}
        for key in ("x", "y", "width", "height"):
            match = re.search(rf'{key}="(-?\d+(?:\.\d+)?)"', attrs)
            if not match:
                break
            values[key] = float(match.group(1))
        if len(values) == 4:
            icons.append((values["x"], values["y"], values["x"] + values["width"], values["y"] + values["height"]))
    return icons


def _svg_node_label_rects(text: str, padding: float) -> List[Tuple[float, float, float, float]]:
    labels = []
    for text_match in re.finditer(r"<text\s+([^>]*)>(.*?)</text>", text, re.DOTALL):
        attrs = text_match.group(1)
        if "text-bold" not in attrs:
            continue
        x_match = re.search(r'x="(-?\d+(?:\.\d+)?)"', attrs)
        y_match = re.search(r'y="(-?\d+(?:\.\d+)?)"', attrs)
        if not x_match or not y_match:
            continue
        font_match = re.search(r"font-size:(\d+(?:\.\d+)?)px", attrs)
        font_size = float(font_match.group(1)) if font_match else 16.0
        raw_lines = re.findall(r"<tspan[^>]*>(.*?)</tspan>", text_match.group(2), re.DOTALL)
        if not raw_lines:
            raw_label = re.sub(r"<[^>]+>", "", text_match.group(2))
            raw_lines = raw_label.splitlines() or [raw_label]
        lines = [unescape(re.sub(r"<[^>]+>", "", line)).strip() for line in raw_lines]
        lines = [line for line in lines if line]
        if not lines:
            continue
        x = float(x_match.group(1))
        y = float(y_match.group(1))
        width = max(font_size, max(len(line) for line in lines) * font_size * 0.46)
        line_gap = font_size * 1.2
        height = font_size + (len(lines) - 1) * line_gap
        anchor = re.search(r"text-anchor:([a-zA-Z]+)", attrs)
        if anchor and anchor.group(1) == "middle":
            left = x - width / 2
            right = x + width / 2
        elif anchor and anchor.group(1) == "end":
            left = x - width
            right = x
        else:
            left = x
            right = x + width
        top = y - font_size
        bottom = y - font_size + height + font_size * 0.25
        labels.append((left - padding, top - padding, right + padding, bottom + padding))
    return labels


def _svg_edge_label_rects(text: str, padding: float) -> List[Tuple[float, float, float, float]]:
    labels = []
    for text_match in re.finditer(r"<text\s+([^>]*)>(.*?)</text>", text, re.DOTALL):
        attrs = text_match.group(1)
        if "text-italic" not in attrs:
            continue
        x_match = re.search(r'x="(-?\d+(?:\.\d+)?)"', attrs)
        y_match = re.search(r'y="(-?\d+(?:\.\d+)?)"', attrs)
        if not x_match or not y_match:
            continue
        font_match = re.search(r"font-size:(\d+(?:\.\d+)?)px", attrs)
        font_size = float(font_match.group(1)) if font_match else 17.0
        raw_label = re.sub(r"<[^>]+>", "", text_match.group(2))
        label = unescape(raw_label).strip()
        if not label:
            continue
        x = float(x_match.group(1))
        y = float(y_match.group(1))
        width = max(font_size, len(label) * font_size * 0.46)
        height = font_size * 1.25
        anchor = re.search(r"text-anchor:([a-zA-Z]+)", attrs)
        if anchor and anchor.group(1) == "middle":
            left = x - width / 2
            right = x + width / 2
        elif anchor and anchor.group(1) == "end":
            left = x - width
            right = x
        else:
            left = x
            right = x + width
        top = y - height
        bottom = y + font_size * 0.25
        labels.append((left - padding, top - padding, right + padding, bottom + padding))
    return labels


def _svg_connection_points(text: str) -> List[List[Tuple[float, float]]]:
    connections = []
    for path_match in re.finditer(r'<path d="([^"]+)"[^>]*class="connection"[^>]*>', text):
        points = [
            (float(x), float(y))
            for x, y in re.findall(r"[ML]\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)", path_match.group(1))
        ]
        if len(points) >= 2:
            connections.append(points)
    return connections


def _svg_uses_global_card_mask(text: str) -> bool:
    return bool(re.search(r'<mask id="d2-[^"]+"', text))


def _rects_overlap(first, second, tolerance: float) -> bool:
    return not (
        first[2] <= second[0] + tolerance
        or second[2] <= first[0] + tolerance
        or first[3] <= second[1] + tolerance
        or second[3] <= first[1] + tolerance
    )


def _inset_rect(rect, inset: float):
    return (rect[0] + inset, rect[1] + inset, rect[2] - inset, rect[3] - inset)


def _point_in_rect(point, rect) -> bool:
    return rect[0] <= point[0] <= rect[2] and rect[1] <= point[1] <= rect[3]


def _segment_length(start, end) -> float:
    return ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5


def _is_axis_aligned_segment(start, end, tolerance: float = 1.0) -> bool:
    return abs(start[0] - end[0]) <= tolerance or abs(start[1] - end[1]) <= tolerance


def _segment_intersects_rect(start, end, rect) -> bool:
    if _point_in_rect(start, rect) or _point_in_rect(end, rect):
        return True
    corners = [
        (rect[0], rect[1]),
        (rect[2], rect[1]),
        (rect[2], rect[3]),
        (rect[0], rect[3]),
    ]
    edges = list(zip(corners, corners[1:] + corners[:1]))
    return any(_segments_intersect(start, end, edge_start, edge_end) for edge_start, edge_end in edges)


def _segments_intersect(a, b, c, d) -> bool:
    def orientation(p, q, r):
        value = (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])
        if abs(value) < 1e-9:
            return 0
        return 1 if value > 0 else 2

    def on_segment(p, q, r):
        return min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and min(p[1], r[1]) <= q[1] <= max(p[1], r[1])

    o1 = orientation(a, b, c)
    o2 = orientation(a, b, d)
    o3 = orientation(c, d, a)
    o4 = orientation(c, d, b)
    if o1 != o2 and o3 != o4:
        return True
    return (
        (o1 == 0 and on_segment(a, c, b))
        or (o2 == 0 and on_segment(a, d, b))
        or (o3 == 0 and on_segment(c, a, d))
        or (o4 == 0 and on_segment(c, b, d))
    )


def _segments_share_endpoint(a, b, c, d, tolerance: float = 1.0) -> bool:
    return any(
        abs(first[0] - second[0]) <= tolerance and abs(first[1] - second[1]) <= tolerance
        for first in (a, b)
        for second in (c, d)
    )


def run_render_qa(
    expected_formats: Iterable[str], artifact_paths: Dict[str, Path], diagnostics: Iterable[Diagnostic]
) -> QAReport:
    all_diagnostics = list(diagnostics)
    for output_format in expected_formats:
        path = artifact_paths.get(output_format)
        if not path:
            all_diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="missing_render_artifact",
                    message=f"Missing rendered {output_format} artifact.",
                )
            )
            continue
        if not path.exists() or path.stat().st_size == 0:
            all_diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="empty_render_artifact",
                    message=f"Rendered {output_format} artifact is missing or empty.",
                )
            )

    metrics = {
        "artifact_count": len(artifact_paths),
        "error_count": sum(1 for item in all_diagnostics if item.severity == "error"),
        "warning_count": sum(1 for item in all_diagnostics if item.severity == "warning"),
    }
    return QAReport(
        passed=metrics["error_count"] == 0,
        diagnostics=all_diagnostics,
        metrics=metrics,
    )
