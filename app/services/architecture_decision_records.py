"""Deterministic Architecture Decision Records (ADRs) for the export dossier.

ADRs SURFACE decision rationale Archway already computes — catalog alternatives
and purposes, deterministic service rationales, typed governance controls,
pricing evidence classes and driver closure, research-quality labels, and
diagram QA findings. They are export/dossier trust artifacts ONLY:

- No LLM/model output is used anywhere in this module.
- No runtime behavior, pricing, readiness, or architecture decision is altered.
- NO-INVENTION RULES: alternatives come only from the catalog
  (``alternatives_considered`` on selected services); ``chosen_because`` reuses
  existing purpose/rationale text verbatim; trade-off axes stay ``None`` unless
  backed by deterministic data; ``comparison_note`` is attached only when an
  existing research service-validation note mentions the selected service.
- ``confidence`` and ``evidence_class`` are rule-derived; output is sorted and
  deduplicated by ``decision_id`` so identical inputs produce identical bytes.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.dossier_manifest import stable_json_hash

DecisionType = Literal[
    "compute",
    "storage",
    "eventing",
    "ai_rag",
    "integration",
    "network_security",
    "governance_writeback",
    "observability_audit",
    "pricing_readiness",
    "evidence_readiness",
    "diagram_view",
]

EvidenceClass = Literal[
    "catalog_backed",
    "research_backed",
    "pricing_backed",
    "user_confirmed",
    "assumption_backed",
    "missing_evidence",
]

Confidence = Literal["high", "medium", "low", "directional"]
Status = Literal["accepted", "directional", "needs_confirmation", "rejected"]


class TradeoffAxes(BaseModel):
    """Each axis is None unless a deterministic fact backs it. Never synthesized."""

    cost: str | None = None
    reliability: str | None = None
    operational_complexity: str | None = None
    latency: str | None = None
    governance: str | None = None
    security: str | None = None
    scalability: str | None = None


class ArchitectureDecisionRecord(BaseModel):
    decision_id: str
    title: str
    decision_type: DecisionType
    selected_option: str
    alternatives_considered: list[str] = Field(default_factory=list)
    comparison_note: str | None = None
    chosen_because: str
    tradeoffs: TradeoffAxes = Field(default_factory=TradeoffAxes)
    evidence_class: EvidenceClass
    confidence: Confidence
    assumptions: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    reviewer_questions: list[str] = Field(default_factory=list)
    related_components: list[str] = Field(default_factory=list)
    related_flows: list[str] = Field(default_factory=list)
    related_pricing_drivers: list[str] = Field(default_factory=list)
    related_governance_controls: list[str] = Field(default_factory=list)
    source_hashes: dict[str, str] = Field(default_factory=dict)
    status: Status
    generated_by: Literal["deterministic_catalog", "deterministic_rule"] = "deterministic_rule"


# Roles the catalog itself frames as decision points even without alternatives.
DECISION_POINT_ROLES = frozenset({"time_series_store"})

_DECISION_TYPE_KEYWORDS: tuple[tuple[DecisionType, tuple[str, ...]], ...] = (
    ("eventing", ("eventbridge", "sqs", "sns", "kinesis", "msk", "event bus")),
    ("ai_rag", ("sagemaker", "bedrock", "opensearch", "kendra", "comprehend", "textract")),
    ("network_security", ("vpc", "direct connect", "privatelink", "waf", "shield", "cognito", "kms", "iam", "verified permissions")),
    ("observability_audit", ("cloudwatch", "cloudtrail", "x-ray", "audit")),
    ("storage", ("s3", "dynamodb", "aurora", "rds", "timestream", "redshift", "glacier", "efs", "fsx")),
    ("compute", ("ecs", "eks", "ec2", "fargate", "batch")),
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "item"


def _normalize_service(name: str) -> str:
    lowered = name.lower()
    for prefix in ("amazon ", "aws "):
        if lowered.startswith(prefix):
            lowered = lowered[len(prefix):]
    return lowered.strip()


def _decision_type_for(service_name: str) -> DecisionType:
    normalized = _normalize_service(service_name)
    for decision_type, keywords in _DECISION_TYPE_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return decision_type
    return "integration"


def _production_spec(architectures: list | None) -> dict:
    specs = [item for item in (architectures or []) if isinstance(item, dict)]
    for spec in specs:
        if spec.get("mode") == "production":
            return spec
    return specs[0] if specs else {}


def _matched_component_ids(service_name: str, components: list[dict]) -> list[str]:
    """Conservative deterministic matcher: token containment on collapsed names."""
    normalized = re.sub(r"[^a-z0-9]", "", _normalize_service(service_name))
    matched = []
    for component in components:
        comp_service = re.sub(r"[^a-z0-9]", "", str(component.get("service") or "").lower())
        comp_name = re.sub(r"[^a-z0-9]", "", str(component.get("name") or "").lower())
        if comp_service and (comp_service in normalized or normalized in comp_service):
            matched.append(str(component.get("id")))
        elif comp_name and normalized and normalized in comp_name:
            matched.append(str(component.get("id")))
    return sorted(set(matched))


def _validation_note_for(service_name: str, report: dict | None) -> str | None:
    notes = ((report or {}).get("metadata") or {}).get("service_validation_notes") or []
    needle = _normalize_service(service_name)
    last_token = needle.split()[-1] if needle else ""
    for note in notes:
        text = str(note)
        if needle and needle in text.lower():
            return text
        if last_token and re.search(rf"\b{re.escape(last_token)}\b", text, flags=re.I):
            return text
    return None


def _ledger_evidence_class(service_name: str, pricing: dict | None) -> str | None:
    ledger = ((pricing or {}).get("metadata") or {}).get("pricing_ledger") or {}
    normalized = _normalize_service(service_name)
    for line in ledger.get("lines") or []:
        if not isinstance(line, dict):
            continue
        if _normalize_service(str(line.get("service_name") or line.get("service") or "")) == normalized:
            evidence = line.get("evidence_class")
            if evidence:
                return str(evidence)
    return None


def _governed_flow_ids_for(component_ids: list[str], flows: list[dict]) -> list[str]:
    ids = []
    targets = set(component_ids)
    for flow in flows:
        metadata = flow.get("metadata") or {}
        if not metadata.get("approval_required"):
            continue
        if str(flow.get("source")) in targets or str(flow.get("target")) in targets:
            ids.append(str(flow.get("id")))
    return sorted(set(ids))


def _source_hashes(architectures, pricing, report, diagrams) -> dict[str, str]:
    return {
        "architectures": stable_json_hash(architectures or []),
        "pricing": stable_json_hash(pricing or {}),
        "report": stable_json_hash(report or {}),
        "diagrams": stable_json_hash(diagrams or {}),
    }


# --------------------------------------------------------------------------- #
# Emitters
# --------------------------------------------------------------------------- #
def _component_records(spec: dict, pricing: dict | None, report: dict | None, hashes: dict[str, str]) -> list[ArchitectureDecisionRecord]:
    records: list[ArchitectureDecisionRecord] = []
    components = [c for c in (spec.get("components") or []) if isinstance(c, dict)]
    flows = [f for f in (spec.get("flows") or []) if isinstance(f, dict)]
    has_research = bool((report or {}).get("evidence_items"))
    for selection in spec.get("selected_services") or []:
        if not isinstance(selection, dict):
            continue
        service = str(selection.get("service") or "")
        alternatives = [str(a) for a in (selection.get("alternatives_considered") or [])]
        related = _matched_component_ids(service, components)
        decision_point = any(
            (c.get("metadata") or {}).get("role") in DECISION_POINT_ROLES
            for c in components
            if str(c.get("id")) in related
        )
        if not alternatives and not decision_point:
            continue
        # chosen_because: existing purpose + existing deterministic rationale, verbatim.
        purpose = str(selection.get("purpose") or "").strip()
        rationale = str(selection.get("rationale") or "").strip()
        chosen_because = " ".join(part for part in (purpose, rationale) if part)
        governed_flows = _governed_flow_ids_for(related, flows)
        ledger_evidence = _ledger_evidence_class(service, pricing)
        tradeoffs = TradeoffAxes(
            cost=f"pricing evidence class: {ledger_evidence}" if ledger_evidence else None,
            governance=(
                f"participates in {len(governed_flows)} approval-gated flow(s)" if governed_flows else None
            ),
        )
        evidence_class: EvidenceClass = (
            "research_backed" if has_research and selection.get("evidence_ids") else "catalog_backed"
        )
        confidence: Confidence = "high" if evidence_class == "research_backed" else "medium"
        reviewer_questions = []
        if alternatives:
            reviewer_questions.append(
                f"Confirm {service} over the catalog alternatives ({', '.join(alternatives)}) against the customer's constraints."
            )
        records.append(
            ArchitectureDecisionRecord(
                decision_id=f"adr_component_{_slug(service)}",
                title=f"Service selection: {service}",
                decision_type=_decision_type_for(service),
                selected_option=service,
                alternatives_considered=alternatives,
                comparison_note=_validation_note_for(service, report),
                chosen_because=chosen_because,
                tradeoffs=tradeoffs,
                evidence_class=evidence_class,
                confidence=confidence,
                reviewer_questions=reviewer_questions,
                related_components=related,
                related_flows=governed_flows,
                related_governance_controls=[],
                source_hashes=hashes,
                status="accepted" if evidence_class == "research_backed" else "directional",
                generated_by="deterministic_catalog",
            )
        )
    return records


def _governance_records(spec: dict, hashes: dict[str, str]) -> list[ArchitectureDecisionRecord]:
    records: list[ArchitectureDecisionRecord] = []
    flows = [f for f in (spec.get("flows") or []) if isinstance(f, dict)]
    controls = [c for c in (spec.get("governance_controls") or []) if isinstance(c, dict)]
    if controls:
        for control in controls:
            name = str(control.get("name") or control.get("control_type") or "governance control")
            records.append(
                ArchitectureDecisionRecord(
                    decision_id=f"adr_governance_{_slug(str(control.get('id') or name))}",
                    title=f"Governance control: {name}",
                    decision_type="governance_writeback",
                    selected_option=str(control.get("control_type") or name),
                    chosen_because=str(control.get("rationale") or "").strip(),
                    tradeoffs=TradeoffAxes(
                        governance=f"enforcement={control.get('enforcement')}, failure_behavior={control.get('failure_behavior')}"
                    ),
                    evidence_class="catalog_backed",
                    confidence="high",
                    related_flows=sorted(str(i) for i in (control.get("governed_flow_ids") or [])),
                    related_governance_controls=[str(control.get("id"))],
                    source_hashes=hashes,
                    status="accepted",
                )
            )
        return records
    # Fallback: typed effectful-flow metadata without enriched controls.
    by_action: dict[str, list[str]] = {}
    for flow in flows:
        metadata = flow.get("metadata") or {}
        if metadata.get("approval_required") or metadata.get("external_write"):
            action = str(metadata.get("action_type") or "effectful_write")
            by_action.setdefault(action, []).append(str(flow.get("id")))
    for action, flow_ids in sorted(by_action.items()):
        records.append(
            ArchitectureDecisionRecord(
                decision_id=f"adr_governance_{_slug(action)}",
                title=f"Approval-gated action: {action}",
                decision_type="governance_writeback",
                selected_option="approval_gated",
                chosen_because="Typed flow metadata marks this action approval-required before any external effect.",
                tradeoffs=TradeoffAxes(governance=f"{len(flow_ids)} approval-gated flow(s)"),
                evidence_class="catalog_backed",
                confidence="high",
                related_flows=sorted(flow_ids),
                source_hashes=hashes,
                status="accepted",
            )
        )
    return records


def _pricing_readiness_record(pricing: dict | None, hashes: dict[str, str]) -> ArchitectureDecisionRecord | None:
    if not pricing:
        return None
    metadata = pricing.get("metadata") or {}
    headline_safe = metadata.get("pricing_can_be_displayed_as_headline", False) is True
    ledger_summary = (metadata.get("pricing_ledger") or {}).get("summary") or {}
    procurement_ready = bool(ledger_summary.get("procurement_ready", False))
    closure = metadata.get("pricing_driver_closure") or {}
    closure_status = str(closure.get("status") or "unknown")
    missing_drivers = [str(d) for d in (closure.get("missing_drivers") or [])]
    unknowns = [str(u) for u in (pricing.get("unknown_variables") or [])]
    pilot = metadata.get("sku_pricing_pilot") or {}
    pilot_status = str(pilot.get("status") or "absent") if pilot else "absent"
    pilot_ready = bool(pilot.get("sku_pilot_procurement_ready", False)) if pilot else False
    not_estimated = [str(item) for item in (pilot.get("not_estimated") or [])]

    missing_facts = sorted(set(missing_drivers + unknowns))
    directional = (not headline_safe) or (not procurement_ready) or bool(missing_facts)
    return ArchitectureDecisionRecord(
        decision_id="adr_pricing_readiness",
        title="Pricing readiness (global vs SKU pilot)",
        decision_type="pricing_readiness",
        selected_option="directional" if directional else "headline_safe",
        chosen_because=(
            f"Global: headline_safe={headline_safe}, procurement_ready={procurement_ready}, "
            f"driver_closure={closure_status}. SKU pilot: status={pilot_status}, "
            f"sku_pilot_procurement_ready={pilot_ready}. Global readiness and SKU-pilot "
            f"readiness are tracked separately and never promote each other."
        ),
        tradeoffs=TradeoffAxes(
            cost=(
                f"sku_tier_backed_subtotal={ledger_summary.get('sku_tier_backed_subtotal')}, "
                f"heuristic_subtotal={ledger_summary.get('heuristic_subtotal')}"
                if ledger_summary
                else None
            )
        ),
        evidence_class="pricing_backed" if (headline_safe or pilot) else ("missing_evidence" if missing_facts else "assumption_backed"),
        confidence="directional" if directional else "high",
        assumptions=[],
        missing_facts=missing_facts + ([f"not_estimated: {item}" for item in not_estimated]),
        reviewer_questions=(
            [f"Confirm the missing pricing drivers before treating totals as more than directional: {', '.join(missing_facts)}."]
            if missing_facts
            else []
        ),
        related_pricing_drivers=missing_drivers,
        source_hashes=hashes,
        status="directional" if directional else "accepted",
    )


def _evidence_readiness_record(report: dict | None, hashes: dict[str, str]) -> ArchitectureDecisionRecord | None:
    metadata = (report or {}).get("metadata") or {}
    quality = metadata.get("research_quality") or {}
    label = str(quality.get("label") or "")
    coverage = (report or {}).get("citation_coverage") or {}
    coverage_passed = bool(coverage.get("passed", False)) if isinstance(coverage, dict) else False
    if label in {"", "Validated", "Official MCP Evidence"} and coverage_passed:
        return None
    reason = str(quality.get("reason") or "").strip()
    return ArchitectureDecisionRecord(
        decision_id="adr_evidence_readiness",
        title=f"Research evidence readiness: {label or 'unknown'}",
        decision_type="evidence_readiness",
        selected_option=label or "unknown",
        chosen_because=reason or "Citation coverage did not pass; evidence is incomplete.",
        evidence_class="missing_evidence",
        confidence="low",
        missing_facts=([] if coverage_passed else ["citation coverage did not pass"]),
        reviewer_questions=["Enable AWS Docs/Pricing MCP evidence sources before treating research claims as validated."],
        source_hashes=hashes,
        status="needs_confirmation",
    )


def _diagram_readiness_record(diagrams: Any, hashes: dict[str, str]) -> ArchitectureDecisionRecord | None:
    # The export payload is a LIST of gallery dumps; a single gallery dict is
    # also tolerated for direct callers.
    if isinstance(diagrams, dict):
        galleries = [diagrams]
    elif isinstance(diagrams, list):
        galleries = [g for g in diagrams if isinstance(g, dict)]
    else:
        galleries = []
    missing: list[str] = []
    omitted: list[str] = []
    unsupported: list[str] = []
    diagnostics: list[str] = []
    for gallery in galleries:
        missing.extend(str(m) for m in (gallery.get("missing_requested_views") or []))
        ledger = gallery.get("view_rendering_ledger") or {}
        omitted.extend(str(item.get("view_id", item)) for item in (ledger.get("omitted_with_reason") or []))
        unsupported.extend(str(item.get("view_id", item)) for item in (ledger.get("unsupported_not_rendered") or []))
        for qa in gallery.get("qa_reports") or []:
            for diagnostic in (qa.get("diagnostics") or []) if isinstance(qa, dict) else []:
                if isinstance(diagnostic, dict) and diagnostic.get("severity") in {"warning", "error"}:
                    diagnostics.append(str(diagnostic.get("code") or diagnostic.get("message") or "diagnostic"))
    if not (missing or omitted or unsupported or diagnostics):
        return None
    findings = sorted(set(missing + omitted + unsupported + diagnostics))
    return ArchitectureDecisionRecord(
        decision_id="adr_diagram_readiness",
        title="Diagram readiness: degraded or omitted views",
        decision_type="diagram_view",
        selected_option="degraded",
        chosen_because="Diagram QA reported degraded/omitted views or non-info diagnostics; details are preserved verbatim in missing_facts.",
        evidence_class="catalog_backed",
        confidence="directional",
        missing_facts=findings,
        reviewer_questions=["Review the diagram QA diagnostics before customer presentation."],
        source_hashes=hashes,
        status="needs_confirmation",
    )


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def build_decision_records(
    architectures: list | None,
    pricing: dict | None,
    report: dict | None,
    diagrams: Any = None,
) -> list[ArchitectureDecisionRecord]:
    """Deterministically derive ADRs from export-time payloads. Pure function."""
    spec = _production_spec(architectures)
    hashes = _source_hashes(architectures, pricing, report, diagrams)
    records: list[ArchitectureDecisionRecord] = []
    records.extend(_component_records(spec, pricing, report, hashes))
    records.extend(_governance_records(spec, hashes))
    for maybe in (
        _pricing_readiness_record(pricing, hashes),
        _evidence_readiness_record(report, hashes),
        _diagram_readiness_record(diagrams, hashes),
    ):
        if maybe is not None:
            records.append(maybe)
    deduped: dict[str, ArchitectureDecisionRecord] = {}
    for record in records:
        deduped.setdefault(record.decision_id, record)
    return [deduped[key] for key in sorted(deduped)]


def decision_records_summary(records: list[ArchitectureDecisionRecord]) -> dict:
    return {
        "count": len(records),
        "low_confidence_count": sum(1 for r in records if r.confidence == "low"),
        "needs_confirmation_count": sum(1 for r in records if r.status == "needs_confirmation"),
        "directional_count": sum(1 for r in records if r.confidence == "directional" or r.status == "directional"),
    }


def decision_records_markdown(records: list[ArchitectureDecisionRecord]) -> str:
    lines = [
        "# Architecture Decision Records",
        "",
        "Deterministically derived from the catalog, typed governance metadata, pricing",
        "evidence classes, research quality, and diagram QA. No model-generated prose.",
        "",
    ]
    for record in records:
        lines.extend(
            [
                f"## {record.decision_id} — {record.title}",
                "",
                f"- **Type:** {record.decision_type} · **Status:** {record.status} · **Confidence:** {record.confidence} · **Evidence:** {record.evidence_class}",
                f"- **Selected:** {record.selected_option}",
            ]
        )
        if record.alternatives_considered:
            lines.append(f"- **Alternatives considered:** {', '.join(record.alternatives_considered)}")
        if record.chosen_because:
            lines.append(f"- **Chosen because:** {record.chosen_because}")
        if record.comparison_note:
            lines.append(f"- **Comparison note (research):** {record.comparison_note}")
        populated = {axis: value for axis, value in record.tradeoffs.model_dump().items() if value}
        if populated:
            lines.append("- **Trade-offs (deterministic facts only):** " + "; ".join(f"{k}: {v}" for k, v in sorted(populated.items())))
        if record.missing_facts:
            lines.append(f"- **Missing facts:** {'; '.join(record.missing_facts)}")
        if record.reviewer_questions:
            lines.append(f"- **Reviewer questions:** {' '.join(record.reviewer_questions)}")
        lines.append("")
    return "\n".join(lines)
