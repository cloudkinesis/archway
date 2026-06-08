from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("ARCHWAY_LLM_PROVIDER", "deterministic")
os.environ.setdefault("ARCHWAY_ENABLE_WEB_SEARCH", "false")
os.environ.setdefault("ARCHWAY_ENABLE_COMPETITOR_WEB_SEARCH", "false")
os.environ.setdefault("ARCHWAY_TAVILY_MAX_CALLS_PER_SESSION", "0")
os.environ.setdefault("ARCHWAY_ENABLE_AWS_OFFICIAL_WEB_FALLBACK", "false")
os.environ.setdefault("ARCHWAY_DATA_DIR", str(Path(tempfile.gettempdir()) / "archway_rc2_golden_export_validation"))

from app.core.config import get_settings
from app.core.logging import read_session_logs
from app.db.session_store import SessionStore
from app.models.domain import DiagramGalleryResult, ResearchReport, SessionPhase, SessionStatus
from app.services.architecture import ArchitecturePlanner
from app.services.architecture_revisions import ArchitectureRevisionService
from app.services.artifacts import ArtifactStore
from app.services.diagram_compiler_adapter import DiagramCompilerAdapter
from app.services.export_package import ExportPackageService
from app.services.governance_controls import unresolved_effectful_flow_ids
from app.services.pricing_driver_selector import select_pricing_driver_family
from app.services.research import ResearchOrchestrator
from app.services.synthesis import SynthesisEngine
from app.services.use_case_profile import profile_use_case


Status = Literal["PASS", "WARN", "FAIL"]


@dataclass(frozen=True)
class GoldenScenario:
    id: str
    label: str
    use_case: str
    expected_pricing_family: str
    required_family_any: tuple[str, ...]
    required_components_any: tuple[str, ...]
    forbidden_terms: tuple[str, ...]
    required_pricing_driver_terms: tuple[str, ...]


SCENARIOS: tuple[GoldenScenario, ...] = (
    GoldenScenario(
        id="legal_contract_rag",
        label="Legal contract RAG and obligation workflow",
        use_case=(
            "AI-assisted legal contract review and obligation-tracking platform with 5,000 historical contracts, "
            "RAG Q&A, clause extraction, obligation tracking, approval workflow, and audit trail."
        ),
        expected_pricing_family="document_rag_workflow",
        required_family_any=("document_intelligence", "rag_assistant"),
        required_components_any=("Bedrock", "OpenSearch", "S3", "Step Functions"),
        required_pricing_driver_terms=("historical_contract_count", "rag_queries_per_day"),
        forbidden_terms=(
            "operating room",
            "ehr",
            "phi",
            "patient",
            "charge nurse",
            "hbase",
            "hdfs",
            "noc",
            "oss/bss",
            "cdr",
            "telemetry frequency",
            "sensor payload",
            "asset telemetry",
            "cdn",
            "bitrate",
            "viewer qoe",
            "depot",
            "dispatch",
            "field technician",
        ),
    ),
    GoldenScenario(
        id="healthcare_or",
        label="Healthcare OR scheduling / delay prediction",
        use_case=(
            "A hospital needs operating room delay prediction with Epic schedule data, patient check-in, charge nurse approval, "
            "PHI controls, and sterile processing readiness. Predictions refresh every 2 minutes across 18 hospitals and 240 operating rooms."
        ),
        expected_pricing_family="healthcare_operations_scheduling",
        required_family_any=("healthcare_operations_scheduling", "surgical_scheduling_prediction"),
        required_components_any=("DynamoDB", "Step Functions", "Lambda", "SageMaker", "Bedrock"),
        required_pricing_driver_terms=("hospital_count", "operating_room_count", "approval_workflow_executions_per_day"),
        forbidden_terms=(
            "depot",
            "dispatch",
            "field technician",
            "confirmed incident",
            "candidate anomaly",
            "predictive failure",
            "hbase",
            "hdfs",
            "noc",
            "oss/bss",
            "cdr",
            "cdn",
            "bitrate",
            "viewer qoe",
        ),
    ),
    GoldenScenario(
        id="telecom_hbase_hdfs",
        label="Telecom HBase/HDFS real-time analytics migration",
        use_case="We need to migrate a telecom HBase/HDFS real-time analytics platform to AWS.",
        expected_pricing_family="telecom_cdr_analytics",
        required_family_any=("telecom_network_analytics", "data_platform_analytics"),
        required_components_any=("EMR", "S3", "Glue", "Athena", "Kinesis", "MSK"),
        required_pricing_driver_terms=("storage_gb", "query_tb_scanned"),
        forbidden_terms=(
            "operating room",
            "ehr",
            "phi",
            "patient",
            "charge nurse",
            "contract clause",
            "obligation tracking",
            "renewal notice",
            "cdn",
            "bitrate",
            "viewer qoe",
            "depot",
            "dispatch",
        ),
    ),
)


def run_validation(
    scenario_ids: list[str] | None = None,
    *,
    out: str | Path = "artifacts/rc2_golden_export_validation_report.md",
    data_dir: str | Path | None = None,
    write_report: bool = True,
) -> list[dict[str, Any]]:
    _configure_environment(data_dir)
    selected = [item for item in SCENARIOS if not scenario_ids or item.id in set(scenario_ids)]
    results = asyncio.run(_run_selected(selected))
    if write_report:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown(results), encoding="utf-8")
    return results


def render_console_table(results: list[dict[str, Any]]) -> str:
    rows = [["Scenario", "Status", "Pricing", "Readiness", "Research", "Architecture", "Diagrams", "Export", "Zip"]]
    for item in results:
        rows.append(
            [
                item["scenario_id"],
                item["status"],
                item["pricing_family"],
                item["readiness"],
                item["research_status"],
                item["architecture_status"],
                item["diagram_status"],
                item["export_status"],
                item.get("export_zip_path") or "-",
            ]
        )
    widths = [max(len(str(row[index])) for row in rows) for index in range(len(rows[0]))]
    lines = []
    for index, row in enumerate(rows):
        lines.append(" | ".join(str(cell).ljust(widths[col]) for col, cell in enumerate(row)))
        if index == 0:
            lines.append("-+-".join("-" * width for width in widths))
    return "\n".join(lines)


def render_markdown(results: list[dict[str, Any]]) -> str:
    overall = "FAIL" if any(item["status"] == "FAIL" for item in results) else "WARN" if any(item["status"] == "WARN" for item in results) else "PASS"
    lines = [
        "# RC2 Golden Export Validation Report",
        "",
        f"Overall status: {overall}",
        "",
        "| Scenario | Status | First question | Pricing family | Readiness | Research | Architecture | Diagrams | Export | Export zip |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for item in results:
        lines.append(
            "| {id} | {status} | {question} | {pricing} | {readiness} | {research} | {architecture} | {diagrams} | {export} | {zip} |".format(
                id=item["scenario_id"],
                status=item["status"],
                question=_md(item["first_interview_question"]),
                pricing=item["pricing_family"],
                readiness=item["readiness"],
                research=item["research_status"],
                architecture=item["architecture_status"],
                diagrams=item["diagram_status"],
                export=item["export_status"],
                zip=item.get("export_zip_path") or "-",
            )
        )
    for item in results:
        lines.extend([
            "",
            f"## {item['label']}",
            "",
            f"- Session: `{item['session_id']}`",
            f"- Baseline domain: `{item['baseline_domain']}`",
            f"- Workload families: `{', '.join(item['workload_families'])}`",
            f"- Discovery planner: `{item['planner_domain']} / {item['planner_family']} / {item['planner_confidence']}`",
            f"- Pricing headline safe: `{item['headline_safe']}`",
            f"- Pricing readiness: `{item['pricing_readiness']}`",
            f"- Rendered views: `{', '.join(item['rendered_view_ids']) or 'none'}`",
            f"- Missing requested views: `{len(item['missing_requested_views'])}`",
            f"- D2/SVG artifact pairs: `{item['diagram_artifact_pair_count']}`",
            f"- Icon embedding metrics captured: `{item['icon_embedding_metric_captured']}`",
            f"- Export manifest status: `{item['export_manifest_status']}`",
            "",
            "Warnings:",
        ])
        lines.extend([f"- {warning}" for warning in item["warnings"]] or ["- none"])
        lines.extend(["", "Blockers:"])
        lines.extend([f"- {blocker}" for blocker in item["blockers"]] or ["- none"])
    return "\n".join(lines) + "\n"


async def _run_selected(scenarios: list[GoldenScenario]) -> list[dict[str, Any]]:
    results = []
    for scenario in scenarios:
        results.append(await _run_scenario(scenario))
    return results


async def _run_scenario(scenario: GoldenScenario) -> dict[str, Any]:
    warnings: list[str] = []
    blockers: list[str] = []
    session_id = ""
    export_zip_path = None
    try:
        artifacts = ArtifactStore()
        sessions = SessionStore()
        synthesis = SynthesisEngine()
        brief = synthesis.create_initial_brief(scenario.use_case)
        session = sessions.create(scenario.use_case, brief)
        session_id = session.id
        artifacts.write_json(session_id, "brief", "current", brief.model_dump(mode="json"))
        profile = profile_use_case(scenario.use_case)
        plan = brief.use_case_profile.get("discovery_plan") or {}
        first_question = synthesis.next_question(brief)

        report = await ResearchOrchestrator().run_research(brief, session_id)
        artifacts.write_json(session_id, "research", "report", report.model_dump(mode="json"))
        artifacts.write_json(session_id, "pricing", "estimate", report.pricing_analysis.model_dump(mode="json"))

        specs = ArchitecturePlanner().generate(report)
        revision_service = ArchitectureRevisionService()
        revision = revision_service.initialize(session_id, specs)
        specs = revision.specs
        validation_issues = [issue.model_dump(mode="json") for issue in revision.validation_issues]

        galleries: list[DiagramGalleryResult] = []
        adapter = DiagramCompilerAdapter()
        for spec in specs:
            if spec.mode == "poc":
                galleries.append(adapter.compile_poc_diagrams(spec, session_id))
            else:
                galleries.append(adapter.compile_production_diagrams(spec, session_id))
        artifacts.write_json(session_id, "diagrams", "gallery", [gallery.model_dump(mode="json") for gallery in galleries])

        session.active_phase = SessionPhase.diagrams
        session.status = SessionStatus.complete
        sessions.save(session)

        bundle = await asyncio.to_thread(ExportPackageService().generate, session_id)
        export_zip_path = str(artifacts.resolve(session_id, bundle.artifact_id))
        manifest = _read_manifest(artifacts.resolve(session_id, bundle.manifest_artifact_id))
        zip_names = _zip_names(export_zip_path)

        result = _assess(
            scenario=scenario,
            session_id=session_id,
            profile=profile,
            plan=plan,
            first_question=first_question.prompt if first_question else "",
            report=report,
            specs=specs,
            validation_issues=validation_issues,
            galleries=galleries,
            bundle=bundle.model_dump(mode="json"),
            manifest=manifest,
            zip_names=zip_names,
            export_zip_path=export_zip_path,
            warnings=warnings,
            blockers=blockers,
        )
        return result
    except Exception as exc:
        blockers.append(f"Pipeline crashed: {type(exc).__name__}: {exc}")
        return {
            "scenario_id": scenario.id,
            "label": scenario.label,
            "session_id": session_id or "not-created",
            "status": "FAIL",
            "baseline_domain": None,
            "workload_families": [],
            "planner_domain": "unknown",
            "planner_family": "unknown",
            "planner_confidence": "unknown",
            "first_interview_question": "",
            "pricing_family": "unknown",
            "headline_safe": False,
            "pricing_readiness": "unknown",
            "readiness": "failed",
            "research_status": "failed",
            "architecture_status": "failed",
            "diagram_status": "failed",
            "export_status": "failed",
            "export_manifest_status": "missing",
            "export_zip_path": export_zip_path,
            "rendered_view_ids": [],
            "missing_requested_views": [],
            "diagram_artifact_pair_count": 0,
            "icon_embedding_metric_captured": False,
            "warnings": warnings,
            "blockers": blockers,
        }


def _assess(
    *,
    scenario: GoldenScenario,
    session_id: str,
    profile: Any,
    plan: dict[str, Any],
    first_question: str,
    report: ResearchReport,
    specs: list[Any],
    validation_issues: list[dict[str, Any]],
    galleries: list[DiagramGalleryResult],
    bundle: dict[str, Any],
    manifest: dict[str, Any],
    zip_names: set[str],
    export_zip_path: str,
    warnings: list[str],
    blockers: list[str],
) -> dict[str, Any]:
    pricing = report.pricing_analysis
    pricing_family = str(pricing.metadata.get("pricing_driver_family") or select_pricing_driver_family(profile).value)
    headline_safe = bool(pricing.metadata.get("pricing_can_be_displayed_as_headline"))
    pricing_readiness = _pricing_readiness(pricing)
    readiness = ((report.metadata or {}).get("customer_readiness") or {}).get("status") or "unknown"
    research_text = _research_text(report)
    architecture_text = _architecture_text(specs)
    visible_text = "\n".join([research_text, architecture_text, first_question, " ".join(pricing.main_cost_drivers)]).lower()

    _check_discovery(scenario, profile, plan, first_question, pricing_family, headline_safe, warnings, blockers)
    research_status = _check_research(scenario, report, research_text, warnings, blockers)
    architecture_status = _check_architecture(scenario, specs, validation_issues, warnings, blockers)
    diagram_status = _check_diagrams(galleries, warnings, blockers)
    export_status = _check_export(bundle, manifest, zip_names, warnings, blockers)
    _check_pricing(scenario, pricing, pricing_family, headline_safe, warnings, blockers)
    _check_antidrift(scenario, visible_text, scenario.use_case, blockers)

    rendered_view_ids = [view for gallery in galleries for view in gallery.rendered_view_ids]
    missing_requested_views = [item for gallery in galleries for item in gallery.missing_requested_views]
    status: Status = "FAIL" if blockers else "WARN" if warnings or pricing_readiness == "directional" else "PASS"
    return {
        "scenario_id": scenario.id,
        "label": scenario.label,
        "session_id": session_id,
        "status": status,
        "baseline_domain": profile.domain,
        "workload_families": list(profile.workload_families),
        "planner_domain": _candidate_name(plan, "domain_candidates"),
        "planner_family": _candidate_name(plan, "workload_family_candidates"),
        "planner_confidence": str(plan.get("confidence") or "unknown"),
        "first_interview_question": first_question,
        "pricing_family": pricing_family,
        "headline_safe": headline_safe,
        "pricing_readiness": pricing_readiness,
        "readiness": readiness,
        "research_status": research_status,
        "architecture_status": architecture_status,
        "diagram_status": diagram_status,
        "export_status": export_status,
        "export_manifest_status": "present" if manifest else "missing",
        "export_zip_path": export_zip_path,
        "rendered_view_ids": rendered_view_ids,
        "missing_requested_views": missing_requested_views,
        "diagram_artifact_pair_count": _diagram_artifact_pair_count(galleries),
        "icon_embedding_metric_captured": _icon_metrics_captured(galleries),
        "warnings": warnings,
        "blockers": blockers,
    }


def _check_discovery(
    scenario: GoldenScenario,
    profile: Any,
    plan: dict[str, Any],
    first_question: str,
    pricing_family: str,
    headline_safe: bool,
    warnings: list[str],
    blockers: list[str],
) -> None:
    families = set(profile.workload_families)
    if not any(family in families for family in scenario.required_family_any):
        blockers.append(f"Baseline families {sorted(families)} do not include expected {scenario.required_family_any}.")
    if pricing_family != scenario.expected_pricing_family:
        blockers.append(f"Pricing family {pricing_family} did not match expected {scenario.expected_pricing_family}.")
    if headline_safe:
        blockers.append("Pricing was marked headline-safe without SKU/tier traceability and confirmed quantities.")
    if not first_question:
        blockers.append("First interview question was missing.")
    if plan.get("pricing_procurement_ready") or plan.get("procurement_ready"):
        blockers.append("Planner exposed a procurement-ready authority flag.")
    if plan.get("ambiguity_detected"):
        warnings.append("Discovery planner marked ambiguity; scenario proceeded with deterministic pipeline.")


def _check_research(scenario: GoldenScenario, report: ResearchReport, research_text: str, warnings: list[str], blockers: list[str]) -> str:
    if not report:
        blockers.append("Research report missing.")
        return "missing"
    if not report.executive_verdict:
        blockers.append("Executive summary/verdict missing.")
    if "ev_" in "\n".join([report.executive_verdict, report.use_case_interpretation, report.feasibility_analysis, report.viability_analysis, report.competitor_analysis]).lower():
        blockers.append("Default research narrative exposes raw ev_* evidence IDs.")
    if not report.pricing_analysis:
        blockers.append("Pricing section missing from research report.")
    if not report.assumptions:
        blockers.append("Research assumptions missing.")
    competitor_status = ((report.metadata or {}).get("competitor_scan") or {})
    if _competitor_status(competitor_status) not in {"completed", "not_run", "skipped", "failed"}:
        blockers.append("Competitor status was not explicit.")
    if not report.citation_coverage or not report.citation_coverage.passed:
        warnings.append("Citation/evidence coverage is limited; acceptable for local deterministic validation but not customer-ready.")
    return "ok"


def _check_architecture(scenario: GoldenScenario, specs: list[Any], validation_issues: list[dict[str, Any]], warnings: list[str], blockers: list[str]) -> str:
    modes = {spec.mode for spec in specs}
    if "poc" not in modes:
        blockers.append("POC architecture missing.")
    if "production" not in modes:
        blockers.append("Production architecture missing.")
    if validation_issues is None:
        blockers.append("Architecture validation status missing.")
    critical = [issue for issue in validation_issues or [] if issue.get("severity") == "critical"]
    if critical:
        blockers.append(f"Critical architecture validation issues remain: {critical}")
    unresolved = [flow_id for spec in specs for flow_id in unresolved_effectful_flow_ids(spec)]
    if unresolved:
        blockers.append(f"Effectful flows remain without governance controls: {unresolved}")
    for spec in specs:
        if any(_looks_unsafe_writeback(flow) for flow in spec.flows):
            blockers.append(f"{spec.mode} has direct unsafe external writeback path.")
    component_text = _architecture_text(specs)
    if not any(term.lower() in component_text for term in scenario.required_components_any):
        warnings.append(f"Expected component/service hints not found in architecture: {scenario.required_components_any}.")
    return "ok" if not critical and not unresolved else "blocked"


def _check_diagrams(galleries: list[DiagramGalleryResult], warnings: list[str], blockers: list[str]) -> str:
    if not galleries:
        blockers.append("Diagram gallery missing.")
        return "missing"
    all_diagrams = [diagram for gallery in galleries for diagram in gallery.diagrams]
    if not all_diagrams:
        blockers.append("Diagram gallery contains no diagrams.")
    missing = [item for gallery in galleries for item in gallery.missing_requested_views]
    silent_missing = [item for item in missing if not item.get("reason")]
    if silent_missing:
        blockers.append(f"Requested diagram views missing without reason: {silent_missing}")
    degraded_without_reason = [diagram.id for diagram in all_diagrams if not diagram.rendered_as_native_view and not diagram.fallback_reason]
    if degraded_without_reason:
        blockers.append(f"Degraded diagram(s) lack reason: {degraded_without_reason}")
    qa_failures = [diag for gallery in galleries for qa in gallery.qa_reports for diag in qa.diagnostics if diag]
    if qa_failures:
        warnings.append(f"Diagram QA reported diagnostics: {qa_failures[:4]}")
    if not _diagram_artifact_pair_count(galleries):
        blockers.append("No D2/SVG diagram artifact pairs were produced.")
    if not _icon_metrics_captured(galleries):
        warnings.append("Icon embedding metric was not captured.")
    return "ok" if not qa_failures else "degraded"


def _check_pricing(scenario: GoldenScenario, pricing: Any, pricing_family: str, headline_safe: bool, warnings: list[str], blockers: list[str]) -> None:
    if pricing_family != scenario.expected_pricing_family:
        blockers.append(f"Pricing family mismatch: {pricing_family} vs {scenario.expected_pricing_family}.")
    if headline_safe:
        blockers.append("Headline-safe pricing should be false for RC2 local validation.")
    if _pricing_readiness(pricing) == "directional":
        warnings.append("Pricing is directional and not procurement-ready.")
    for required in scenario.required_pricing_driver_terms:
        if required.lower() not in " ".join(pricing.main_cost_drivers + pricing.unknown_variables).lower():
            blockers.append(f"Pricing drivers missing expected term: {required}.")
    for line in pricing.line_items:
        if line.expected_monthly_usd > 0 and not line.pricing_trace:
            blockers.append(f"Non-zero pricing line {line.service} has empty pricing trace.")
        if line.expected_monthly_usd > 0 and line.pricing_trace.get("procurement_ready"):
            blockers.append(f"Non-zero pricing line {line.service} was treated as procurement-ready.")


def _check_export(bundle: dict[str, Any], manifest: dict[str, Any], zip_names: set[str], warnings: list[str], blockers: list[str]) -> str:
    if not bundle or not bundle.get("artifact_id"):
        blockers.append("Export zip missing.")
        return "missing"
    required = {
        "01-solution-brief.md",
        "02-research-report.md",
        "02B-deep-research-dossier.md",
        "03-pricing.md",
        "04-architecture.md",
        "05-diagrams.md",
        "07-diagnostics.md",
        "10-quality-and-repair-summary.md",
        "manifest.json",
        "raw/brief.json",
        "raw/research_report.json",
        "raw/pricing.json",
        "raw/architecture_specs.json",
        "raw/diagram_gallery.json",
    }
    missing = sorted(required - zip_names)
    if missing:
        blockers.append(f"Export zip missing required files: {missing}.")
    if not manifest:
        blockers.append("Export manifest missing.")
    if bundle.get("warnings"):
        warnings.extend(f"Export warning: {item}" for item in bundle.get("warnings") or [])
    return "ok" if not missing and manifest else "blocked"


def _check_antidrift(scenario: GoldenScenario, text: str, source_text: str, blockers: list[str]) -> None:
    source = source_text.lower()
    leaked = [term for term in scenario.forbidden_terms if term in text and term not in source]
    if leaked:
        blockers.append(f"Forbidden cross-domain terms detected: {leaked}.")


def _configure_environment(data_dir: str | Path | None) -> None:
    if data_dir is not None:
        os.environ["ARCHWAY_DATA_DIR"] = str(data_dir)
    os.environ["ARCHWAY_LLM_PROVIDER"] = "deterministic"
    os.environ["ARCHWAY_ENABLE_WEB_SEARCH"] = "false"
    os.environ["ARCHWAY_ENABLE_COMPETITOR_WEB_SEARCH"] = "false"
    os.environ["ARCHWAY_TAVILY_MAX_CALLS_PER_SESSION"] = "0"
    os.environ["ARCHWAY_ENABLE_AWS_OFFICIAL_WEB_FALLBACK"] = "false"
    get_settings.cache_clear()


def _candidate_name(plan: dict[str, Any], key: str) -> str:
    candidates = plan.get(key) or []
    if candidates and isinstance(candidates[0], dict):
        return str(candidates[0].get("name") or "unknown")
    return "unknown"


def _competitor_status(status: dict[str, Any]) -> str:
    if status.get("failure_reason"):
        return "failed"
    if status.get("results_used", 0) > 0:
        return "completed"
    if status.get("skipped_reason"):
        return "skipped"
    return "not_run"


def _pricing_readiness(pricing: Any) -> str:
    if pricing.metadata.get("pricing_can_be_displayed_as_headline") and all(line.pricing_trace.get("procurement_ready") for line in pricing.line_items):
        return "procurement-ready"
    return "directional"


def _research_text(report: ResearchReport) -> str:
    return "\n".join(
        [
            report.executive_verdict,
            report.use_case_interpretation,
            report.feasibility_analysis,
            report.viability_analysis,
            report.competitor_analysis,
            report.recommended_poc,
            report.recommended_production_direction,
            " ".join(item.text for item in report.assumptions),
        ]
    ).lower()


def _architecture_text(specs: list[Any]) -> str:
    return "\n".join(
        [
            spec.summary
            + " "
            + " ".join(component.name + " " + component.service for component in spec.components)
            + " "
            + " ".join(flow.label or "" for flow in spec.flows)
            for spec in specs
        ]
    ).lower()


def _looks_unsafe_writeback(flow: Any) -> bool:
    text = f"{flow.label or ''} {flow.metadata}".lower()
    if "writeback" not in text and "external_write" not in text:
        return False
    return not any(term in text for term in ("approval", "queue", "policy", "recommendation_only"))


def _diagram_artifact_pair_count(galleries: list[DiagramGalleryResult]) -> int:
    count = 0
    for gallery in galleries:
        for diagram in gallery.diagrams:
            if diagram.format_paths.get("svg") and diagram.format_paths.get("d2"):
                count += 1
    return count


def _icon_metrics_captured(galleries: list[DiagramGalleryResult]) -> bool:
    for gallery in galleries:
        for qa in gallery.qa_reports:
            if "icon_embedding" in qa.metrics:
                return True
    return False


def _read_manifest(path: Path) -> dict[str, Any]:
    import json

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _zip_names(path: str | Path) -> set[str]:
    try:
        with ZipFile(path) as archive:
            return set(archive.namelist())
    except Exception:
        return set()


def _md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RC2 golden export validation scenarios.")
    parser.add_argument("--out", default="artifacts/rc2_golden_export_validation_report.md")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--scenario", action="append", dest="scenarios", help="Scenario id to run. Can be repeated.")
    args = parser.parse_args()

    results = run_validation(args.scenarios, out=args.out, data_dir=args.data_dir)
    print(render_console_table(results))
    print()
    print(f"Markdown report: {args.out}")
    overall = "FAIL" if any(item["status"] == "FAIL" for item in results) else "WARN" if any(item["status"] == "WARN" for item in results) else "PASS"
    print(f"Status: {overall}")
    for item in results:
        for warning in item["warnings"]:
            print(f"WARN {item['scenario_id']}: {warning}")
        for blocker in item["blockers"]:
            print(f"FAIL {item['scenario_id']}: {blocker}")
    return 1 if overall == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
