from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models.domain import ArchitectureSpec, PricingAnalysis
from app.services.llm.base import LLMMessage, LLMTask, LLMTaskType
from app.services.llm.model_router import ModelRouter
from app.services.understanding.deep_use_case_understanding import DeepUseCaseUnderstanding
from app.services.governance_controls import unresolved_effectful_flow_ids


class ArchitectureCritiqueFinding(BaseModel):
    severity: Literal["info", "warning", "critical"]
    category: Literal["classification", "metric_mismatch", "service_fit", "missing_component", "missing_flow", "missing_governance", "pricing_driver_mismatch", "deployment_posture", "latency_mismatch", "diagram_view_gap"]
    issue: str
    why_it_matters: str
    recommended_fix: str
    auto_repairable: bool = False


class ArchitectureCritique(BaseModel):
    passed: bool
    findings: list[ArchitectureCritiqueFinding] = Field(default_factory=list)
    customer_readiness_cap: Literal["customer_ready", "demo_ready_with_caveats", "directional_only", "internal_only"] = "demo_ready_with_caveats"
    enhancement_status: str = "deterministic"


class ArchitectureCritiqueService:
    async def critique(self, raw_use_case: str, understanding: DeepUseCaseUnderstanding, spec: ArchitectureSpec, pricing: PricingAnalysis | None = None, session_id: str | None = None) -> ArchitectureCritique:
        deterministic = deterministic_architecture_critique(raw_use_case, understanding, spec, pricing)
        result = await ModelRouter().complete(
            LLMTask(task_type=LLMTaskType.architecture_critique, session_id=session_id),
            [
                LLMMessage(role="system", content="Critique the AWS architecture against the use case. Return JSON only. Do not invent AWS facts or prices."),
                LLMMessage(role="user", content=f"Use case:\n{raw_use_case}\n\nUnderstanding:\n{understanding.model_dump(mode='json')}\n\nArchitecture:\n{spec.model_dump(mode='json')}\n\nPricing:\n{pricing.model_dump(mode='json') if pricing else {}}"),
            ],
            response_schema=ArchitectureCritique,
            temperature=0.1,
        )
        if result.validated and isinstance(result.parsed, ArchitectureCritique):
            parsed = result.parsed
            deterministic_findings = list(deterministic.findings)
            parsed.findings = deterministic_findings + parsed.findings
            parsed.findings = _drop_satisfied_media_findings(parsed.findings, understanding, spec)
            parsed.findings = _drop_satisfied_governance_findings(parsed.findings, spec)
            parsed.findings = _drop_satisfied_human_approval_findings(parsed.findings, spec)
            parsed.findings = _drop_satisfied_command_center_findings(parsed.findings, spec)
            parsed.findings = _drop_satisfied_healthcare_occupancy_findings(parsed.findings, spec)
            parsed.findings = _drop_satisfied_requirement_coverage_findings(parsed.findings, spec)
            parsed.findings = _downgrade_unconfirmed_model_criticals(parsed.findings, deterministic_findings)
            parsed.passed = not any(item.severity == "critical" for item in parsed.findings)
            if deterministic.customer_readiness_cap == "internal_only":
                parsed.customer_readiness_cap = "internal_only"
            parsed.enhancement_status = f"{result.provider}_validated"
            return parsed
        deterministic.enhancement_status = "deterministic_fallback"
        return deterministic


def deterministic_architecture_critique(raw_use_case: str, understanding: DeepUseCaseUnderstanding, spec: ArchitectureSpec, pricing: PricingAnalysis | None = None) -> ArchitectureCritique:
    findings: list[ArchitectureCritiqueFinding] = []
    services = " ".join(item.service.lower() for item in spec.selected_services)
    component_services = " ".join(component.service.lower() for component in spec.components)
    flow_labels = " ".join(flow.label.lower() for flow in spec.flows)
    families = set(understanding.workload_families)
    if {"capital_markets_risk_engine", "monte_carlo_risk_grid"} & families and not any(token in services for token in ("batch", "parallelcluster", "fsx", "eks", "ec2")):
        findings.append(_finding("warning", "missing_component", "Risk engine architecture lacks explicit risk compute grid/HPC component.", "Monte Carlo VaR and Greeks cadence require compute orchestration beyond a generic API/data pattern.", "Add AWS Batch/EKS/ParallelCluster and high-throughput storage candidates.", True))
    if {"capital_markets_risk_engine", "monte_carlo_risk_grid"} & families and not any(token in component_services for token in ("elasticache", "dynamodb")):
        findings.append(_finding("critical", "latency_mismatch", "Risk engine lacks explicit low-latency portfolio state/cache path.", "Sub-second VaR and Greeks decision paths cannot depend on historical lake scans.", "Add low-latency state and cache components for current positions, Greeks, limits, and VaR results.", True))
    if {"capital_markets_risk_engine", "monte_carlo_risk_grid"} & families and "market" not in flow_labels:
        findings.append(_finding("warning", "missing_flow", "Risk engine lacks explicit market data or exchange ingestion flow.", "Derivatives risk depends on current market context and normalized feed boundaries.", "Add private market data/exchange ingestion and normalization flow.", True))
    if {"telecom_network_analytics", "cdr_congestion_prediction"} & families and "iot core" in services and "kinesis" not in services:
        findings.append(_finding("warning", "service_fit", "Telecom CDR ingestion should justify IoT Core or prefer stream ingestion.", "CDR-scale mediation/event pipelines are usually stream/data pipelines, not MQTT device ingestion unless tower telemetry is explicit.", "Prefer Kinesis/MSK/Data Firehose path or explain IoT telemetry source.", True))
    if understanding.action_flows and not spec.governance_controls:
        findings.append(_finding("critical", "missing_governance", "Action flows lack typed governance controls.", "Effectful actions must be bounded before diagrams/export can be customer-credible.", "Run GovernanceControlEnricher.", True))
    if pricing and pricing.metadata.get("status") in {"invalid_extracted_scale_not_applied", "directional_only_missing_core_compute_drivers"}:
        findings.append(_finding("critical", "pricing_driver_mismatch", "Pricing driver mismatch remains unresolved.", "A credible architecture package cannot headline pricing if explicit metrics were ignored.", "Apply extracted pricing drivers or hide headline estimate.", False))
    cap = "internal_only" if any(item.severity == "critical" for item in findings) else "directional_only" if findings else "demo_ready_with_caveats"
    return ArchitectureCritique(passed=not any(item.severity == "critical" for item in findings), findings=findings, customer_readiness_cap=cap)


def _finding(severity: str, category: str, issue: str, why: str, fix: str, repairable: bool) -> ArchitectureCritiqueFinding:
    return ArchitectureCritiqueFinding(severity=severity, category=category, issue=issue, why_it_matters=why, recommended_fix=fix, auto_repairable=repairable)


def _downgrade_unconfirmed_model_criticals(findings: list[ArchitectureCritiqueFinding], deterministic_findings: list[ArchitectureCritiqueFinding]) -> list[ArchitectureCritiqueFinding]:
    """Keep model critique audit-useful without letting it seize compiler authority.

    Deterministic findings are still allowed to block. Critical findings emitted
    only by a model are downgraded to warnings unless a deterministic critique
    produced the same critical category+issue. This prevents stale/overbroad live
    critiques from forcing diagnostic-only output when the pattern catalog and
    validators already carry the required component/flow coverage.
    """
    deterministic_critical_keys = {
        _finding_key(item)
        for item in deterministic_findings
        if item.severity == "critical"
    }
    output: list[ArchitectureCritiqueFinding] = []
    for item in findings:
        if item.severity == "critical" and _finding_key(item) not in deterministic_critical_keys:
            output.append(item.model_copy(update={
                "severity": "warning",
                "why_it_matters": (
                    f"{item.why_it_matters} This live-model critique is audit-only unless deterministic "
                    "validation confirms the same blocker."
                ),
            }))
            continue
        output.append(item)
    return output


def _finding_key(item: ArchitectureCritiqueFinding) -> tuple[str, str]:
    return (item.category, item.issue.strip().lower())


def _drop_satisfied_media_findings(findings: list[ArchitectureCritiqueFinding], understanding: DeepUseCaseUnderstanding, spec: ArchitectureSpec) -> list[ArchitectureCritiqueFinding]:
    if "live_streaming" not in set(understanding.workload_families):
        return findings
    architecture_text = " ".join([
        *(item.name for item in spec.components),
        *(item.service for item in spec.components),
        *(item.label or "" for item in spec.flows),
        *(item.purpose for item in spec.selected_services),
    ]).lower()
    satisfied_terms = {
        "drm": ("drm", "license", "key"),
        "consent": ("consent", "privacy"),
        "geo": ("geo-rights", "blackout", "entitlement"),
        "qoe": ("qoe", "startup", "rebuffering", "latency"),
    }
    output: list[ArchitectureCritiqueFinding] = []
    for item in findings:
        haystack = " ".join([item.issue, item.why_it_matters, item.recommended_fix]).lower()
        satisfied = False
        for marker, required_terms in satisfied_terms.items():
            if marker in haystack and any(term in architecture_text for term in required_terms):
                satisfied = True
                break
        if not satisfied:
            output.append(item)
    return output


def _drop_satisfied_governance_findings(findings: list[ArchitectureCritiqueFinding], spec: ArchitectureSpec) -> list[ArchitectureCritiqueFinding]:
    if unresolved_effectful_flow_ids(spec):
        return findings
    if not spec.governance_controls:
        return findings
    return [
        item
        for item in findings
        if item.category != "missing_governance"
    ]


def _drop_satisfied_human_approval_findings(findings: list[ArchitectureCritiqueFinding], spec: ArchitectureSpec) -> list[ArchitectureCritiqueFinding]:
    has_human_approval_flow = any(
        str(flow.metadata.get("classification") or "").lower() == "human_approval"
        or bool(flow.metadata.get("approval_required"))
        for flow in spec.flows
    )
    has_human_approval_component = any(
        "human approval" in component.name.lower()
        or component.metadata.get("role") in {"human_approval_workflow", "clinical_approval_workflow"}
        for component in spec.components
    )
    has_human_approval_control = any(control.control_type == "human_approval" for control in spec.governance_controls)
    if not (has_human_approval_flow and has_human_approval_component and has_human_approval_control):
        return findings
    output = []
    for item in findings:
        text = " ".join([item.category, item.issue, item.why_it_matters, item.recommended_fix]).lower()
        if item.category in {"missing_component", "missing_flow"} and "approval" in text:
            continue
        output.append(item)
    return output


def _drop_satisfied_command_center_findings(findings: list[ArchitectureCritiqueFinding], spec: ArchitectureSpec) -> list[ArchitectureCritiqueFinding]:
    has_command_center = any("command center" in component.name.lower() for component in spec.components)
    has_command_center_flow = any(flow.source == "command_center" or flow.target == "command_center" for flow in spec.flows)
    if not (has_command_center and has_command_center_flow):
        return findings
    output = []
    for item in findings:
        text = " ".join([item.category, item.issue, item.why_it_matters, item.recommended_fix]).lower()
        if item.category in {"missing_component", "missing_flow"} and "command center" in text:
            continue
        output.append(item)
    return output


def _drop_satisfied_healthcare_occupancy_findings(findings: list[ArchitectureCritiqueFinding], spec: ArchitectureSpec) -> list[ArchitectureCritiqueFinding]:
    families = set((spec.metadata or {}).get("workload_families") or [])
    if "healthcare_operations_scheduling" not in families:
        return findings
    has_occupancy_to_events = any(flow.source == "occupancy_metadata" and flow.target == "events" for flow in spec.flows)
    has_external_feed_path = all(any(flow.source == source and flow.target == "private_connectivity" for flow in spec.flows) for source in ("ehr", "staffing", "sterile_processing"))
    has_private_to_adapter = any(flow.source == "private_connectivity" and flow.target == "adapter" for flow in spec.flows)
    if not has_occupancy_to_events:
        return findings
    output = []
    for item in findings:
        text = " ".join([item.category, item.issue, item.why_it_matters, item.recommended_fix]).lower()
        if item.category == "missing_flow" and "occupancy" in text and ("event router" in text or "schedule event router" in text):
            continue
        if item.category == "missing_flow" and "occupancy" in text and "external systems" in text and has_external_feed_path and has_private_to_adapter:
            continue
        output.append(item)
    return output


_REQUIREMENT_COVERAGE_TERMS = {
    "computer_vision_hot_path": ("image", "imagery", "photo", "video", "vision", "camera", "scan", "ocr"),
    "document_processing_path": ("document", "text", "note", "pdf", "contract", "record", "ocr", "extraction"),
    "intermittent_connectivity": ("offline", "intermittent", "connectivity", "sync", "edge", "store-and-forward"),
    "governed_action_path": ("approval", "human", "review", "governed", "workflow", "action"),
    "data_residency_boundary": ("residency", "sovereign", "region", "country", "jurisdiction", "boundary"),
}


def _drop_satisfied_requirement_coverage_findings(findings: list[ArchitectureCritiqueFinding], spec: ArchitectureSpec) -> list[ArchitectureCritiqueFinding]:
    coverage = ((spec.metadata or {}).get("requirement_coverage") or {}).get("requirements") or []
    covered = {
        str(item.get("id") or "")
        for item in coverage
        if isinstance(item, dict) and str(item.get("status") or "").lower() == "covered"
    }
    if not covered:
        return findings
    output: list[ArchitectureCritiqueFinding] = []
    for item in findings:
        if item.category not in {"missing_component", "missing_flow"}:
            output.append(item)
            continue
        text = " ".join([item.issue, item.why_it_matters, item.recommended_fix]).lower()
        if any(requirement_id in covered and any(term in text for term in terms) for requirement_id, terms in _REQUIREMENT_COVERAGE_TERMS.items()):
            continue
        output.append(item)
    return output
