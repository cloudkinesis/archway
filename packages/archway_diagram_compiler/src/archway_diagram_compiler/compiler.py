"""High-level compiler entrypoint."""

from pathlib import Path
from hashlib import sha256
import shutil
from typing import Iterable, Optional, Sequence

from archway_diagram_compiler._compat import copy_model
from archway_diagram_compiler.artifacts import (
    qa_report_payload,
    render_plan_payload,
    write_json_artifact,
    write_placement_explanations,
)
from archway_diagram_compiler.d2_backend import render_layout_model_to_d2
from archway_diagram_compiler.enrichment import enrich_production_spec
from archway_diagram_compiler.flow_classifier import classify_flow
from archway_diagram_compiler.flow_ledger import (
    build_initial_flow_ledger,
    update_ledger_for_views,
)
from archway_diagram_compiler.high_fanout_handler import high_fanout_diagnostics
from archway_diagram_compiler.icons import copy_layout_icon_assets
from archway_diagram_compiler.layout_ir import build_layout_model_from_view
from archway_diagram_compiler.models import DiagramBundle, DiagramView, SemanticArchitectureSpec, UserVisibleArtifact
from archway_diagram_compiler.normalizer import normalize_spec
from archway_diagram_compiler.provider_semantic_qa import run_provider_semantic_qa
from archway_diagram_compiler.qa import run_graph_qa, run_render_qa
from archway_diagram_compiler.quality_config import DEFAULT_QUALITY_CONFIG
from archway_diagram_compiler.renderer import D2Renderer, SvgToPngConverter, write_d2
from archway_diagram_compiler.repair_engine import repair_layout
from archway_diagram_compiler.structural_qa import run_structural_qa
from archway_diagram_compiler.svg_postprocess import orthogonalize_connection_paths
from archway_diagram_compiler.view_planner import plan_views
from archway_diagram_compiler.visual_layout_qa import run_visual_layout_qa
from archway_diagram_compiler.views import build_diagram_view_specs
from archway_diagram_compiler.providers import get_provider_catalog


def compile_architecture(
    spec: SemanticArchitectureSpec,
    output_dir: Path,
    renderer: Optional[D2Renderer] = None,
    png_converter: Optional[SvgToPngConverter] = None,
    render_formats: Iterable[str] = ("svg", "png"),
    render: bool = True,
    include_icons: bool = True,
) -> DiagramBundle:
    output_dir = Path(output_dir)
    _prepare_output_dir(output_dir)
    normalized, normalization_diagnostics = normalize_spec(spec)
    normalized, enrichment_diagnostics = enrich_production_spec(normalized)
    normalized = _classify_spec_edges(normalized)
    initial_ledger = build_initial_flow_ledger(normalized)
    graph_qa = run_graph_qa(normalized, normalization_diagnostics + enrichment_diagnostics)

    view_configs = plan_views(normalized, initial_ledger)
    view_specs = build_diagram_view_specs(normalized, view_configs)
    view_specs, omitted_views = _omit_empty_views(view_specs)
    view_specs, suppressed_views = _suppress_redundant_views(view_specs)
    omitted_views.extend(suppressed_views)
    flow_ledger = update_ledger_for_views(
        initial_ledger,
        {view.metadata["diagram_view"]: view.flows for view in view_specs},
    )
    structural_diagnostics = run_structural_qa(
        normalized,
        normalization_diagnostics + enrichment_diagnostics,
        flow_ledger,
    )
    provider_diagnostics = run_provider_semantic_qa(normalized)
    layout_models = [build_layout_model_from_view(view_spec) for view_spec in view_specs]
    layout_diagnostics = high_fanout_diagnostics(layout_models)
    first_view_dir = output_dir / view_specs[0].metadata["diagram_view"]
    first_icon_paths = copy_layout_icon_assets(first_view_dir, layout_models[0].nodes) if include_icons else {}
    d2_text = render_layout_model_to_d2(layout_models[0], icon_paths=first_icon_paths)
    artifact_paths = {}
    render_diagnostics = []
    view_reports = []
    views = []

    expected_formats = tuple(render_formats)
    d2_formats = tuple(
        output_format
        for output_format in expected_formats
        if not (output_format == "png" and "svg" in expected_formats)
    )
    renderer = renderer or D2Renderer()
    png_converter = png_converter or SvgToPngConverter()
    for index, view_spec in enumerate(view_specs):
        layout_model = layout_models[index]
        view_dir = output_dir / view_spec.metadata["diagram_view"]
        icon_paths = copy_layout_icon_assets(view_dir, layout_model.nodes) if include_icons else {}
        view_d2_text = ""
        view_d2_path = view_dir / "diagram.d2"
        view_artifacts = {}
        if icon_paths:
            view_artifacts["icons"] = view_dir / "aws-icons"
        current_render_diagnostics = []
        view_report = None
        for attempt in range(DEFAULT_QUALITY_CONFIG.max_repair_attempts):
            view_d2_text = render_layout_model_to_d2(layout_model, icon_paths=icon_paths)
            view_d2_path = write_d2(view_d2_text, view_dir)
            view_artifacts["d2"] = view_d2_path
            current_render_diagnostics = []
            if render:
                rendered, current_render_diagnostics = renderer.render(view_d2_path, view_dir, d2_formats)
                view_artifacts.update(rendered)
                if "svg" in view_artifacts:
                    rewrites = orthogonalize_connection_paths(view_artifacts["svg"])
                    if rewrites:
                        layout_model.metadata["svg_connection_rewrites"] = rewrites
                if "png" in expected_formats and "svg" in view_artifacts:
                    png_path = view_dir / f"{view_d2_path.stem}.png"
                    png_diagnostic = png_converter.convert(view_artifacts["svg"], png_path)
                    if png_diagnostic is None:
                        view_artifacts["png"] = png_path
                    else:
                        current_render_diagnostics.append(png_diagnostic)
            view_report = run_visual_layout_qa(
                view_spec,
                view_artifacts,
                max_aspect_ratio=DEFAULT_QUALITY_CONFIG.max_aspect_ratio,
                max_visible_edges=DEFAULT_QUALITY_CONFIG.max_visible_edges,
                min_aspect_ratio=DEFAULT_QUALITY_CONFIG.min_primary_aspect_ratio if index == 0 else None,
                layout_model=layout_model,
            )
            if (
                view_report.passed
                or attempt == DEFAULT_QUALITY_CONFIG.max_repair_attempts - 1
                or not _has_repairable_diagnostics(view_report)
            ):
                break
            layout_model = repair_layout(layout_model, view_report)
            layout_models[index] = layout_model
        render_diagnostics.extend(current_render_diagnostics)
        assert view_report is not None
        view_reports.append(view_report)
        view = DiagramView(
            name=view_spec.metadata["diagram_view"],
            title=view_spec.title,
            d2_text=view_d2_text,
            artifact_paths=view_artifacts,
            view_id=view_spec.metadata["diagram_view"],
            view_type=view_spec.metadata["diagram_view"],
            included_nodes=[node.id for node in view_spec.nodes],
            included_flows=[flow.id for flow in view_spec.flows],
            layout_strategy="semantic_view_transitional",
            qa_status="passed" if view_report.passed else "failed",
        )
        views.append(view)
        for artifact_name, path in view_artifacts.items():
            artifact_paths[f"{view.name}_{artifact_name}"] = path
        if index == 0:
            artifact_paths.update(view_artifacts)

    if render:
        render_qa = run_render_qa(
            expected_formats,
            {name: path for name, path in views[0].artifact_paths.items() if name in expected_formats},
            render_diagnostics,
        )
    else:
        render_qa = run_render_qa((), {}, [])

    view_diagnostics = [diagnostic for report in view_reports for diagnostic in report.diagnostics]
    diagnostics = structural_diagnostics + provider_diagnostics + layout_diagnostics + render_qa.diagnostics + view_diagnostics
    final_errors = sum(1 for item in diagnostics if item.severity == "error")
    final_warnings = sum(1 for item in diagnostics if item.severity == "warning")
    qa_report = copy_model(
        graph_qa,
        update={
            "passed": final_errors == 0,
            "diagnostics": diagnostics,
            "metrics": {
                **graph_qa.metrics,
                "error_count": final_errors,
                "warning_count": final_warnings,
                "artifact_count": len(artifact_paths),
                "render_error_count": render_qa.metrics.get("error_count", 0),
                "view_count": len(views),
                "main_visible_edge_count": view_reports[0].metrics.get("visible_edge_count", 0),
            },
        }
    )
    artifact_paths["flow_ledger"] = write_json_artifact(flow_ledger, output_dir / "flow_ledger.json")
    artifact_paths["render_plan"] = write_json_artifact(
        render_plan_payload(normalized, layout_models, view_configs, omitted_views=omitted_views),
        output_dir / "render_plan.json",
    )
    artifact_paths["layout_model"] = write_json_artifact(
        {"views": [_model_to_dict(layout) for layout in layout_models]},
        output_dir / "layout_model.json",
    )
    artifact_paths["qa_report"] = write_json_artifact(qa_report_payload(qa_report), output_dir / "qa_report.json")
    artifact_paths["placement_explanations"] = write_placement_explanations(
        normalized,
        flow_ledger,
        layout_models,
        output_dir / "placement_explanations.md",
        omitted_views=omitted_views,
    )

    return DiagramBundle(
        d2_text=d2_text,
        artifact_paths=artifact_paths,
        diagnostics=diagnostics,
        qa_report=qa_report,
        views=views,
        normalized_spec=normalized,
        flow_ledger=flow_ledger,
        layout_models=layout_models,
        user_visible_artifacts=_deduplicate_user_visible_artifacts(views),
    )


def _model_to_dict(model):
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _deduplicate_user_visible_artifacts(views: Sequence[DiagramView]) -> list:
    visible = []
    seen_keys = set()
    seen_hashes = set()
    user_formats = {"d2", "svg", "png"}
    for view in views:
        view_id = view.view_id or view.name
        for output_format in ("d2", "svg", "png"):
            path = view.artifact_paths.get(output_format)
            if path is None or not path.is_file() or output_format not in user_formats:
                continue
            key = (view_id, output_format)
            if key in seen_keys:
                continue
            digest = sha256(path.read_bytes()).hexdigest()
            if digest in seen_hashes:
                continue
            seen_keys.add(key)
            seen_hashes.add(digest)
            visible.append(
                UserVisibleArtifact(
                    view_id=view_id,
                    format=output_format,
                    path=path,
                    name=f"{view_id}.{output_format}",
                )
            )
    return visible


def _prepare_output_dir(output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def _omit_empty_views(view_specs):
    kept = []
    omitted = []
    for view_spec in view_specs:
        view_id = view_spec.metadata.get("diagram_view", "view")
        if view_id == "network_private_connectivity" and not _is_meaningful_network_view(view_spec):
            omitted.append(
                {
                    "view_id": view_id,
                    "title": view_spec.title,
                    "reason": "No meaningful private connectivity path for this architecture",
                }
            )
            continue
        if view_id == "production_logical_service_flow" or view_spec.nodes or view_spec.flows:
            kept.append(view_spec)
            continue
        omitted.append(
            {
                "view_id": view_id,
                "title": view_spec.title,
                "reason": "No applicable nodes or flows for this view",
            }
        )
    return kept, omitted


def _is_meaningful_network_view(view_spec: SemanticArchitectureSpec) -> bool:
    nodes_by_id = {node.id: node for node in view_spec.nodes}
    if not nodes_by_id or not view_spec.flows:
        return False
    has_vpc_resident_source = any(
        nodes_by_id.get(flow.source) is not None
        and _is_vpc_resident_scope(nodes_by_id[flow.source].scope)
        for flow in view_spec.flows
    )
    has_private_path = any(
        "vpc_link" in flow.id
        or "endpoint" in flow.id
        or flow.metadata.get("endpoint_access_path")
        or _flow_classification(flow) == "private_integration"
        or nodes_by_id.get(flow.source, None) is not None and nodes_by_id[flow.source].service in _PRIVATE_PATH_SERVICES
        or nodes_by_id.get(flow.target, None) is not None and nodes_by_id[flow.target].service in _PRIVATE_PATH_SERVICES
        or nodes_by_id.get(flow.target, None) is not None and _is_vpc_resident_scope(nodes_by_id[flow.target].scope)
        and nodes_by_id.get(flow.source, None) is not None and _is_vpc_resident_scope(nodes_by_id[flow.source].scope)
        for flow in view_spec.flows
    )
    has_meaningful_target = any(
        nodes_by_id.get(flow.target) is not None
        and nodes_by_id[flow.target].service not in {"api_gateway", "vpc_link", "vpc_endpoint"}
        and flow.source != flow.target
        for flow in view_spec.flows
    )
    return has_vpc_resident_source and has_private_path and has_meaningful_target


def _is_vpc_resident_scope(scope: Optional[str]) -> bool:
    return scope in {"vpc_resident", "vpc_workload", "vpc_data"}


_PRIVATE_PATH_SERVICES = {
    "vpc_link",
    "vpc_endpoint",
    "transit_gateway",
    "direct_connect",
    "vpn",
    "privatelink_service",
    "rds_proxy",
    "nat_gateway",
}


def _suppress_redundant_views(view_specs):
    specificity = {
        "fanout_detail_view": 1,
        "rag_ingestion_view": 2,
        "rag_retrieval_view": 3,
        "agent_tool_execution_view": 4,
        "agent_memory_view": 5,
        "ai_security_governance_view": 6,
        "async_flow_view": 7,
        "data_access_view": 8,
        "live_media_delivery_view": 8,
        "media_rights_ad_decisioning_view": 8,
        "media_qoe_analytics_view": 8,
        "network_private_connectivity": 9,
        "production_logical_service_flow": 10,
        "rag_view": 11,
    }
    kept = list(view_specs)
    omitted = []

    # Generic RAG overview is opt-in and must still survive uniqueness checks.
    rag_view = next((view for view in kept if view.metadata.get("diagram_view") == "rag_view"), None)
    if rag_view is not None:
        detailed = [
            view
            for view in kept
            if view.metadata.get("diagram_view") in {"rag_retrieval_view", "rag_ingestion_view"}
        ]
        if detailed:
            kept.remove(rag_view)
            omitted.append(
                {
                    "view_id": "rag_view",
                    "title": rag_view.title,
                    "reason": "Covered by dedicated RAG retrieval/ingestion views.",
                }
            )

    changed = True
    while changed:
        changed = False
        for first_index, first in enumerate(list(kept)):
            first_id = first.metadata.get("diagram_view", "")
            for second in list(kept)[first_index + 1:]:
                second_id = second.metadata.get("diagram_view", "")
                remove, cover = (
                    (first, second)
                    if specificity.get(first_id, 99) > specificity.get(second_id, 99)
                    else (second, first)
                )
                if not _views_overlap(remove, cover):
                    continue
                if _view_explicitly_requested(remove):
                    continue
                if remove in kept:
                    kept.remove(remove)
                    omitted.append(
                        {
                            "view_id": remove.metadata.get("diagram_view", "view"),
                            "title": remove.title,
                            "reason": f"Covered by {cover.metadata.get('diagram_view', 'a more specific view')}.",
                        }
                    )
                    changed = True
                    break
            if changed:
                break
    production = next((view for view in kept if view.metadata.get("diagram_view") == "production_logical_service_flow"), None)
    if production is not None and _production_is_covered_without_overview(production, [view for view in kept if view is not production]):
        kept.remove(production)
        omitted.append(
            {
                "view_id": "production_logical_service_flow",
                "title": production.title,
                "reason": "Covered by specialized views and does not add a separate high-level request or orchestration overview.",
            }
        )
    return kept, omitted


def _production_is_covered_without_overview(production, other_views) -> bool:
    if any((flow.edge_type or flow.metadata.get("classification")) in {"request", "private_integration", "agent_orchestration", "agent_handoff"} for flow in production.flows):
        return False
    if any(flow.metadata.get("homogeneous_fanout_group") for flow in production.flows):
        return False
    ai_edge_types = {
        "rag_retrieval",
        "model_invocation",
        "vector_search",
        "hybrid_search",
        "source_reference",
        "memory_read",
        "memory_write",
        "prompt_lookup",
        "guardrail_check",
        "evaluation",
        "human_approval",
        "model_observability",
        "tool_invocation",
    }
    if not any((flow.edge_type or flow.metadata.get("classification")) in ai_edge_types for flow in production.flows):
        return False
    if not _view_has_ai_nodes(production):
        return False
    if not any(
        view.metadata.get("diagram_view")
        in {"rag_retrieval_view", "rag_ingestion_view", "agent_memory_view", "ai_security_governance_view", "agent_tool_execution_view"}
        for view in other_views
    ):
        return False
    production_flows = {
        source_id
        for flow in production.flows
        for source_id in _source_flow_ids_for_overlap(flow)
    }
    if not production_flows:
        return False
    covered_flows = {
        source_id
        for view in other_views
        for flow in view.flows
        for source_id in _source_flow_ids_for_overlap(flow)
    }
    return production_flows.issubset(covered_flows)


def _view_explicitly_requested(view_spec) -> bool:
    view_id = view_spec.metadata.get("diagram_view", "")
    requested = set(view_spec.metadata.get("expected_views") or view_spec.metadata.get("requested_views") or [])
    return bool(view_id and view_id in requested)


def _flow_classification(flow) -> str:
    metadata_type = flow.metadata.get("classification") or flow.metadata.get("edge_type") or flow.metadata.get("edge_kind")
    if flow.edge_type and flow.edge_type != "request":
        return str(flow.edge_type)
    return str(metadata_type or flow.edge_type or "")


def _view_has_ai_nodes(view) -> bool:
    ai_services = {
        "bedrock",
        "bedrock_knowledge_base",
        "bedrock_agent",
        "bedrock_agentcore",
        "bedrock_guardrails",
        "sagemaker",
        "opensearch_vector_index",
        "opensearch_hybrid_search",
        "generic_vector_store",
    }
    ai_group_tokens = {
        "agent",
        "ai",
        "bedrock",
        "governance",
        "guardrail",
        "memory",
        "model",
        "rag",
        "retrieval",
        "tool",
        "vector",
    }
    for node in view.nodes:
        if node.service in ai_services:
            return True
        node_text = " ".join(
            str(value)
            for value in (
                getattr(node, "name", ""),
                getattr(node, "service", ""),
                getattr(node, "category", ""),
                getattr(node, "metadata", {}).get("role", ""),
                getattr(node, "metadata", {}).get("group_type", ""),
            )
            if value
        ).lower()
        if node.service == "semantic_group" and any(token in node_text for token in ai_group_tokens):
            return True
    return False


def _views_overlap(candidate_remove, candidate_cover) -> bool:
    remove_id = candidate_remove.metadata.get("diagram_view", "")
    cover_id = candidate_cover.metadata.get("diagram_view", "")
    if (
        remove_id == "network_private_connectivity"
        and _is_meaningful_network_view(candidate_remove)
    ):
        return False
    if remove_id == "multi_region_view" or cover_id == "multi_region_view":
        return False
    if {remove_id, cover_id} == {"agent_tool_execution_view", "fanout_detail_view"}:
        return False
    if remove_id == "production_logical_service_flow" and cover_id not in {
        "rag_ingestion_view",
        "rag_retrieval_view",
        "agent_memory_view",
        "ai_security_governance_view",
    }:
        return False
    if remove_id == "production_logical_service_flow" and not _view_has_ai_nodes(candidate_remove):
        return False
    first_nodes = _node_identity_set(candidate_remove.nodes)
    second_nodes = _node_identity_set(candidate_cover.nodes)
    first_labels = {_normalized_label(node.name) for node in candidate_remove.nodes if node.name}
    second_labels = {_normalized_label(node.name) for node in candidate_cover.nodes if node.name}
    first_sources = _source_node_set(candidate_remove.nodes)
    second_sources = _source_node_set(candidate_cover.nodes)
    first_roles = _semantic_role_set(candidate_remove.nodes)
    second_roles = _semantic_role_set(candidate_cover.nodes)
    first_flows = {_source_flow_id_for_overlap(flow) for flow in candidate_remove.flows}
    second_flows = {_source_flow_id_for_overlap(flow) for flow in candidate_cover.flows}
    if not first_flows or not second_flows or not first_nodes:
        return False
    node_overlap = max(
        _coverage_ratio(first_nodes, second_nodes),
        _coverage_ratio(first_labels, second_labels),
        _coverage_ratio(first_sources, second_sources),
    )
    flow_overlap = _coverage_ratio(first_flows, second_flows)
    role_overlap = _coverage_ratio(first_roles, second_roles)
    return node_overlap > 0.8 and flow_overlap > 0.8 and role_overlap > 0.8


def _node_identity_set(nodes: Sequence) -> set:
    return {str(node.id) for node in nodes}


def _source_node_set(nodes: Sequence) -> set:
    source_ids = set()
    for node in nodes:
        source_ids.add(str(node.metadata.get("source_node_id") or node.id))
        for source_id in node.metadata.get("source_node_ids", []) or []:
            source_ids.add(str(source_id))
    return source_ids


def _semantic_role_set(nodes: Sequence) -> set:
    roles = set()
    for node in nodes:
        roles.add(str(node.metadata.get("role") or node.category or node.service or ""))
        roles.add(str(node.scope or ""))
    return {role for role in roles if role}


def _normalized_label(value: str) -> str:
    return " ".join(str(value).replace("\\n", " ").split()).strip().lower()


def _overlap_ratio(first: set, second: set) -> float:
    if not first or not second:
        return 0.0
    return len(first & second) / float(min(len(first), len(second)))


def _coverage_ratio(candidate: set, cover: set) -> float:
    if not candidate or not cover:
        return 0.0
    return len(candidate & cover) / float(len(candidate))


def _source_flow_id_for_overlap(flow):
    source_ids = flow.metadata.get("source_flow_ids")
    if isinstance(source_ids, list) and source_ids:
        return tuple(sorted(str(item) for item in source_ids))
    return str(flow.metadata.get("source_flow_id") or flow.id)


def _source_flow_ids_for_overlap(flow) -> set:
    source_ids = flow.metadata.get("source_flow_ids")
    if isinstance(source_ids, list) and source_ids:
        return {str(item) for item in source_ids}
    return {_source_flow_id_for_overlap(flow)}


def _has_repairable_diagnostics(report) -> bool:
    repairable = {
        "too_many_visible_edges",
        "too_many_incoming_edges",
        "diagram_aspect_ratio_too_wide",
        "diagram_aspect_ratio_too_narrow",
        "diagonal_connector_segments",
        "edge_label_overlap",
        "edge_crosses_node",
        "too_many_edge_crossings",
        "node_overlap",
    }
    return any(diagnostic.code in repairable for diagnostic in report.diagnostics)


def _classify_spec_edges(spec: SemanticArchitectureSpec) -> SemanticArchitectureSpec:
    nodes_by_id = {node.id: node for node in spec.nodes}
    flows = []
    for flow in spec.flows:
        source = nodes_by_id.get(flow.source)
        target = nodes_by_id.get(flow.target)
        if source is None or target is None:
            flows.append(flow)
            continue
        if flow.edge_type is not None:
            flows.append(flow)
            continue
        classification = classify_flow(flow, source, target, get_provider_catalog(source.provider))
        metadata = dict(flow.metadata)
        metadata.setdefault("classification_reason", classification.reason)
        flows.append(copy_model(flow, deep=True, update={"edge_type": classification.edge_type, "metadata": metadata}))
    return copy_model(spec, deep=True, update={"flows": flows})
