"""Artifact writers for V2 compiler side outputs."""

import json
from pathlib import Path
from typing import Iterable, List, Optional, Union

from pydantic import BaseModel

from archway_diagram_compiler.models import (
    FlowLedger,
    LayoutModel,
    QAReport,
    SemanticArchitectureSpec,
)


def write_json_artifact(model: Union[BaseModel, dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(model, BaseModel):
        payload = _model_to_dict(model)
    else:
        payload = model
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def write_placement_explanations(
    spec: SemanticArchitectureSpec,
    ledger: FlowLedger,
    layout_models: Iterable[LayoutModel],
    path: Path,
    omitted_views: Optional[Iterable[dict]] = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = [f"# Placement Explanations", "", f"Architecture: {spec.title}", ""]
    nodes_by_id = {node.id: node for node in spec.nodes}
    for node in sorted(spec.nodes, key=lambda item: item.id):
        if node.scope in {"regional_managed_data", "regional_managed_ai", "regional_security", "regional_observability", "regional_audit"}:
            lines.append(
                f"- `{node.name}` is rendered outside VPC boundaries because `{node.service}` is a `{node.scope}` managed AWS service."
            )
        if node.service in {"bedrock", "bedrock_agent", "bedrock_agentcore", "bedrock_knowledge_base", "bedrock_guardrails"}:
            lines.append(
                f"- `{node.name}` is treated as managed AI control/data plane capability, so AI views place it outside VPC boundaries and show private access through endpoints when needed."
            )
        if node.service in {"opensearch_vector_index", "generic_vector_store"}:
            lines.append(
                f"- `{node.name}` is modeled as a vector index for retrieval instead of a generic OpenSearch box."
            )
        if node.service == "opensearch_hybrid_search":
            lines.append(
                f"- `{node.name}` is modeled as an OpenSearch hybrid search index so lexical/vector retrieval is explicit."
            )
        if node.service == "opensearch_log_analytics_index":
            lines.append(
                f"- `{node.name}` is modeled as an OpenSearch log analytics index and appears with governance/audit concerns."
            )
        if node.service == "opensearch_application_search_index":
            lines.append(
                f"- `{node.name}` is modeled as an application search index rather than a RAG vector store."
            )
        if node.scope in {"vpc_resident", "vpc_workload", "vpc_data"}:
            lines.append(
                f"- `{node.name}` is rendered inside `{node.vpc_id or 'the VPC'}` because `{node.service}` is VPC-resident."
            )
        if node.service == "vpc_endpoint":
            target = node.metadata.get("target_node_id") or node.metadata.get("target_service")
            lines.append(
                f"- `{node.name}` is rendered as an access path endpoint for `{target}`, not as a duplicate target service."
            )
    lines.append("")
    fanout_groups = _homogeneous_fanout_groups(ledger, layout_models)
    if fanout_groups:
        lines.append("## Homogeneous Fan-Out Summaries")
        for group_id, group in sorted(fanout_groups.items()):
            entries = group["entries"]
            targets = len(entries)
            lines.append(
                f"- `{group['source_label']}` had {targets} homogeneous outgoing flows to {group['target_label']}. "
                f"The primary logical view summarizes them as “{group['aggregate_label']}” to reduce crossings. "
                "The full target list is available in `fanout_detail_view`."
            )
        lines.append("")
    architecture_advisories = _architecture_advisory_explanations(spec)
    if architecture_advisories:
        lines.append("## Architecture Advisories")
        lines.extend(architecture_advisories)
        lines.append("")
    endpoint_group_explanations = _endpoint_group_explanations(layout_models)
    if endpoint_group_explanations:
        lines.append("## Private Access Grouping")
        lines.extend(endpoint_group_explanations)
        lines.append("")
    ai_view_explanations = _ai_view_explanations(ledger, layout_models)
    if ai_view_explanations:
        lines.append("## AI/RAG View Splits")
        lines.extend(ai_view_explanations)
        lines.append("")
    omitted = list(omitted_views or [])
    if omitted:
        lines.append("## Omitted Views")
        for view in omitted:
            lines.append(f"- `{view['view_id']}`: {view['reason']}.")
        lines.append("")
    lines.append("## Flow Ledger Summary")
    for entry in ledger.entries:
        source_label = nodes_by_id.get(entry.source).name if nodes_by_id.get(entry.source) else entry.source
        target_label = nodes_by_id.get(entry.target).name if nodes_by_id.get(entry.target) else entry.target
        lines.append(
            f"- `{source_label} -> {target_label}`: {entry.status}"
            + (f" in `{entry.view_id}`" if entry.view_id else "")
            + (f" ({entry.reason})" if entry.reason else "")
        )
    lines.append("")
    lines.append("## Views")
    for layout in layout_models:
        lines.append(f"- `{layout.view_id}`: {len(layout.nodes)} layout nodes, {len(layout.edges)} layout edges.")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def _architecture_advisory_explanations(spec: SemanticArchitectureSpec) -> List[str]:
    lines: List[str] = []
    nodes_by_id = {node.id: node for node in spec.nodes}
    flows_by_target = {}
    for flow in spec.flows:
        flows_by_target.setdefault(flow.target, []).append(flow)
    auth_services = {"cognito", "iam"}
    for node in sorted(spec.nodes, key=lambda item: item.id):
        if node.service not in {"api_gateway", "appsync"}:
            continue
        has_public_incoming = any(
            nodes_by_id.get(flow.source)
            and nodes_by_id[flow.source].service in {"external_actor", "external_user", "route53", "cloudfront"}
            for flow in flows_by_target.get(node.id, [])
        )
        has_auth = any(
            (nodes_by_id.get(flow.source) and nodes_by_id[flow.source].service in auth_services)
            or flow.edge_type in {"auth", "secret_access"}
            or "auth" in str(flow.label or "").lower()
            for flow in spec.flows
            if flow.source == node.id or flow.target == node.id
        )
        if not has_public_incoming or has_auth or node.metadata.get("auth") in {"cognito_jwt", "iam", "jwt"}:
            continue
        if node.metadata.get("auth_mode") == "public_demo" or node.metadata.get("intentionally_public") is True:
            lines.append(
                f"- `{node.name}` is intentionally public for demo/test use. Mark production APIs with a visible Cognito, IAM, JWT, or custom authorizer."
            )
        else:
            lines.append(
                f"- `{node.name}` is public-facing without a visible auth provider. For production, add a Cognito/JWT authorizer, IAM auth, or another explicit authorization control."
            )
    return lines


def _endpoint_group_explanations(layout_models: Iterable[LayoutModel]) -> List[str]:
    lines: List[str] = []
    seen = set()
    for layout in layout_models:
        for node in layout.nodes:
            if not node.metadata.get("endpoint_access_group"):
                continue
            key = (layout.view_id, node.id)
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                f"- `{node.label}` in `{layout.view_id}` summarizes parallel endpoint access paths. Individual endpoint targets remain visible in the network view."
            )
    return lines


def render_plan_payload(
    spec: SemanticArchitectureSpec,
    layout_models: Iterable[LayoutModel],
    view_configs: Optional[Iterable] = None,
    omitted_views: Optional[Iterable[dict]] = None,
) -> dict:
    views = [
        {
            "view_id": layout.view_id,
            "title": layout.title,
            "layout_strategy": layout.metadata.get("source", "layout_model"),
            "node_count": len(layout.nodes),
            "edge_count": len(layout.edges),
        }
        for layout in layout_models
    ]
    planned_views = []
    for config in view_configs or []:
        if isinstance(config, BaseModel):
            planned_views.append(_model_to_dict(config))
        else:
            planned_views.append(dict(config))
    return {
        "title": spec.title,
        "views": views,
        "omitted_views": list(omitted_views or []),
        "planned_views": planned_views,
        "rule_results": spec.metadata.get("rule_results", []),
    }


def qa_report_payload(report: QAReport) -> dict:
    return _model_to_dict(report)


def _model_to_dict(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _homogeneous_fanout_groups(ledger: FlowLedger, layout_models: Iterable[LayoutModel]) -> dict:
    groups = {}
    for entry in ledger.entries:
        if entry.status == "collapsed_into_group" and entry.reason in {
            "homogeneous fan-out summarized to reduce crossings",
            "agent tool fan-out summarized to reduce crossings",
        }:
            groups.setdefault(entry.group_id or "fanout_group", {"entries": []})["entries"].append(entry)
    if not groups:
        return groups
    aggregate_labels = {}
    source_labels = {}
    target_labels = {}
    for layout in layout_models:
        for node in layout.nodes:
            aggregate_labels.setdefault(node.id, node.label)
            for source_id in node.source_node_ids:
                source_labels.setdefault(source_id, node.label)
        for edge in layout.edges:
            if edge.metadata.get("homogeneous_fanout_group"):
                target_labels.setdefault(edge.target, _target_label_from_aggregate(aggregate_labels.get(edge.target, edge.target)))
    for group_id, group in groups.items():
        entries = group["entries"]
        source_id = entries[0].source if entries else ""
        aggregate_label = aggregate_labels.get(group_id, group_id)
        group["source_label"] = source_labels.get(source_id, source_id)
        group["aggregate_label"] = aggregate_label
        group["target_label"] = target_labels.get(group_id, _target_label_from_aggregate(aggregate_label))
    return groups


def _target_label_from_aggregate(label: str) -> str:
    clean = label.split("×", 1)[0].strip()
    if clean == "Event targets":
        return "Lambda targets"
    return clean[:1].lower() + clean[1:] if clean else "targets"


def _ai_view_explanations(ledger: FlowLedger, layout_models: Iterable[LayoutModel]) -> List[str]:
    view_ids = {layout.view_id for layout in layout_models}
    classifications_by_view = {}
    for entry in ledger.entries:
        if entry.view_id:
            classifications_by_view.setdefault(entry.view_id, set()).add(entry.classification)
    lines: List[str] = []
    if "rag_retrieval_view" in view_ids:
        lines.append("- Runtime RAG retrieval is separated into `rag_retrieval_view` so Knowledge Base, vector search, and source references are not mixed with ingestion.")
    if "rag_ingestion_view" in view_ids:
        lines.append("- Document ingestion, chunking, embedding, and vector indexing are separated into `rag_ingestion_view`.")
    if "agent_tool_execution_view" in view_ids:
        lines.append("- Agent tool calls are shown in `agent_tool_execution_view`; large homogeneous tool fan-out is summarized in primary views and expanded in detail views.")
    if "agent_memory_view" in view_ids:
        lines.append("- Prompt lookup and memory read/write flows are isolated in `agent_memory_view`.")
    if "ai_security_governance_view" in view_ids:
        governance_types = sorted(classifications_by_view.get("ai_security_governance_view", []))
        suffix = f" ({', '.join(governance_types)})" if governance_types else ""
        lines.append(f"- Guardrails, evaluation, approval, audit, observability, secrets, and encryption concerns are grouped in `ai_security_governance_view`{suffix}.")
    return lines
