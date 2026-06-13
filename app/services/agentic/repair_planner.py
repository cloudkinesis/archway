from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.services.agentic.contracts import (
    AGENTIC_LANES,
    AgentFinding,
    AgentRepairAction,
    AgentRepairPlan,
    AgentRun,
    AgentTask,
    ArtifactCompletenessState,
)
from app.services.dossier_manifest import stable_json_hash
from app.services.customer_readiness import compute_readiness_tier


def agentic_feature_flags(settings: Settings) -> dict[str, bool]:
    return {
        "enable_agentic_repair_planner": settings.enable_agentic_repair_planner,
        "enable_agentic_research": settings.enable_agentic_research,
        "enable_agentic_use_case_analyst": settings.enable_agentic_use_case_analyst,
        "enable_agentic_pricing": settings.enable_agentic_pricing,
        "enable_agentic_narrative": settings.enable_agentic_narrative,
        "enable_agentic_reviewer": settings.enable_agentic_reviewer,
        "enable_agentic_diagram_planner": settings.enable_agentic_diagram_planner,
        "enable_agentic_architecture": settings.enable_agentic_architecture,
    }


def enabled_lanes_from_settings(settings: Settings) -> list[str]:
    flags = agentic_feature_flags(settings)
    mapping = {
        "repair_planner": "enable_agentic_repair_planner",
        "research": "enable_agentic_research",
        "use_case_analyst": "enable_agentic_use_case_analyst",
        "pricing_dimension": "enable_agentic_pricing",
        "pricing": "enable_agentic_pricing",
        "narrative": "enable_agentic_narrative",
        "reviewer": "enable_agentic_reviewer",
        "diagram_planner": "enable_agentic_diagram_planner",
        "architecture": "enable_agentic_architecture",
    }
    return [lane for lane, key in mapping.items() if flags[key]]


class DeterministicRepairPlanner:
    """D21 Phase-0 repair planner.

    This planner reads existing readiness, pricing, evidence, diagram, linter,
    and reviewer signals. It does not call a model, call the network, or mutate
    pricing/readiness/compiler state.
    """

    def plan(
        self,
        *,
        report: dict | None,
        pricing: dict | None,
        architectures: list | None,
        diagrams: list | None,
        diagram_fidelity: dict | None = None,
        artifact_linter_findings: list | None = None,
        reviewer_findings: list | None = None,
    ) -> ArtifactCompletenessState:
        tier = compute_readiness_tier(report=report, pricing=pricing, architectures=architectures)
        actions: list[AgentRepairAction] = []
        source_signals: list[str] = []

        for idx, reason in enumerate(tier.get("reasons") or [], start=1):
            actions.append(_action(f"readiness_{idx}", f"Resolve readiness gate: {reason}", "customer_readiness.reasons"))
            source_signals.append("customer_readiness.reasons")

        closure = ((pricing or {}).get("metadata") or {}).get("pricing_driver_closure") or {}
        for driver in closure.get("missing_drivers") or []:
            name = _driver_name(driver)
            actions.append(_action(f"pricing_missing_{_slug(name)}", f"Confirm missing pricing driver: {name}", "pricing_driver_closure.missing_drivers", "03-pricing.md"))
            source_signals.append("pricing_driver_closure.missing_drivers")
        for driver in closure.get("assumed_drivers") or []:
            name = str(driver)
            actions.append(_action(f"pricing_assumed_{_slug(name)}", f"Validate assumed pricing driver: {name}", "pricing_driver_closure.assumed_drivers", "03-pricing.md"))
            source_signals.append("pricing_driver_closure.assumed_drivers")

        evidence_quality = (((report or {}).get("metadata") or {}).get("evidence_quality") or {})
        if not (evidence_quality.get("aws_docs_available") or evidence_quality.get("aws_pricing_available")):
            actions.append(_action("evidence_authority", "Refresh authoritative AWS Docs/Pricing evidence for package claims.", "research.evidence_quality", "06-evidence-appendix.md"))
            source_signals.append("research.evidence_quality")
        coverage = (((report or {}).get("metadata") or {}).get("citation_coverage") or {})
        if coverage and coverage.get("passed") is False:
            actions.append(_action("citation_coverage", "Resolve uncited or weakly cited dossier claims.", "research.citation_coverage", "02C-claim-register.md"))
            source_signals.append("research.citation_coverage")

        for idx, fallback in enumerate(_diagram_fallbacks(diagrams, diagram_fidelity), start=1):
            actions.append(_action(f"diagram_fallback_{idx}", f"Review diagram fallback: {fallback}", "diagram_fidelity.view_rendering_ledger", "05-diagrams.md"))
            source_signals.append("diagram_fidelity.view_rendering_ledger")

        for idx, finding in enumerate(artifact_linter_findings or [], start=1):
            message = _finding_message(finding)
            if message:
                actions.append(_action(f"artifact_lint_{idx}", f"Resolve artifact polish finding: {message}", "artifact_linter.findings"))
                source_signals.append("artifact_linter.findings")

        for idx, finding in enumerate(reviewer_findings or [], start=1):
            message = _finding_message(finding)
            if message:
                actions.append(_action(f"reviewer_{idx}", f"Review deterministic reviewer finding: {message}", "reviewer.findings"))
                source_signals.append("reviewer.findings")

        plan = AgentRepairPlan(
            tier_from=tier.get("tier"),
            tier_to=_next_tier(tier.get("tier")),
            actions=_dedupe_actions(actions),
            source_signals=sorted(set(source_signals)),
        )
        return ArtifactCompletenessState(
            outcome=_outcome(tier.get("tier"), plan.actions),
            missing_evidence=[] if evidence_quality.get("aws_docs_available") or evidence_quality.get("aws_pricing_available") else ["authoritative AWS evidence"],
            missing_pricing_drivers=[a.action for a in plan.actions if a.source_signal == "pricing_driver_closure.missing_drivers"],
            diagram_fallbacks=[a.action for a in plan.actions if a.source_signal == "diagram_fidelity.view_rendering_ledger"],
            readiness_reasons=list(tier.get("reasons") or []),
            repair_plan=plan,
        )


def build_agentic_trace(
    *,
    settings: Settings,
    report: dict | None,
    pricing: dict | None,
    architectures: list | None,
    diagrams: list | None,
    diagram_fidelity: dict | None = None,
    artifact_linter_findings: list | None = None,
    reviewer_findings: list | None = None,
) -> dict[str, Any]:
    state = DeterministicRepairPlanner().plan(
        report=report,
        pricing=pricing,
        architectures=architectures,
        diagrams=diagrams,
        diagram_fidelity=diagram_fidelity,
        artifact_linter_findings=artifact_linter_findings,
        reviewer_findings=reviewer_findings,
    )
    enabled_lanes = enabled_lanes_from_settings(settings)
    input_hash = stable_json_hash({
        "readiness_reasons": state.readiness_reasons,
        "missing_pricing_drivers": state.missing_pricing_drivers,
        "diagram_fallbacks": state.diagram_fallbacks,
        "enabled_lanes": enabled_lanes,
    })
    run = AgentRun(
        run_id="agent_run_" + input_hash.removeprefix("sha256:")[:12],
        enabled_lanes=enabled_lanes,
        model_provider=settings.llm_provider,
        input_hash=input_hash,
        tasks=[
            AgentTask(
                task_id=f"task_{lane}",
                lane=lane,
                purpose=_lane_purpose(lane),
                input_refs=["deterministic_export_payload"],
                status="skipped" if lane not in enabled_lanes else ("accepted" if lane == "repair_planner" else "skipped"),
            )
            for lane in AGENTIC_LANES
        ],
        findings=[
            AgentFinding(
                lane="repair_planner",
                severity="advisory",
                rule_id="d21.phase0.raw_audit_only",
                message="D21 Phase 0 writes deterministic repair guidance to raw/audit traces only.",
                target_artifact="raw/agent_repair_plan.json",
            )
        ],
    )
    return {
        "agent_runs": [run.model_dump(mode="json")],
        "agent_proposals": [],
        "agent_repair_plan": state.model_dump(mode="json"),
        "authority_matrix": authority_matrix(settings),
    }


def authority_matrix(settings: Settings) -> list[dict[str, Any]]:
    enabled = set(enabled_lanes_from_settings(settings))
    rows = [
        ("deterministic_baseline", True, True, True, True, True, True),
        ("repair_planner", True, True, True, False, False, False),
        ("research", True, True, True, False, False, False),
        ("pricing_dimension", True, True, True, False, False, False),
        ("pricing", True, True, True, False, False, False),
        ("narrative", True, True, True, False, False, False),
        ("reviewer", True, True, True, False, False, False),
        ("architecture", True, True, True, False, False, False),
    ]
    return [
        {
            "component": component,
            "can_propose": can_propose,
            "can_write_raw_traces": raw,
            "can_write_audit_pack": audit,
            "can_write_client_pack": False if component != "deterministic_baseline" else True,
            "can_affect_readiness": readiness if component == "deterministic_baseline" else False,
            "can_affect_pricing_math": pricing if component == "deterministic_baseline" else False,
            "can_affect_diagram_compiler_output": diagram if component == "deterministic_baseline" else False,
            "default_enabled": component == "deterministic_baseline" or component in enabled,
        }
        for component, can_propose, raw, audit, readiness, pricing, diagram in rows
    ]


def repair_plan_markdown(state: ArtifactCompletenessState, matrix: list[dict[str, Any]]) -> str:
    lines = [
        "# D21 Agentic Repair Plan",
        "",
        "This Phase-0 artifact is deterministic. It uses existing readiness, pricing, evidence, diagram, linter, and reviewer signals only.",
        "",
        f"**Outcome:** {state.outcome}",
        f"**Current tier:** {state.repair_plan.tier_from or 'unknown'}",
        f"**Next tier:** {state.repair_plan.tier_to or 'none'}",
        "",
        "## Repair Actions",
        "",
    ]
    if state.repair_plan.actions:
        lines.extend(f"- {item.action} (`{item.source_signal}`)" for item in state.repair_plan.actions)
    else:
        lines.append("- No deterministic repair actions were identified.")
    lines.extend(["", "## Authority Matrix", ""])
    header = "| Component | Propose | Raw | Audit | Client | Readiness | Pricing Math | Diagram Truth | Default Enabled |"
    lines.extend([header, "|---|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for row in matrix:
        lines.append(
            f"| {row['component']} | {_yes(row['can_propose'])} | {_yes(row['can_write_raw_traces'])} | "
            f"{_yes(row['can_write_audit_pack'])} | {_yes(row['can_write_client_pack'])} | "
            f"{_yes(row['can_affect_readiness'])} | {_yes(row['can_affect_pricing_math'])} | "
            f"{_yes(row['can_affect_diagram_compiler_output'])} | {_yes(row['default_enabled'])} |"
        )
    lines.extend(["", "D21 Phase 0 does not invoke an LLM, call the network, or promote any model-proposed claim.", ""])
    return "\n".join(lines)


def _action(action_id: str, action: str, source_signal: str, target_artifact: str | None = None) -> AgentRepairAction:
    return AgentRepairAction(action_id=action_id, action=action, source_signal=source_signal, target_artifact=target_artifact)


def _diagram_fallbacks(diagrams: list | None, diagram_fidelity: dict | None) -> list[str]:
    out: list[str] = []
    for issue in (diagram_fidelity or {}).get("missing_requested_views") or []:
        if isinstance(issue, dict):
            out.append(f"{issue.get('mode') or 'architecture'} view {issue.get('view_id') or 'unknown'}: {issue.get('reason') or 'not rendered'}")
        else:
            out.append(str(issue))
    for gallery in diagrams or []:
        for diagram in gallery.get("diagrams", []) if isinstance(gallery, dict) else []:
            reason = diagram.get("fallback_reason")
            if reason:
                out.append(f"{diagram.get('view_id') or diagram.get('title') or 'diagram'}: {reason}")
    return sorted(set(out))


def _finding_message(finding: Any) -> str | None:
    if isinstance(finding, dict):
        return finding.get("message") or finding.get("summary") or finding.get("code")
    return getattr(finding, "message", None) or getattr(finding, "summary", None) or str(finding)


def _driver_name(driver: Any) -> str:
    if isinstance(driver, dict):
        return str(driver.get("name") or driver.get("driver_name") or driver.get("id") or driver)
    return str(driver)


def _dedupe_actions(actions: list[AgentRepairAction]) -> list[AgentRepairAction]:
    seen: set[tuple[str, str]] = set()
    out: list[AgentRepairAction] = []
    for action in actions:
        key = (action.action, action.source_signal)
        if key in seen:
            continue
        seen.add(key)
        out.append(action)
    return out


def _next_tier(tier: str | None) -> str | None:
    order = ["internal_only", "demo_ready", "workshop_ready", "procurement_ready"]
    if tier not in order:
        return None
    idx = order.index(tier)
    return order[idx + 1] if idx + 1 < len(order) else None


def _outcome(tier: str | None, actions: list[AgentRepairAction]) -> str:
    if tier in {"workshop_ready", "procurement_ready"} and not actions:
        return "solution_package"
    if tier in {"internal_only", None}:
        return "unsupported_refusal_package"
    return "directional_diagnostic_package"


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")[:48] or "unknown"


def _lane_purpose(lane: str) -> str:
    return {
        "repair_planner": "Generate deterministic next actions from existing package signals.",
        "research": "Future lane: propose cited research findings after evaluation gates exist.",
        "use_case_analyst": "Future lane: propose missing facts and scenario profile candidates.",
        "pricing_dimension": "Future lane: propose service usage dimensions and pricing-driver questions.",
        "pricing": "Future lane: propose service usage dimensions and pricing-driver questions.",
        "narrative": "Audit-only lane: propose evidence-bound narrative polish after validation.",
        "reviewer": "Audit-only lane: add reviewer critiques without removing deterministic findings.",
        "diagram_planner": "Audit-only lane: propose semantic view plans without changing compiler truth.",
        "architecture": "Future lane: propose architecture candidates under human/pattern authority.",
    }.get(lane, "D21 lane")


def _yes(value: bool) -> str:
    return "yes" if value else "no"
