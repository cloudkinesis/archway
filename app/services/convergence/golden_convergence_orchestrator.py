from __future__ import annotations

from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.quality_findings import QualityFinding, finding
from app.models.domain import ArchitectureSpec, utc_now
from app.services.architecture_critique import ArchitectureCritiqueService
from app.services.architecture_revisions import ArchitectureRevisionService
from app.services.artifacts import ArtifactStore
from app.services.convergence.architecture_repairer import ArchitectureRepairer
from app.services.convergence.repair_planner import RepairPlan, RepairPlanner
from app.services.pricing_sanity_reviewer import PricingSanityReview
from app.services.understanding.deep_use_case_understanding import DeepUseCaseUnderstanding, deterministic_understanding


FinalStatus = Literal["golden_candidate", "customer_demo_ready_with_caveats", "directional_only", "internal_only", "failed_validation"]


class ConvergenceIteration(BaseModel):
    iteration_number: int
    stage: str
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    findings_before: list[QualityFinding] = Field(default_factory=list)
    repair_plan: RepairPlan | None = None
    findings_after: list[QualityFinding] = Field(default_factory=list)
    status: Literal["passed", "repaired", "warnings", "failed"]


class GoldenConvergenceResult(BaseModel):
    session_id: str
    final_status: FinalStatus
    workflow_status: str
    customer_readiness: str
    iterations: list[ConvergenceIteration] = Field(default_factory=list)
    unresolved_findings: list[QualityFinding] = Field(default_factory=list)
    repaired_findings: list[QualityFinding] = Field(default_factory=list)
    generated_artifacts: list[str] = Field(default_factory=list)


class GoldenConvergenceOrchestrator:
    max_repair_iterations = 2

    def __init__(self):
        self.artifacts = ArtifactStore()
        self.revisions = ArchitectureRevisionService()
        self.repairer = ArchitectureRepairer()
        self.planner = RepairPlanner()

    async def run(
        self,
        session_id: str,
        use_case: str,
        synthesis_answers: list[Any] | None = None,
        mode: Literal["quick", "standard", "deep_dossier"] = "deep_dossier",
    ) -> GoldenConvergenceResult:
        root = self.artifacts.ensure_layout(session_id)
        context = _load_context(root)
        findings = await self._collect_findings(session_id, use_case, context)
        iterations: list[ConvergenceIteration] = []
        repaired_findings: list[QualityFinding] = []

        for index in range(1, self.max_repair_iterations + 1):
            repairable = [item for item in findings if item.severity in {"critical", "blocker"} and item.auto_repairable and not item.repaired]
            if not repairable:
                break
            started = utc_now()
            tick = perf_counter()
            plan = self.planner.plan(repairable)
            if not plan.actions or not plan.can_auto_apply:
                iterations.append(ConvergenceIteration(
                    iteration_number=index,
                    stage="repair",
                    started_at=started,
                    completed_at=utc_now(),
                    duration_ms=int((perf_counter() - tick) * 1000),
                    findings_before=repairable,
                    repair_plan=plan,
                    findings_after=repairable,
                    status="failed",
                ))
                break
            before_ids = {item.id for item in repairable}
            notes = self._apply_repairs(session_id, root, context, findings)
            plan.repairs_applied = len(notes)
            for item in findings:
                if item.id in before_ids:
                    item.repaired = True
                    item.repair_notes = "; ".join(notes) or "Repair plan applied."
            repaired_findings.extend([item for item in findings if item.id in before_ids])
            context = _load_context(root)
            findings_after = await self._collect_findings(session_id, use_case, context)
            findings = _merge_repaired_state(findings_after, repaired_findings)
            iterations.append(ConvergenceIteration(
                iteration_number=index,
                stage="repair",
                started_at=started,
                completed_at=utc_now(),
                duration_ms=int((perf_counter() - tick) * 1000),
                findings_before=repairable,
                repair_plan=plan,
                findings_after=[item for item in findings if item.severity in {"critical", "blocker"} and not item.repaired],
                status="repaired" if notes else "warnings",
            ))

        unresolved = [item for item in findings if not item.repaired and item.severity in {"warning", "critical", "blocker"}]
        final_status = _final_status(unresolved, context)
        result = GoldenConvergenceResult(
            session_id=session_id,
            final_status=final_status,
            workflow_status="converged_with_repairs" if repaired_findings else "validated_without_repairs",
            customer_readiness=final_status,
            iterations=iterations or [
                ConvergenceIteration(
                    iteration_number=0,
                    stage="validate",
                    started_at=utc_now(),
                    completed_at=utc_now(),
                    duration_ms=0,
                    findings_before=findings,
                    findings_after=findings,
                    status="passed" if not unresolved else "warnings",
                )
            ],
            unresolved_findings=unresolved,
            repaired_findings=repaired_findings,
        )
        final_plan = self.planner.plan(unresolved)
        if final_plan.actions and final_plan.can_auto_apply:
            notes = self._apply_repairs(session_id, root, context, unresolved)
            final_plan.repairs_applied = len(notes)
            if notes:
                context = _load_context(root)
        generated = _write_convergence_artifacts(self.artifacts, session_id, result, findings, final_plan, context)
        result.generated_artifacts = generated
        self.artifacts.write_json(session_id, "quality", "golden_convergence_result", result.model_dump(mode="json"))
        return result

    async def _collect_findings(self, session_id: str, use_case: str, context: dict[str, Any]) -> list[QualityFinding]:
        findings: list[QualityFinding] = []
        findings.extend(_understanding_findings(context.get("report")))
        findings.extend(_pricing_findings(context.get("pricing") or ((context.get("report") or {}).get("pricing_analysis"))))
        findings.extend(_diagram_findings(context.get("diagrams")))
        findings.extend(_dossier_findings(context.get("dossier_consistency")))
        findings.extend(_customer_readiness_findings(context.get("report")))
        findings.extend(await self._architecture_findings(session_id, use_case, context))
        return _dedupe_findings(findings)

    async def _architecture_findings(self, session_id: str, use_case: str, context: dict[str, Any]) -> list[QualityFinding]:
        specs = _parse_specs(context.get("architectures"))
        if not specs:
            return []
        report = context.get("report") or {}
        pricing = (report.get("pricing_analysis") or context.get("pricing"))
        understanding = _understanding_from_report(report, use_case)
        output: list[QualityFinding] = []
        for issue in self.revisions.validate(specs):
            output.append(finding(
                code=f"architecture.{issue.code}",
                severity="critical" if issue.severity == "critical" else "warning",
                category="governance" if "governance" in issue.code else "architecture",
                title=issue.code.replace("_", " ").title(),
                description=issue.message,
                evidence=[issue.mode or "architecture"],
                auto_repairable=issue.code in {"write_without_governance"},
                repair_strategy="Run governance control enrichment and revalidate.",
                customer_readiness_impact="cap_to_internal_only" if issue.severity == "critical" else "cap_to_directional",
            ))
        for spec in specs:
            payload = (spec.metadata or {}).get("architecture_critique")
            critique = None
            if payload:
                try:
                    critique = payload
                except Exception:
                    critique = None
            if not critique:
                try:
                    review = await ArchitectureCritiqueService().critique(use_case, understanding, spec, None, session_id)
                    critique = review.model_dump(mode="json")
                except Exception:
                    critique = None
            for item in (critique or {}).get("findings", []):
                severity = "critical" if item.get("severity") == "critical" else "warning"
                category = "governance" if item.get("category") == "missing_governance" else "pricing" if item.get("category") == "pricing_driver_mismatch" else "architecture"
                output.append(finding(
                    code=f"{category}.{item.get('category', 'critique')}",
                    severity=severity,
                    category=category,
                    title=str(item.get("issue") or "Architecture critique finding"),
                    description=str(item.get("why_it_matters") or item.get("recommended_fix") or ""),
                    evidence=[spec.mode],
                    auto_repairable=bool(item.get("auto_repairable")),
                    repair_strategy=item.get("recommended_fix"),
                    customer_readiness_impact="cap_to_internal_only" if severity == "critical" else "cap_to_directional",
                ))
        return output

    def _apply_repairs(self, session_id: str, root: Path, context: dict[str, Any], findings: list[QualityFinding]) -> list[str]:
        notes: list[str] = []
        specs = _parse_specs(context.get("architectures"))
        if specs:
            repaired_specs, repair_notes = self.repairer.repair(specs, findings)
            if repair_notes:
                notes.extend(repair_notes)
                self.revisions._append(session_id, repaired_specs, "Golden convergence auto-repair")
        pricing = context.get("pricing") or ((context.get("report") or {}).get("pricing_analysis"))
        if pricing and any(item.category == "pricing" and item.severity in {"critical", "blocker"} for item in findings):
            metadata = dict(pricing.get("metadata") or {})
            metadata["pricing_can_be_displayed_as_headline"] = False
            metadata["headline_display"] = "Directional placeholder only - not headline-safe."
            if metadata.get("status") not in {"invalid_extracted_scale_not_applied", "directional_only_missing_core_compute_drivers"}:
                metadata["status"] = "invalid_placeholder"
            pricing["metadata"] = metadata
            _write_json(root / "pricing" / "estimate.json", pricing)
            report = context.get("report")
            if report:
                report["pricing_analysis"] = pricing
                report.setdefault("metadata", {})["pricing_sanity_review"] = {
                    **(report.get("metadata", {}).get("pricing_sanity_review") or {}),
                    "pricing_can_be_displayed_as_headline": False,
                    "pricing_status": metadata["status"],
                }
                _write_json(root / "research" / "report.json", report)
            notes.append("Pricing headline was invalidated because unresolved pricing sanity findings remain.")
        if any(item.category == "diagram" and item.auto_repairable for item in findings):
            notes.append("Diagram repair recorded explicit missing semantic/compiler view reason for downstream readiness and export.")
        return notes


def _load_context(root: Path) -> dict[str, Any]:
    return {
        "brief": _read_json(root / "brief" / "current.json"),
        "report": _read_json(root / "research" / "report.json"),
        "pricing": _read_json(root / "pricing" / "estimate.json"),
        "architectures": _read_json(root / "architecture" / "specs.json"),
        "architecture_revisions": _read_json(root / "architecture" / "revisions.json"),
        "diagrams": _read_json(root / "diagrams" / "gallery.json"),
        "dossier_consistency": _read_json(root / "quality" / "dossier_consistency_check.json"),
    }


def _understanding_findings(report: dict | None) -> list[QualityFinding]:
    validation = ((report or {}).get("metadata") or {}).get("understanding_validation") or {}
    findings: list[QualityFinding] = []
    for issue in validation.get("issues", []):
        severity = "critical" if issue.get("severity") == "critical" else "warning"
        category = "metrics" if issue.get("code") == "numbers_without_metrics" else "understanding"
        findings.append(finding(
            code=f"{category}.{issue.get('code')}",
            severity=severity,
            category=category,
            title=str(issue.get("code", "Understanding issue")).replace("_", " ").title(),
            description=str(issue.get("message", "")),
            evidence=["raw use case", "deep_use_case_understanding"],
            auto_repairable=False,
            customer_readiness_impact="cap_to_internal_only" if severity == "critical" else "cap_to_directional",
        ))
    return findings


def _pricing_findings(pricing: dict | None) -> list[QualityFinding]:
    if not pricing:
        return [finding(code="pricing.missing", severity="critical", category="pricing", title="Pricing artifact missing", description="Pricing analysis was not available for convergence.", evidence=["pricing/estimate.json"], auto_repairable=False, customer_readiness_impact="cap_to_internal_only")]
    metadata = pricing.get("metadata") or {}
    status = metadata.get("status") or metadata.get("pricing_sanity_review_status")
    maturity = metadata.get("pricing_maturity")
    source_truth = metadata.get("source_truth_pricing_compiler") or {}
    generic_not_estimated = source_truth.get("mode") == "generic_not_estimated"
    has_derived_dimensions = any(
        isinstance(item, dict)
        and item.get("quantity") not in (None, "", 0)
        and str(item.get("formula") or "").lower() != "not_estimated"
        for item in metadata.get("service_usage_dimensions") or []
    )
    findings: list[QualityFinding] = []
    if status in {"invalid_extracted_scale_not_applied", "invalid_placeholder"}:
        if generic_not_estimated and has_derived_dimensions and metadata.get("pricing_can_be_displayed_as_headline") is False:
            findings.append(finding(code="pricing.not_estimated_with_derived_dimensions", severity="warning", category="pricing", title="Pricing remains non-headline", description="Pricing is honestly withheld from headline totals while derived usage quantities are preserved for review.", evidence=[status, "source_truth_pricing_compiler.mode=generic_not_estimated"], auto_repairable=False, repair_strategy="Bind exact AWS usage/rate dimensions before showing a customer-facing total.", customer_readiness_impact="cap_to_directional"))
        else:
            findings.append(finding(code="pricing.fallback_driver_ignored_explicit_metrics", severity="critical", category="pricing", title="Pricing not headline-safe", description=metadata.get("reason") or "Pricing sanity found an invalid placeholder or ignored explicit metrics.", evidence=[status], auto_repairable=True, repair_strategy="Invalidate headline pricing and cap customer readiness.", customer_readiness_impact="cap_to_internal_only"))
    if status == "directional_only_missing_core_compute_drivers":
        findings.append(finding(code="pricing.directional_only_missing_core_compute_drivers", severity="critical", category="pricing", title="Core pricing drivers missing", description=metadata.get("reason") or "Core compute/SKU drivers are missing for this workload.", evidence=[status], auto_repairable=True, repair_strategy="Mark pricing as directional only and hide headline estimate.", customer_readiness_impact="cap_to_directional"))
    if metadata.get("pricing_can_be_displayed_as_headline") is False and maturity == "pricing_placeholder_only":
        findings.append(finding(code="pricing.headline_blocked", severity="warning", category="pricing", title="Headline pricing blocked", description="Pricing must be shown as directional placeholder only.", evidence=["pricing.metadata.pricing_can_be_displayed_as_headline=false"], auto_repairable=False, repair_strategy="Ensure reports do not show the estimate as a normal headline.", customer_readiness_impact="cap_to_directional"))
    elif metadata.get("pricing_can_be_displayed_as_headline") is False and maturity == "pricing_customer_demo_ready":
        findings.append(finding(code="pricing.scenario_demo_ready", severity="info", category="pricing", title="Scenario pricing ready for demo", description="Pricing is scenario-based, not procurement-ready, and can be shown as a directional demo estimate with visible caveats.", evidence=["pricing.metadata.pricing_maturity=pricing_customer_demo_ready"], auto_repairable=False, customer_readiness_impact="none"))
    elif metadata.get("pricing_can_be_displayed_as_headline") is False:
        findings.append(finding(code="pricing.headline_blocked", severity="warning", category="pricing", title="Headline pricing blocked", description="Pricing must be shown as directional placeholder only.", evidence=["pricing.metadata.pricing_can_be_displayed_as_headline=false"], auto_repairable=False, repair_strategy="Ensure reports do not show the estimate as a normal headline.", customer_readiness_impact="cap_to_directional"))
    return findings


def _diagram_findings(diagrams: list | None) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    if not diagrams:
        return findings
    for gallery in diagrams:
        broader_rendered = _broader_supported_view_ids(gallery)
        for missing in gallery.get("missing_requested_views") or []:
            view_id = str(missing.get("view_id") or "")
            if view_id in broader_rendered:
                findings.append(finding(code="diagram.requested_view_represented", severity="info", category="diagram", title="Requested view represented by supported diagram", description=str(missing.get("reason") or "Compiler represented this semantic request through a broader supported view."), evidence=[view_id], affected_sections=[str(gallery.get("mode"))], auto_repairable=False, repair_strategy="Keep the mapping in the audit record; no client dead-end is required.", customer_readiness_impact="none"))
            else:
                findings.append(finding(code="diagram.requested_view_suppressed", severity="warning", category="diagram", title="Requested view not rendered", description=str(missing.get("reason") or "Compiler did not render requested view."), evidence=[view_id], affected_sections=[str(gallery.get("mode"))], auto_repairable=True, repair_strategy="Record explicit suppression reason and readiness impact.", customer_readiness_impact="cap_to_customer_demo"))
        for qa in gallery.get("qa_reports") or []:
            if not qa.get("passed", False):
                if _qa_failure_is_view_coverage_only(qa, broader_rendered):
                    findings.append(finding(code="diagram.qa_view_coverage_only", severity="info", category="diagram", title="Diagram QA covered by broader view", description=f"Requested view {qa.get('view_id')} was represented through a broader supported diagram.", evidence=[str(qa.get("diagnostics") or [])], affected_sections=[str(gallery.get("mode"))], auto_repairable=False, customer_readiness_impact="none"))
                elif _qa_failure_is_non_blocking(qa):
                    findings.append(finding(code="diagram.qa_warning_only", severity="warning", category="diagram", title="Diagram QA recorded non-blocking warnings", description=f"Diagram QA for {qa.get('view_id')} reported warning/info diagnostics, but no render-blocking failure.", evidence=[str(qa.get("diagnostics") or [])], affected_sections=[str(gallery.get("mode"))], auto_repairable=False, customer_readiness_impact="cap_to_customer_demo"))
                else:
                    findings.append(finding(code="diagram.qa_failed", severity="critical", category="diagram", title="Diagram QA failed", description=f"Diagram QA failed for {qa.get('view_id')}.", evidence=[str(qa.get("diagnostics") or [])], affected_sections=[str(gallery.get("mode"))], auto_repairable=False, customer_readiness_impact="fail"))
    return findings


def _broader_supported_view_ids(gallery: dict) -> set[str]:
    ids: set[str] = set()
    for item in gallery.get("view_rendering_ledger") or gallery.get("rendering_ledger") or []:
        if not isinstance(item, dict):
            continue
        if item.get("rendered_via_broader_supported_view") or item.get("fallback_kind") == "broader_supported_view":
            for key in ("view_id", "semantic_view_id", "requested_view_id"):
                if item.get(key):
                    ids.add(str(item[key]))
    return ids


def _qa_failure_is_view_coverage_only(qa: dict, broader_rendered: set[str]) -> bool:
    view_id = str(qa.get("view_id") or "")
    diagnostics = " ".join(str(item) for item in qa.get("diagnostics") or []).lower()
    if view_id and view_id in broader_rendered:
        return True
    if not diagnostics:
        return False
    view_gap_terms = ("missing requested", "requested view", "not rendered", "did not emit", "semantic view", "broader supported")
    render_failure_terms = ("blank", "empty svg", "compile", "syntax", "renderer", "png", "svg failed")
    return any(term in diagnostics for term in view_gap_terms) and not any(term in diagnostics for term in render_failure_terms)


def _qa_failure_is_non_blocking(qa: dict) -> bool:
    diagnostics = qa.get("diagnostics") or []
    if not diagnostics:
        return False
    text = " ".join(str(item) for item in diagnostics).lower()
    render_failure_terms = (
        "blank",
        "empty svg",
        "compile",
        "syntax",
        "renderer failed",
        "png failed",
        "svg failed",
        "missing artifact",
        "file not found",
    )
    if any(term in text for term in render_failure_terms):
        return False
    for item in diagnostics:
        code = str(item.get("code") if isinstance(item, dict) else "").lower()
        if code in {"too_many_edge_crossings", "aws_service_catalog_fallback"}:
            continue
        severity = str(item.get("severity") if isinstance(item, dict) else "").lower()
        if severity in {"critical", "error", "fatal"}:
            return False
    return True


def _dossier_findings(consistency: dict | None) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    if not consistency:
        return findings
    for item in consistency.get("errors") or []:
        findings.append(finding(code="dossier.consistency_error", severity="critical", category="dossier", title="Dossier consistency error", description=str(item), evidence=["dossier_consistency_check"], auto_repairable=False, customer_readiness_impact="cap_to_internal_only"))
    for item in consistency.get("warnings") or []:
        findings.append(finding(code="dossier.consistency_warning", severity="warning", category="dossier", title="Dossier consistency warning", description=str(item), evidence=["dossier_consistency_check"], auto_repairable=False, customer_readiness_impact="cap_to_directional"))
    return findings


def _customer_readiness_findings(report: dict | None) -> list[QualityFinding]:
    readiness = ((report or {}).get("metadata") or {}).get("customer_readiness") or {}
    blockers = readiness.get("blockers") or []
    return [
        finding(code="export.customer_readiness_blocker", severity="warning", category="export", title="Customer readiness blocker", description=str(item), evidence=["customer_readiness"], auto_repairable=False, customer_readiness_impact="cap_to_directional")
        for item in blockers
    ]


def _parse_specs(payload: list | None) -> list[ArchitectureSpec]:
    specs: list[ArchitectureSpec] = []
    for item in payload or []:
        try:
            specs.append(ArchitectureSpec.model_validate(item))
        except Exception:
            continue
    return specs


def _understanding_from_report(report: dict, use_case: str) -> DeepUseCaseUnderstanding:
    payload = (report.get("metadata") or {}).get("deep_understanding") if report else None
    if payload:
        try:
            return DeepUseCaseUnderstanding.model_validate(payload)
        except Exception:
            pass
    return deterministic_understanding(use_case)


def _merge_repaired_state(findings: list[QualityFinding], repaired: list[QualityFinding]) -> list[QualityFinding]:
    repaired_by_code = {item.code: item for item in repaired}
    merged = []
    for item in findings:
        old = repaired_by_code.get(item.code)
        if old:
            item.repaired = True
            item.repair_notes = old.repair_notes
        merged.append(item)
    return merged


def _final_status(unresolved: list[QualityFinding], context: dict[str, Any]) -> FinalStatus:
    if any(item.customer_readiness_impact == "fail" or item.severity == "blocker" for item in unresolved):
        return "failed_validation"
    if any(item.customer_readiness_impact == "cap_to_internal_only" or item.severity == "critical" for item in unresolved):
        return "internal_only"
    if any(item.customer_readiness_impact == "cap_to_directional" for item in unresolved):
        return "directional_only"
    if any(item.severity == "warning" for item in unresolved):
        return "customer_demo_ready_with_caveats"
    return "golden_candidate"


def _write_convergence_artifacts(store: ArtifactStore, session_id: str, result: GoldenConvergenceResult, findings: list[QualityFinding], plan: RepairPlan, context: dict[str, Any]) -> list[str]:
    generated = [
        store.write_json(session_id, "quality", "quality_findings", [item.model_dump(mode="json") for item in findings]),
        store.write_json(session_id, "quality", "repair_plan", plan.model_dump(mode="json")),
        store.write_json(session_id, "quality", "customer_readiness", {"status": result.final_status, "unresolved_findings": len(result.unresolved_findings)}),
    ]
    return generated


def quality_summary_markdown(result: GoldenConvergenceResult) -> str:
    lines = [
        "# Quality and Repair Summary",
        "",
        f"- Final status: {result.final_status}",
        f"- Workflow status: {result.workflow_status}",
        f"- Repair iterations: {len([item for item in result.iterations if item.iteration_number])}",
        f"- Repaired findings: {len(result.repaired_findings)}",
        f"- Unresolved findings: {len(result.unresolved_findings)}",
        "",
        "## Repairs Applied",
    ]
    lines.extend(f"- {item.code}: {item.repair_notes or item.repair_strategy or item.title}" for item in result.repaired_findings)
    if not result.repaired_findings:
        lines.append("- None")
    lines.extend(["", "## Findings Unresolved"])
    lines.extend(f"- {item.severity.upper()} {item.code}: {item.title} - {item.description}" for item in result.unresolved_findings)
    if not result.unresolved_findings:
        lines.append("- None")
    lines.extend(["", "## Readiness Impact", _readiness_impact_text(result), ""])
    return "\n".join(lines)


def _readiness_impact_text(result: GoldenConvergenceResult) -> str:
    if result.final_status == "golden_candidate":
        return "No unresolved critical contradictions remain; package is a golden candidate subject to source freshness."
    if result.final_status == "customer_demo_ready_with_caveats":
        return "Suitable for customer demo with caveats; warnings must stay visible."
    if result.final_status == "directional_only":
        return "Directional only; do not use pricing or architecture as approval-ready."
    if result.final_status == "internal_only":
        return "Internal only; unresolved critical findings remain."
    return "Failed validation; package should not be presented externally."


def _dedupe_findings(items: list[QualityFinding]) -> list[QualityFinding]:
    seen: set[tuple[str, str, str]] = set()
    output: list[QualityFinding] = []
    for item in items:
        key = (item.code, item.title, ",".join(item.evidence))
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _read_json(path: Path):
    if not path.is_file():
        return None
    return __import__("json").loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(__import__("json").dumps(payload, indent=2, default=str), encoding="utf-8")
