from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import sys
from typing import Any, Literal

from app.core.config import get_settings
from app.core.logging import AuditLogger, hash_payload
from app.models.domain import ArchitectureSpec, DiagramArtifact, DiagramGalleryResult, DiagramQAReport, HealthCheckResult, HealthStatus
from app.services.artifacts import ArtifactStore
from app.services.view_planner import DiagramViewMapping, customer_title_for_compiler_view


class DiagramCompilerAdapter:
    def __init__(self):
        self.settings = get_settings()
        self.artifacts = ArtifactStore()

    def compile_poc_diagrams(self, architecture_spec: ArchitectureSpec, session_id: str) -> DiagramGalleryResult:
        return self._compile(architecture_spec, session_id, "poc")

    def compile_production_diagrams(self, architecture_spec: ArchitectureSpec, session_id: str) -> DiagramGalleryResult:
        return self._compile(architecture_spec, session_id, "production")

    def get_compiler_health(self) -> HealthCheckResult:
        try:
            self._ensure_import_path()
            from archway_diagram_compiler.adapters.archway import archway_to_semantic_spec  # noqa: F401
            from archway_diagram_compiler.compiler import compile_architecture  # noqa: F401
        except Exception as exc:
            return HealthCheckResult(
                id="diagram_compiler",
                label="Existing Archway diagram compiler",
                status=HealthStatus.failed,
                required=True,
                reason=f"Compiler import failed: {exc}",
                details={"path": str(self.settings.diagram_compiler_path)},
            )
        return HealthCheckResult(
            id="diagram_compiler",
            label="Existing Archway diagram compiler",
            status=HealthStatus.ready,
            required=True,
            reason="Compiler package and Archway adapter are importable.",
            details={"path": str(self.settings.diagram_compiler_path)},
        )

    def _compile(self, architecture_spec: ArchitectureSpec, session_id: str, mode: Literal["poc", "production"]) -> DiagramGalleryResult:
        self._ensure_import_path()
        from archway_diagram_compiler.adapters.archway import archway_to_semantic_spec
        from archway_diagram_compiler.compiler import compile_architecture

        audit = AuditLogger(session_id)
        output_dir = self.artifacts.session_root(session_id) / "diagrams" / mode / architecture_spec.id
        with audit.timed(
            "diagrams",
            "compile_existing_archway_compiler",
            inputs_hash=hash_payload(architecture_spec.model_dump()),
            tool_name="archway_diagram_compiler.compile_architecture",
            timeout_seconds=self.settings.compiler_total_timeout_seconds,
        ):
            semantic_spec = archway_to_semantic_spec(architecture_spec)
            semantic_spec = _normalize_semantic_flow_types(semantic_spec)
            bundle = self._run_compiler_with_timeout(
                lambda: compile_architecture(semantic_spec, output_dir, render_formats=("svg",)),
                timeout_seconds=self.settings.compiler_total_timeout_seconds,
            )
        diagrams: list[DiagramArtifact] = []
        qa_reports: list[DiagramQAReport] = []
        placement_id = None
        placement_path = bundle.artifact_paths.get("placement_explanations")
        if placement_path:
            placement_id = self.artifacts.to_artifact_id(session_id, Path(placement_path))
        view_mappings = [
            DiagramViewMapping(**mapping)
            for mapping in architecture_spec.metadata.get("diagram_view_mappings", [])
        ]
        for view in bundle.views:
            compiler_view_id = view.view_id or view.name
            matching_mappings = [mapping for mapping in view_mappings if mapping.compiler_view_id == compiler_view_id]
            selected_mapping = matching_mappings[0] if matching_mappings else None
            format_paths = {}
            for fmt, path in view.artifact_paths.items():
                if fmt in {"svg", "png", "d2"} and Path(path).is_file():
                    format_paths[fmt] = self.artifacts.to_artifact_id(session_id, Path(path))
            diagrams.append(
                DiagramArtifact(
                    id=f"{mode}_{compiler_view_id}",
                    title=customer_title_for_compiler_view(compiler_view_id, view_mappings) if view_mappings else view.title,
                    mode=mode,
                    view_id=compiler_view_id,
                    compiler_view_id=compiler_view_id,
                    semantic_view_id=selected_mapping.semantic_view_id if selected_mapping else None,
                    user_description=selected_mapping.user_description if selected_mapping else None,
                    rendered_as_native_view=selected_mapping.rendered_as_native_view if selected_mapping else True,
                    fallback_reason=selected_mapping.fallback_reason if selected_mapping else None,
                    format_paths=format_paths,
                    preview_svg_artifact_id=format_paths.get("svg"),
                    placement_explanation_artifact_id=placement_id,
                )
            )
        icon_metrics = _icon_embedding_metrics(session_id, self.artifacts, diagrams)
        rendered_view_ids = [diagram.compiler_view_id or diagram.view_id for diagram in diagrams]
        view_rendering_ledger = _view_rendering_ledger(architecture_spec, rendered_view_ids, bundle, mode)
        missing_requested_views = view_rendering_ledger.get("unsupported_not_rendered", [])
        qa_reports.append(
            DiagramQAReport(
                view_id="bundle",
                passed=bundle.qa_report.passed,
                diagnostics=[
                    *_missing_view_diagnostics(missing_requested_views),
                    *_icon_embedding_diagnostics(icon_metrics),
                    *[_model_dump(item) for item in bundle.qa_report.diagnostics],
                ],
                metrics={**bundle.qa_report.metrics, "icon_embedding": icon_metrics, "view_rendering_ledger": view_rendering_ledger},
            )
        )
        return DiagramGalleryResult(
            session_id=session_id,
            architecture_spec_id=architecture_spec.id,
            mode=mode,
            diagrams=diagrams,
            qa_reports=qa_reports,
            rendered_view_ids=rendered_view_ids,
            missing_requested_views=missing_requested_views,
            view_rendering_ledger=view_rendering_ledger,
        )

    def _ensure_import_path(self) -> None:
        path = str(self.settings.diagram_compiler_path)
        if path not in sys.path:
            sys.path.insert(0, path)

    def _run_compiler_with_timeout(self, compile_call, *, timeout_seconds: float):
        if timeout_seconds <= 0:
            return compile_call()
        executor = ThreadPoolExecutor(max_workers=self.settings.compiler_max_concurrent_jobs, thread_name_prefix="archway-d2-compiler")
        future = executor.submit(compile_call)
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise TimeoutError(
                f"Existing Archway diagram compiler exceeded configured timeout of {timeout_seconds:g} seconds."
            ) from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)


def _model_dump(value):
    return value.model_dump() if hasattr(value, "model_dump") else value.dict()


def _normalize_semantic_flow_types(semantic_spec):
    """Preserve Archway's typed flow intent when passing through the compiler adapter."""
    supported = {
        "request",
        "auth",
        "control",
        "data_read",
        "data_write",
        "async",
        "event",
        "notification",
        "secret_access",
        "encryption",
        "audit",
        "observability",
        "private_integration",
        "vpc_endpoint_access",
        "rag_retrieval",
        "model_invocation",
        "agent_orchestration",
        "agent_handoff",
        "tool_invocation",
        "embedding_generation",
        "vector_search",
        "hybrid_search",
        "document_ingestion",
        "document_chunking",
        "document_embedding",
        "memory_read",
        "memory_write",
        "prompt_lookup",
        "guardrail_check",
        "evaluation",
        "human_approval",
        "audit_trace",
        "model_observability",
        "source_reference",
        "media_delivery",
        "media_rights",
        "media_ad_decision",
        "media_qoe",
    }
    aliases = {
        "ml_inference": "model_invocation",
        "training_data": "data_read",
        "data_access": "data_read",
        "state_read": "data_read",
        "state_write": "data_write",
        "cache_write": "data_write",
        "audit_write": "audit_trace",
        "analytics_publish": "data_write",
        "data_processing": "data_write",
        "queue_for_review": "human_approval",
        "policy_change": "guardrail_check",
        "policy_check": "guardrail_check",
        "external_write": "human_approval",
        "stream_processing": "async",
        "stream_ingestion": "async",
        "workflow_start": "async",
        "tool_call": "tool_invocation",
    }
    normalized_flows = []
    for flow in semantic_spec.flows:
        metadata = dict(flow.metadata or {})
        requested = str(metadata.get("edge_type") or metadata.get("classification") or metadata.get("edge_kind") or "")
        edge_type = aliases.get(requested, requested)
        if edge_type not in supported:
            edge_type = flow.edge_type
        if metadata.get("logical_detail_only"):
            metadata["endpoint_access_path"] = True
        if edge_type:
            metadata["classification"] = edge_type
            normalized_flows.append(flow.model_copy(update={"edge_type": edge_type, "metadata": metadata}))
        else:
            normalized_flows.append(flow)
    return semantic_spec.model_copy(update={"flows": normalized_flows})


def _view_rendering_ledger(architecture_spec: ArchitectureSpec, rendered_view_ids: list[str], bundle, mode: str) -> dict[str, list[dict[str, Any]]]:
    ledger: dict[str, list[dict[str, Any]]] = {
        "rendered_explicitly": [],
        "rendered_via_broader_supported_view": [],
        "omitted_with_reason": [],
        "unsupported_not_rendered": [],
    }
    expected = set(architecture_spec.metadata.get("expected_views") or [])
    rendered = set(rendered_view_ids)
    omitted = _omitted_view_reasons(bundle)
    mappings = [
        DiagramViewMapping(**item)
        for item in architecture_spec.metadata.get("diagram_view_mappings", [])
    ]
    for view_id in sorted(expected):
        item = {
            "mode": mode,
            "view_id": view_id,
            "compiler_view_id": view_id,
            "semantic_view_id": None,
            "classification": "compiler_view",
        }
        if view_id in rendered:
            item["reason"] = "Requested compiler view was rendered directly by the D2 compiler."
            ledger["rendered_explicitly"].append(item)
        elif broader := _broader_rendering_for_compiler_view(view_id, mappings, rendered):
            item.update(broader)
            ledger["rendered_via_broader_supported_view"].append(item)
        elif view_id in omitted:
            item["reason"] = omitted[view_id]
            ledger["omitted_with_reason"].append(item)
        else:
            item["missing_level"] = "compiler"
            item["reason"] = "The existing Archway D2 compiler did not emit this requested view."
            ledger["unsupported_not_rendered"].append(item)
    for mapping in mappings:
        item = {
            "mode": mode,
            "view_id": mapping.semantic_view_id,
            "semantic_view_id": mapping.semantic_view_id,
            "compiler_view_id": mapping.compiler_view_id,
            "classification": "semantic_view",
            "user_title": mapping.user_title,
        }
        if mapping.compiler_view_id == "unsupported_by_current_compiler":
            item["missing_level"] = "semantic"
            item["reason"] = mapping.fallback_reason or "The current compiler has no supported view for this semantic intent."
            ledger["unsupported_not_rendered"].append(item)
        elif mapping.compiler_view_id in rendered:
            item["reason"] = (
                "Semantic view was rendered directly by the compiler."
                if mapping.rendered_as_native_view
                else mapping.fallback_reason or f"Semantic view is represented through {mapping.compiler_view_id}."
            )
            if mapping.rendered_as_native_view:
                ledger["rendered_explicitly"].append(item)
            else:
                ledger["rendered_via_broader_supported_view"].append(item)
        elif broader := _broader_rendering_for_semantic_view(mapping.semantic_view_id, rendered):
            item.update(broader)
            ledger["rendered_via_broader_supported_view"].append(item)
        elif mapping.compiler_view_id in omitted:
            item["reason"] = omitted[mapping.compiler_view_id]
            ledger["omitted_with_reason"].append(item)
        else:
            item["missing_level"] = "semantic"
            item["reason"] = mapping.fallback_reason or "The existing Archway D2 compiler did not emit the compiler view mapped from this semantic view."
            ledger["unsupported_not_rendered"].append(item)
    return ledger


def _missing_view_diagnostics(missing_requested_views: list[dict[str, Any]]) -> list[dict]:
    return [
        {
            "severity": "warning",
            "code": "requested_view_not_rendered",
            "message": f"Requested {item.get('missing_level', 'compiler')} view {item['view_id']} was not rendered: {item['reason']}",
            "node_id": None,
            "flow_id": None,
        }
        for item in missing_requested_views
    ]


def _missing_requested_views(architecture_spec: ArchitectureSpec, rendered_view_ids: list[str], bundle) -> list[dict[str, Any]]:
    return _view_rendering_ledger(architecture_spec, rendered_view_ids, bundle, "unknown").get("unsupported_not_rendered", [])


def _broader_rendering_for_compiler_view(view_id: str, mappings: list[DiagramViewMapping], rendered: set[str]) -> dict[str, str] | None:
    for mapping in mappings:
        if mapping.compiler_view_id != view_id:
            continue
        broader = _broader_rendering_for_semantic_view(mapping.semantic_view_id, rendered)
        if broader:
            return broader
    return None


def _broader_rendering_for_semantic_view(semantic_view_id: str, rendered: set[str]) -> dict[str, str] | None:
    broader_supported = {
        "rag_ingestion_view": [
            ("data_access_view", "RAG ingestion and indexing are represented in Data Access while runtime retrieval remains a separate RAG Retrieval view."),
            ("production_logical_service_flow", "RAG ingestion is represented in the production service flow; runtime retrieval remains separate when requested."),
        ],
        "telemetry_ingestion_view": [
            ("data_access_view", "Telemetry ingestion is represented in Data Access, including source, buffering, storage, and retention responsibilities."),
            ("production_logical_service_flow", "Telemetry ingestion is represented in the production service flow."),
        ],
        "stream_processing_view": [
            ("data_access_view", "Streaming analytics are represented in Data Access where hot-path processing and downstream storage are shown together."),
            ("production_logical_service_flow", "Streaming analytics are represented in the production service flow."),
        ],
        "approval_workflow_view": [
            ("ai_security_governance_view", "Approval, obligation review, metadata update, and audit controls are represented in the AI Security Governance view."),
            ("agent_tool_execution_view", "Approval and metadata workflow are represented through the Agent Tool Execution view."),
            ("production_logical_service_flow", "Approval workflow is represented in the production service flow."),
        ],
    }
    for compiler_view_id, reason in broader_supported.get(semantic_view_id, []):
        if compiler_view_id in rendered:
            return {"represented_by_view_id": compiler_view_id, "reason": reason}
    return None


def _omitted_view_reasons(bundle) -> dict[str, str]:
    render_plan_path = bundle.artifact_paths.get("render_plan") if hasattr(bundle, "artifact_paths") else None
    if not render_plan_path:
        return {}
    try:
        import json

        payload = json.loads(Path(render_plan_path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {
        str(item.get("view_id")): str(item.get("reason") or "Omitted by compiler")
        for item in payload.get("omitted_views", [])
        if item.get("view_id")
    }


def _icon_embedding_metrics(session_id: str, artifacts: ArtifactStore, diagrams: list[DiagramArtifact]) -> dict[str, dict[str, int | bool]]:
    metrics: dict[str, dict[str, int | bool]] = {}
    for diagram in diagrams:
        d2_ref = diagram.format_paths.get("d2")
        svg_ref = diagram.format_paths.get("svg")
        if not d2_ref or not svg_ref:
            continue
        try:
            d2_text = Path(artifacts.resolve(session_id, d2_ref)).read_text(encoding="utf-8")
            svg_text = Path(artifacts.resolve(session_id, svg_ref)).read_text(encoding="utf-8")
        except Exception:
            continue
        d2_icon_refs = d2_text.count("icon:") + d2_text.count("image:")
        svg_embedded_images = svg_text.count("<image")
        metrics[diagram.view_id] = {
            "d2_icon_references": d2_icon_refs,
            "svg_embedded_image_count": svg_embedded_images,
            "counts_match": d2_icon_refs == svg_embedded_images,
        }
    return metrics


def _icon_embedding_diagnostics(icon_metrics: dict[str, dict[str, int | bool]]) -> list[dict]:
    diagnostics = []
    for view_id, metrics in icon_metrics.items():
        if metrics.get("counts_match") is False:
            diagnostics.append({
                "severity": "warning",
                "code": "icon_embedding_count_mismatch",
                "message": (
                    f"D2 icon/image references ({metrics.get('d2_icon_references')}) do not match "
                    f"SVG embedded image count ({metrics.get('svg_embedded_image_count')}) for {view_id}."
                ),
                "node_id": None,
                "flow_id": None,
            })
    return diagnostics
