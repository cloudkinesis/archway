"""Flow preservation ledger."""

from typing import Dict, Iterable, List, Optional, Set

from archway_diagram_compiler.flow_classifier import classify_flow
from archway_diagram_compiler.models import (
    Diagnostic,
    Flow,
    FlowLedger,
    FlowLedgerEntry,
    SemanticArchitectureSpec,
)
from archway_diagram_compiler.providers import get_provider_catalog


def build_initial_flow_ledger(spec: SemanticArchitectureSpec) -> FlowLedger:
    nodes_by_id = {node.id: node for node in spec.nodes}
    entries: List[FlowLedgerEntry] = []
    for flow in spec.flows:
        source = nodes_by_id.get(flow.source)
        target = nodes_by_id.get(flow.target)
        if source is None or target is None:
            continue
        provider = get_provider_catalog(source.provider)
        classification = classify_flow(flow, source, target, provider)
        entries.append(
            FlowLedgerEntry(
                flow_id=flow.id,
                source=flow.source,
                target=flow.target,
                label=flow.label,
                classification=classification.edge_type,
                status="omitted_with_reason",
                reason="Flow has not been assigned to a view yet.",
            )
        )
    return FlowLedger(entries=sorted(entries, key=lambda item: item.flow_id))


def update_ledger_for_views(
    ledger: FlowLedger,
    view_flows: Dict[str, Iterable[Flow]],
    collapsed: Optional[Dict[str, str]] = None,
    omitted: Optional[Dict[str, str]] = None,
) -> FlowLedger:
    collapsed = collapsed or {}
    omitted = omitted or {}
    known_flow_ids = {entry.flow_id for entry in ledger.entries}
    rendered_by_flow: Dict[str, str] = {}
    collapsed_by_flow: Dict[str, Dict[str, str]] = {}
    classification_by_flow = {entry.flow_id: entry.classification for entry in ledger.entries}
    for view_id, flows in view_flows.items():
        for flow in flows:
            if flow.metadata.get("homogeneous_fanout_group"):
                group_id = str(flow.metadata.get("group_id") or flow.target)
                reason = str(flow.metadata.get("collapse_reason") or "homogeneous fan-out summarized to reduce crossings")
                for source_flow_id in _source_flow_ids(flow, known_flow_ids):
                    existing = collapsed_by_flow.get(source_flow_id)
                    candidate = {"group_id": group_id, "reason": reason, "view_id": view_id}
                    if existing is None or _view_priority(view_id, classification_by_flow.get(source_flow_id)) < _view_priority(existing.get("view_id"), classification_by_flow.get(source_flow_id)):
                        collapsed_by_flow[source_flow_id] = candidate
                continue
            for source_flow_id in _source_flow_ids(flow, known_flow_ids):
                existing_view = rendered_by_flow.get(source_flow_id)
                if existing_view is None or _view_priority(view_id, classification_by_flow.get(source_flow_id)) < _view_priority(existing_view, classification_by_flow.get(source_flow_id)):
                    rendered_by_flow[source_flow_id] = view_id

    updated: List[FlowLedgerEntry] = []
    for entry in ledger.entries:
        if entry.flow_id in collapsed_by_flow:
            collapse = collapsed_by_flow[entry.flow_id]
            updated.append(
                _copy_entry(
                    entry,
                    {
                        "status": "collapsed_into_group",
                        "view_id": collapse.get("view_id") or "production_logical_service_flow",
                        "group_id": collapse["group_id"],
                        "reason": collapse["reason"],
                    },
                )
            )
        elif entry.flow_id in rendered_by_flow:
            rendered_view = rendered_by_flow[entry.flow_id]
            status = "rendered_in_another_view" if _is_specialized_view(rendered_view) else "rendered_explicitly"
            updated.append(_copy_entry(entry, {"status": status, "view_id": rendered_view, "reason": None}))
        elif entry.flow_id in collapsed:
            updated.append(_copy_entry(entry, {"status": "collapsed_into_group", "group_id": collapsed[entry.flow_id], "reason": "Flow collapsed into a semantic group."}))
        elif entry.flow_id in omitted:
            updated.append(_copy_entry(entry, {"status": "omitted_with_reason", "reason": omitted[entry.flow_id]}))
        else:
            updated.append(
                _copy_entry(
                    entry,
                    {
                        "status": "omitted_with_reason",
                        "reason": "Flow is preserved for secondary view planning and was not selected for the generated default views.",
                    },
                )
            )
    return FlowLedger(entries=updated)


def validate_flow_ledger(spec: SemanticArchitectureSpec, ledger: FlowLedger) -> List[Diagnostic]:
    diagnostics: List[Diagnostic] = []
    input_flow_ids: Set[str] = {flow.id for flow in spec.flows}
    ledger_flow_ids = {entry.flow_id for entry in ledger.entries}
    for flow_id in sorted(input_flow_ids - ledger_flow_ids):
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="flow_ledger_missing_entry",
                message="Input flow has no FlowLedger entry.",
                flow_id=flow_id,
            )
        )
    for entry in ledger.entries:
        if entry.flow_id in input_flow_ids and entry.status == "omitted_with_reason" and not entry.reason:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="flow_ledger_missing_omission_reason",
                    message="Omitted flow must include an explanation.",
                    flow_id=entry.flow_id,
                )
            )
        if entry.status == "collapsed_into_group" and not (entry.group_id or entry.reason):
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="flow_ledger_missing_collapse_reason",
                    message="Collapsed flow must include a group or explanation.",
                    flow_id=entry.flow_id,
                )
            )
    return diagnostics


def _source_flow_ids(flow: Flow, known_flow_ids: Optional[Set[str]] = None) -> List[str]:
    known_flow_ids = known_flow_ids or set()
    source_ids = flow.metadata.get("source_flow_ids")
    if isinstance(source_ids, list):
        exact = [str(item) for item in source_ids if str(item) in known_flow_ids]
        return exact or [str(item) for item in source_ids]
    source_id = flow.metadata.get("source_flow_id")
    if source_id:
        return [str(source_id)] if str(source_id) in known_flow_ids else [flow.id]
    if flow.id in known_flow_ids:
        return [flow.id]
    if flow.id.endswith("_logical"):
        return [flow.id[: -len("_logical")]]
    for suffix in ("_endpoint", "_service", "_vpc_link", "_lb", "_workload"):
        if flow.id.endswith(suffix):
            return [flow.id[: -len(suffix)]]
    return [flow.id]


def _copy_entry(entry: FlowLedgerEntry, update: dict) -> FlowLedgerEntry:
    if hasattr(entry, "model_copy"):
        return entry.model_copy(update=update)
    return entry.copy(update=update)


def _view_priority(view_id: Optional[str], classification: Optional[str]) -> int:
    if view_id is None:
        return 999
    preferred = {
        "rag_retrieval": ["rag_retrieval_view", "ai_logical_service_flow", "production_logical_service_flow"],
        "vector_search": ["rag_retrieval_view", "ai_logical_service_flow", "production_logical_service_flow"],
        "hybrid_search": ["rag_retrieval_view", "ai_logical_service_flow", "production_logical_service_flow"],
        "source_reference": ["rag_retrieval_view", "ai_logical_service_flow", "production_logical_service_flow"],
        "document_ingestion": ["rag_ingestion_view", "ai_logical_service_flow", "production_logical_service_flow"],
        "document_chunking": ["rag_ingestion_view", "ai_logical_service_flow", "production_logical_service_flow"],
        "document_embedding": ["rag_ingestion_view", "ai_logical_service_flow", "production_logical_service_flow"],
        "embedding_generation": ["rag_ingestion_view", "ai_logical_service_flow", "production_logical_service_flow"],
        "tool_invocation": ["production_logical_service_flow", "agent_tool_execution_view", "ai_logical_service_flow", "fanout_detail_view"],
        "agent_orchestration": ["agent_tool_execution_view", "ai_logical_service_flow", "production_logical_service_flow"],
        "agent_handoff": ["agent_tool_execution_view", "ai_logical_service_flow", "production_logical_service_flow"],
        "memory_read": ["agent_memory_view", "ai_logical_service_flow", "production_logical_service_flow"],
        "memory_write": ["agent_memory_view", "ai_logical_service_flow", "production_logical_service_flow"],
        "prompt_lookup": ["agent_memory_view", "ai_logical_service_flow", "production_logical_service_flow"],
        "guardrail_check": ["ai_security_governance_view", "ai_logical_service_flow", "production_logical_service_flow"],
        "evaluation": ["ai_security_governance_view", "ai_logical_service_flow", "production_logical_service_flow"],
        "human_approval": ["ai_security_governance_view", "ai_logical_service_flow", "production_logical_service_flow"],
        "audit_trace": ["ai_security_governance_view", "ai_logical_service_flow", "production_logical_service_flow"],
        "model_observability": ["ai_security_governance_view", "ai_logical_service_flow", "production_logical_service_flow"],
        "model_invocation": ["ai_logical_service_flow", "rag_retrieval_view", "production_logical_service_flow"],
        "media_delivery": ["live_media_delivery_view", "production_logical_service_flow"],
        "media_rights": ["media_rights_ad_decisioning_view", "security_observability_controls", "production_logical_service_flow"],
        "media_ad_decision": ["media_rights_ad_decisioning_view", "production_logical_service_flow"],
        "media_qoe": ["media_qoe_analytics_view", "security_observability_controls", "production_logical_service_flow"],
    }
    ordered = preferred.get(str(classification), ["production_logical_service_flow"])
    if view_id in ordered:
        return ordered.index(view_id)
    if view_id == "production_logical_service_flow":
        return 50
    return 20


def _is_specialized_view(view_id: Optional[str]) -> bool:
    return view_id in {
        "rag_retrieval_view",
        "rag_ingestion_view",
        "agent_tool_execution_view",
        "agent_memory_view",
        "ai_security_governance_view",
        "live_media_delivery_view",
        "media_rights_ad_decisioning_view",
        "media_qoe_analytics_view",
    }
