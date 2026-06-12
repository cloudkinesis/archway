"""D2 renderer backend for LayoutModel."""

import re
from collections import defaultdict
from typing import Dict, List, Optional

from archway_diagram_compiler.models import LayoutEdge, LayoutModel, LayoutNode


def render_layout_model_to_d2(layout: LayoutModel, icon_paths: Optional[Dict[str, str]] = None) -> str:
    icon_paths = icon_paths or {}
    lines: List[str] = [
        "direction: right",
        "style.fill: \"#F8FAFC\"",
        "style.stroke: transparent",
        "",
    ]
    lanes = sorted(layout.lanes, key=lambda lane: (lane.order, lane.id))
    nodes_by_lane = defaultdict(list)
    for node in sorted(layout.nodes, key=lambda item: (item.rank, item.order, item.id)):
        nodes_by_lane[node.lane_id].append(node)

    lines.append(f"{identifier(layout.view_id)}: {quote(_display_text(layout.title))} {{")
    lines.append("  direction: right")
    visible_lane_count = len([lane for lane in lanes if nodes_by_lane.get(lane.id)])
    visible_node_count = sum(len(nodes_by_lane.get(lane.id, [])) for lane in lanes)
    lines.append(f"  grid-columns: {_grid_columns(layout, visible_lane_count, visible_node_count)}")
    if layout.metadata.get("spacing") == "expanded":
        gap = 80 + (int(layout.metadata.get("spacing_attempt", 1)) - 1) * 24
        lines.append(f"  grid-gap: {gap}")
    _write_container_style(lines, indent="  ")
    node_refs: Dict[str, str] = {}
    for lane in lanes:
        lane_nodes = nodes_by_lane.get(lane.id)
        if not lane_nodes:
            continue
        lines.append(f"  {identifier(lane.id)}: {quote(_display_text(lane.label))} {{")
        lines.append("    direction: down")
        lines.append("    grid-columns: 1")
        if layout.metadata.get("spacing") == "expanded":
            gap = 56 + (int(layout.metadata.get("spacing_attempt", 1)) - 1) * 16
            lines.append(f"    grid-gap: {gap}")
        _write_container_style(lines, indent="    ")
        for node in lane_nodes:
            node_refs[node.id] = f"{identifier(layout.view_id)}.{identifier(lane.id)}.{identifier(node.id)}"
            _write_node(lines, node, icon_paths, indent="    ")
        lines.append("  }")
    lines.append("}")
    lines.append("")

    for edge in sorted(layout.edges, key=lambda item: item.id):
        if edge.source not in node_refs or edge.target not in node_refs:
            continue
        suffix = f": {quote(_summarize_edge_label(edge.label))}" if edge.label else ""
        lines.append(f"{node_refs[edge.source]} -> {node_refs[edge.target]}{suffix} {{")
        if edge.style == "dashed":
            lines.append("  style.stroke: \"#64748B\"")
            lines.append("  style.stroke-width: 2")
            lines.append("  style.stroke-dash: 5")
        elif edge.style == "dotted":
            lines.append("  style.stroke: \"#64748B\"")
            lines.append("  style.stroke-width: 2")
            lines.append("  style.stroke-dash: 2")
        else:
            lines.append("  style.stroke: \"#334155\"")
            lines.append("  style.stroke-width: 2")
        lines.append("  style.font-size: 17")
        lines.append("  style.font-color: \"#334155\"")
        lines.append("}")
    return "\n".join(lines).rstrip() + "\n"


def _write_node(lines: List[str], node: LayoutNode, icon_paths: Dict[str, str], indent: str) -> None:
    label = _summarize_node_label(node.label if not node.subtitle else f"{node.label}\\n{node.subtitle}")
    lines.append(f"{indent}{identifier(node.id)}: {quote(label)} {{")
    icon_path = icon_paths.get(node.id)
    if icon_path:
        lines.append(f"{indent}  icon: {icon_path}")
        lines.append(f"{indent}  width: 230")
    lines.extend(
        [
            f"{indent}  shape: rectangle",
            f"{indent}  height: {_node_height(node)}",
            f"{indent}  style.fill: \"{_node_fill(node)}\"",
            f"{indent}  style.stroke: \"{_node_stroke(node)}\"",
            f"{indent}  style.stroke-width: 1",
            f"{indent}  style.border-radius: 8",
            f"{indent}  style.shadow: true",
            f"{indent}  style.font-size: {_node_font_size(node)}",
        ]
    )
    lines.append(f"{indent}}}")


def _write_container_style(lines: List[str], indent: str) -> None:
    lines.extend(
        [
            f"{indent}style.fill: \"#FFFFFF\"",
            f"{indent}style.stroke: \"#CBD5E1\"",
            f"{indent}style.stroke-width: 1",
            f"{indent}style.border-radius: 8",
        ]
    )


def _grid_columns(layout: LayoutModel, visible_lane_count: int, visible_node_count: int) -> int:
    if visible_lane_count <= 0:
        return 1
    if layout.metadata.get("spacing") == "expanded" and visible_lane_count >= 4:
        return min(3, visible_lane_count)
    if visible_node_count <= 8 and visible_lane_count >= 4:
        return min(3, visible_lane_count)
    return max(1, min(5, visible_lane_count))


def quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"') + '"'


def _display_text(value: str) -> str:
    replacements = {
        " Ai ": " AI ",
        " Rag ": " RAG ",
        " Api ": " API ",
        " Vpc": " VPC",
        " Vpc ": " VPC ",
        " Sqs": " SQS",
        " Sns": " SNS",
        " Kms": " KMS",
        " Iam": " IAM",
        " Jwt": " JWT",
        " Ecs": " ECS",
        " Eks": " EKS",
        " Ec2": " EC2",
        " Waf": " WAF",
        "Cloudwatch": "CloudWatch",
        "Cloudtrail": "CloudTrail",
        "Dynamodb": "DynamoDB",
        "Opensearch": "OpenSearch",
        "Bedrock": "Bedrock",
        "Api Gateway": "API Gateway",
        " And ": " and ",
    }
    text = value
    for old, new in replacements.items():
        text = text.replace(old, new)
    for acronym in ("AI", "RAG", "API", "VPC", "SQS", "SNS", "S3", "KMS", "IAM", "JWT", "ECS", "EKS", "EC2", "WAF"):
        text = re.sub(rf"\b{acronym.title()}\b", acronym, text)
    text = text.replace("Open Search", "OpenSearch").replace("Cloudwatch", "CloudWatch").replace("Cloudtrail", "CloudTrail")
    return text


def _summarize_node_label(label: str) -> str:
    label = _display_text(label)
    lines = []
    for part in label.split("\n"):
        lines.extend(part.split("\\n"))
    summarized = []
    for line in lines:
        summarized.append(_shorten(line, 48))
    return " / ".join(line for line in summarized if line)


def _summarize_edge_label(label: str) -> str:
    return _shorten(_display_text(label), 40)


def _shorten(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    lowered = value.lower()
    if "application and model telemetry" in lowered:
        return "Application and model telemetry"
    if "application telemetry" in lowered:
        return "Application telemetry"
    return value[: max(0, limit - 1)].rstrip() + "…"


def _node_height(node: LayoutNode) -> int:
    label_lines = max(1, node.label.count("\n") + 1) + (1 if node.subtitle else 0)
    if node.metadata.get("same_lane_fanout_group") or node.metadata.get("fanout_group"):
        return 112
    return 164 if label_lines > 1 else 118


def _node_fill(node: LayoutNode) -> str:
    if node.metadata.get("endpoint_access_group") or node.metadata.get("homogeneous_fanout_group") or node.metadata.get("fanout_group"):
        return "#F8FAFC"
    return "#FFFFFF"


def _node_stroke(node: LayoutNode) -> str:
    if node.metadata.get("endpoint_access_group") or node.metadata.get("homogeneous_fanout_group") or node.metadata.get("fanout_group"):
        return "#64748B"
    return "#94A3B8"


def _node_font_size(node: LayoutNode) -> int:
    return 15 if node.subtitle or "\n" in node.label else 16


def identifier(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip())
    cleaned = cleaned.strip("_") or "node"
    if cleaned[0].isdigit():
        cleaned = f"n_{cleaned}"
    return cleaned.lower()
