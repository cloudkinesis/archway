from pathlib import Path
import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core.logging import AuditLogger, hash_payload, read_session_logs
from app.db.session_store import SessionStore
from app.models.domain import ArchitectureSpec, DiagramGalleryResult, ResearchReport, SessionPhase, SessionStatus
from app.models.schemas import CreateSessionRequest, ProceedRequest, SynthesisMessageRequest, UpdateArchitectureRequest, UpdateSessionRequest
from app.services.architecture import ArchitecturePlanner
from app.services.architecture_critique import ArchitectureCritiqueService
from app.services.architecture_revisions import ArchitectureRevisionService
from app.services.artifacts import ArtifactStore
from app.services.build_status import BuildStatusService
from app.services.convergence.architecture_repairer import ArchitectureRepairer
from app.services.deep_dossier import DeepDossierService
from app.services.diagram_compiler_adapter import DiagramCompilerAdapter
from app.services.health import HealthService
from app.services.jobs import job_manager
from app.services.export_package import ExportPackageService
from app.services.golden_regression import GoldenRegressionExportService
from app.services.governance_controls import GovernanceControlEnricher
from app.services.pricing import PricingEngine
from app.services.pricing_driver_closure import build_pricing_checkpoint, build_pricing_driver_closure
from app.services.pricing_scenario_profiles import scenario_profile
from app.services.customer_readiness import assess_customer_readiness
from app.services.research import ResearchOrchestrator
from app.services.research_ui_digest import build_research_ui_digest
from app.services.research_view_model import build_research_view_model
from app.services.synthesis import SynthesisEngine
from app.services.understanding.deep_use_case_understanding import DeepUseCaseUnderstanding, deterministic_understanding
from app.domain.quality_findings import finding

router = APIRouter(prefix="/api")
store = SessionStore()
artifacts = ArtifactStore()
synthesis = SynthesisEngine()
architecture_revisions = ArchitectureRevisionService()


class PricingCheckpointAnswerRequest(BaseModel):
    question_id: str | None = None
    option_id: str | None = None
    driver_values: dict[str, object] = Field(default_factory=dict)


class PricingCheckpointProfileRequest(BaseModel):
    profile_id: str


@router.get("/health")
async def health():
    return await HealthService().check()


@router.post("/health/retry")
async def health_retry():
    return await HealthService().check(force_remote=True)


@router.get("/build/status")
async def build_status():
    return await BuildStatusService().status()


@router.get("/golden-regression/export")
async def golden_regression_export():
    return GoldenRegressionExportService().export()


@router.post("/sessions")
async def create_session(request: CreateSessionRequest):
    brief = synthesis.create_initial_brief(request.initial_use_case)
    brief = await synthesis.enhance_brief(brief)
    session = store.create(request.initial_use_case, brief)
    artifacts.write_json(session.id, "brief", "current", brief.model_dump(mode="json"))
    AuditLogger(session.id).event("synthesis", "session_created", inputs_hash=hash_payload(request.initial_use_case), output_hash=hash_payload(session.model_dump()))
    return {"session": session, "readiness": synthesis.readiness(brief), "message": synthesis.opening_message(brief)}


@router.get("/sessions")
async def list_sessions():
    return {"sessions": store.list()}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    return {"session": _require_session(session_id)}


@router.get("/sessions/{session_id}/hydrate")
async def hydrate_session(session_id: str):
    session = _require_session(session_id)
    brief = _read_json_with_export_fallback(session_id, "brief/current.json", "brief.json")
    report = _read_json_with_export_fallback(session_id, "research/report.json", "research_report.json")
    pricing = _read_json_with_export_fallback(session_id, "pricing/estimate.json", "pricing.json")
    diagrams = _read_json_with_export_fallback(session_id, "diagrams/gallery.json", "diagram_gallery.json")
    specs = architecture_revisions.active_specs(session_id)
    revisions = architecture_revisions.list(session_id)
    validation_issues = revisions[-1].validation_issues if revisions else (architecture_revisions.validate(specs) if specs else [])
    latest_export = _latest_export_bundle(session_id)
    narrative = _research_narrative(session_id, brief, report, pricing, [spec.model_dump(mode="json") for spec in specs] if specs else None, diagrams)
    digest = await build_research_ui_digest(session_id, report, narrative)
    view_model = build_research_view_model(
        session_id,
        report,
        digest.model_dump(mode="json") if digest else None,
        pricing,
        narrative,
    )
    return {
        "session": session,
        "readiness": synthesis.readiness(session.current_summary) if session.current_summary else None,
        "brief": brief,
        "research": report,
        "research_narrative": narrative,
        "research_digest": digest,
        "research_view_model": view_model,
        "pricing": pricing,
        "architecture": {
            "architectures": specs or [],
            "revisions": revisions,
            "validation_issues": validation_issues,
        },
        "diagrams": diagrams or [],
        "diagnostics": {
            "logs": read_session_logs(session_id),
            "latest_export": latest_export,
        },
    }


@router.patch("/sessions/{session_id}")
async def update_session(session_id: str, request: UpdateSessionRequest):
    session = _require_session(session_id)
    if request.name:
        session.name = request.name
    return {"session": store.save(session)}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    return {"deleted": store.delete(session_id)}


@router.post("/sessions/{session_id}/synthesis/message")
async def synthesis_message(session_id: str, request: SynthesisMessageRequest):
    session = _require_session(session_id)
    if session.current_summary is None:
        raise HTTPException(status_code=409, detail="This session does not have a brief yet.")
    response = synthesis.respond(session.current_summary, request.message)
    response.brief = await synthesis.enhance_brief(response.brief, session_id=session_id)
    response.readiness = synthesis.readiness(response.brief)
    answered_count = len((((response.brief.use_case_profile or {}).get("interview") or {}).get("answered") or []))
    response.message = synthesis.format_question(synthesis.next_question(response.brief), answered_count)
    session.current_summary = response.brief
    session.active_phase = SessionPhase.synthesis
    session.status = SessionStatus.shaping
    store.save(session)
    artifacts.write_json(session.id, "brief", "current", response.brief.model_dump(mode="json"))
    AuditLogger(session.id).event("synthesis", "message_processed", inputs_hash=hash_payload(request.message), output_hash=hash_payload(response.brief.model_dump()))
    return response


@router.post("/sessions/{session_id}/synthesis/proceed")
async def synthesis_proceed(session_id: str, request: ProceedRequest):
    session = _require_session(session_id)
    if session.current_summary is None:
        raise HTTPException(status_code=409, detail="This session does not have a brief yet.")
    readiness = synthesis.readiness(session.current_summary)
    checkpoint = readiness.recommended_minimum_questions[:3]
    answered_count = len((((session.current_summary.use_case_profile or {}).get("interview") or {}).get("answered") or []))
    next_question = synthesis.next_question(session.current_summary)
    if not request.assume_and_proceed and next_question and answered_count < 4:
        return {
            "proceeded": False,
            "message": synthesis.format_question(next_question, answered_count),
            "questions": [next_question],
            "readiness": readiness,
        }
    if request.assume_and_proceed or readiness.can_proceed or not readiness.critical_gaps:
        existing_ids = {item.text for item in session.current_summary.assumptions}
        for assumption in readiness.assumptions_if_skipped:
            if assumption.text not in existing_ids:
                session.current_summary.assumptions.append(assumption)
        session.active_phase = SessionPhase.research
        session.status = SessionStatus.researching
        store.save(session)
        artifacts.write_json(session.id, "brief", "current", session.current_summary.model_dump(mode="json"))
        return {"proceeded": True, "message": "I can proceed now. I’ll make conservative assumptions and call them out clearly.", "readiness": readiness}
    return {
        "proceeded": False,
        "message": "I can proceed now. Before I do, these details materially affect pricing, security, or architecture. You can answer them or let Archway assume and proceed.",
        "questions": checkpoint,
        "readiness": readiness,
    }


@router.get("/sessions/{session_id}/brief")
async def get_brief(session_id: str):
    session = _require_session(session_id)
    return {"brief": session.current_summary, "readiness": synthesis.readiness(session.current_summary) if session.current_summary else None}


@router.post("/sessions/{session_id}/research/run")
async def run_research(session_id: str):
    session = _require_session(session_id)
    if session.current_summary is None:
        raise HTTPException(status_code=409, detail="This session does not have a brief yet.")
    session.active_phase = SessionPhase.research
    session.status = SessionStatus.researching
    store.save(session)
    brief = session.current_summary.model_copy(deep=True)

    def work(job_id: str) -> str:
        report = asyncio.run(ResearchOrchestrator().run_research(
            brief,
            session_id,
            progress=lambda value, message: job_manager.update(job_id, progress=value, message=message),
        ))
        job_manager.update(job_id, progress=96, message="Writing research report and pricing artifacts.")
        report_path = artifacts.write_json(session_id, "research", "report", report.model_dump(mode="json"))
        artifacts.write_json(session_id, "pricing", "estimate", report.pricing_analysis.model_dump(mode="json"))
        current = _require_session(session_id)
        current.status = SessionStatus.architecture
        current.active_phase = SessionPhase.architecture
        store.save(current)
        AuditLogger(session_id).event("research", "research_completed", output_hash=hash_payload(report.model_dump()))
        return report_path

    job = job_manager.submit(session_id, "research", work, "Research queued.")
    return {"job": job}


@router.get("/sessions/{session_id}/research/status")
async def research_status(session_id: str):
    session = _require_session(session_id)
    report = _read_json(session_id, "research/report.json")
    job = job_manager.latest_for_session(session_id, "research")
    return {"status": session.status, "has_report": report is not None, "job": job}


@router.get("/sessions/{session_id}/research/report")
async def research_report(session_id: str):
    report = _read_json(session_id, "research/report.json")
    if report is None:
        raise HTTPException(status_code=404, detail="Research report is not ready yet.")
    return {"report": report}


@router.get("/sessions/{session_id}/pricing/checkpoint")
async def pricing_checkpoint(session_id: str):
    _require_session(session_id)
    pricing = _read_json(session_id, "pricing/estimate.json")
    if pricing is None:
        raise HTTPException(status_code=409, detail="Run research before pricing checkpoint.")
    state = _read_json(session_id, "pricing/checkpoint_state.json") or {}
    checkpoint = build_pricing_checkpoint(pricing, session_id=session_id, state=state)
    artifacts.write_json(session_id, "pricing", "pricing_driver_closure", checkpoint.closure_report.model_dump(mode="json"))
    return {"checkpoint": checkpoint}


@router.post("/sessions/{session_id}/pricing/checkpoint/answer")
async def answer_pricing_checkpoint(session_id: str, request: PricingCheckpointAnswerRequest):
    _require_session(session_id)
    if not request.driver_values:
        raise HTTPException(status_code=400, detail="Provide at least one pricing driver value.")
    state = _read_json(session_id, "pricing/checkpoint_state.json") or {}
    driver_values = {**(state.get("driver_values") or {}), **request.driver_values}
    confirmed = set(state.get("confirmed_driver_names") or [])
    confirmed.update(request.driver_values.keys())
    state = {
        **state,
        "driver_values": driver_values,
        "confirmed_driver_names": sorted(confirmed),
        "last_question_id": request.question_id,
        "last_option_id": request.option_id,
        "proceed_without_headline": False,
    }
    return await _apply_pricing_checkpoint_state(session_id, state)


@router.post("/sessions/{session_id}/pricing/checkpoint/use-profile")
async def use_pricing_checkpoint_profile(session_id: str, request: PricingCheckpointProfileRequest):
    _require_session(session_id)
    profile = scenario_profile(request.profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Scenario profile was not found.")
    state = _read_json(session_id, "pricing/checkpoint_state.json") or {}
    state = {
        **state,
        "scenario_profile_used": profile.id,
        "driver_values": {**profile.driver_values, **(state.get("driver_values") or {})},
        "confirmed_driver_names": state.get("confirmed_driver_names") or [],
        "proceed_without_headline": False,
    }
    return await _apply_pricing_checkpoint_state(session_id, state)


@router.post("/sessions/{session_id}/pricing/checkpoint/proceed-without-headline")
async def proceed_pricing_without_headline(session_id: str):
    _require_session(session_id)
    pricing = _read_json(session_id, "pricing/estimate.json")
    if pricing is None:
        raise HTTPException(status_code=409, detail="Run research before pricing checkpoint.")
    state = {**(_read_json(session_id, "pricing/checkpoint_state.json") or {}), "proceed_without_headline": True}
    closure = build_pricing_driver_closure(pricing, scenario_profile_used=state.get("scenario_profile_used"), proceed_without_headline=True)
    pricing["metadata"] = {
        **(pricing.get("metadata") or {}),
        "pricing_driver_closure": closure.model_dump(mode="json"),
        "pricing_maturity": closure.pricing_maturity,
        "pricing_can_be_displayed_as_headline": False,
        "directional_scenario_allowed": False,
        "headline_display": "Pricing withheld from executive headline because critical pricing drivers are unresolved.",
    }
    artifacts.write_json(session_id, "pricing", "checkpoint_state", state)
    artifacts.write_json(session_id, "pricing", "estimate", pricing)
    artifacts.write_json(session_id, "pricing", "pricing_driver_closure", closure.model_dump(mode="json"))
    _update_report_pricing(session_id, pricing)
    checkpoint = build_pricing_checkpoint(pricing, session_id=session_id, state=state)
    return {"checkpoint": checkpoint, "pricing": pricing}


@router.post("/sessions/{session_id}/architecture/generate")
async def generate_architecture(session_id: str):
    _require_session(session_id)
    report_data = _read_json(session_id, "research/report.json")
    if report_data is None:
        raise HTTPException(status_code=409, detail="Run research before generating architecture.")
    report = ResearchReport.model_validate(report_data)

    def work(job_id: str) -> str:
        job_manager.update(job_id, progress=10, message="Generating POC and production architecture options.")
        specs = ArchitecturePlanner().generate(report)
        job_manager.update(job_id, progress=30, message="Enriching governance controls for effectful flows.")
        specs = GovernanceControlEnricher().enrich_specs(specs)
        job_manager.update(job_id, progress=45, message="Validating service selection and architecture constraints.")
        specs = asyncio.run(_attach_architecture_critiques(report, specs, session_id))
        job_manager.update(job_id, progress=62, message="Running architecture critique and repair planning.")
        specs = asyncio.run(_repair_architecture_critiques(report, specs, session_id))
        job_manager.update(job_id, progress=82, message="Saving revision and preparing diagram inputs.")
        revision = architecture_revisions.record_generation(session_id, specs)
        specs_path = "architecture/specs.json"
        current = _require_session(session_id)
        current.active_phase = SessionPhase.diagrams
        current.status = SessionStatus.diagrams
        store.save(current)
        return specs_path

    job = job_manager.submit(session_id, "architecture", work, "Architecture planning queued.")
    return {"job": job}


async def _attach_architecture_critiques(report: ResearchReport, specs: list[ArchitectureSpec], session_id: str) -> list[ArchitectureSpec]:
    understanding = _understanding_from_report(report)
    service = ArchitectureCritiqueService()
    critiqued: list[ArchitectureSpec] = []
    for spec in specs:
        updated = spec.model_copy(deep=True)
        critique = await service.critique(report.use_case_interpretation, understanding, updated, report.pricing_analysis, session_id)
        updated.metadata = {**updated.metadata, "architecture_critique": critique.model_dump(mode="json")}
        critiqued.append(updated)
    return critiqued


async def _repair_architecture_critiques(report: ResearchReport, specs: list[ArchitectureSpec], session_id: str) -> list[ArchitectureSpec]:
    repairer = ArchitectureRepairer()
    current = specs
    for _ in range(2):
        repairable = []
        for spec in current:
            critique = (spec.metadata or {}).get("architecture_critique") or {}
            for item in critique.get("findings") or []:
                if item.get("severity") != "critical" or not item.get("auto_repairable"):
                    continue
                category = "governance" if item.get("category") == "missing_governance" else "architecture"
                repairable.append(
                    finding(
                        code=f"{category}.{item.get('category', 'critique')}",
                        severity="critical",
                        category=category,
                        title=item.get("issue") or "Architecture critique finding",
                        description=item.get("why_it_matters") or "",
                        evidence=[spec.mode],
                        auto_repairable=True,
                        repair_strategy=item.get("recommended_fix"),
                        customer_readiness_impact="cap_to_internal_only",
                    )
                )
        if not repairable:
            return current
        repaired, notes = repairer.repair(current, repairable)
        if not notes:
            return current
        current = await _attach_architecture_critiques(report, repaired, session_id)
        for spec in current:
            spec.metadata = {
                **spec.metadata,
                "architecture_repair_iterations": int(spec.metadata.get("architecture_repair_iterations") or 0) + 1,
                "architecture_repair_notes": list(dict.fromkeys((spec.metadata.get("architecture_repair_notes") or []) + notes)),
            }
    return current


def _understanding_from_report(report: ResearchReport) -> DeepUseCaseUnderstanding:
    payload = (report.metadata or {}).get("deep_understanding")
    if payload:
        try:
            return DeepUseCaseUnderstanding.model_validate(payload)
        except Exception:
            pass
    return deterministic_understanding(report.use_case_interpretation)


@router.get("/sessions/{session_id}/architecture")
async def get_architecture(session_id: str):
    specs = architecture_revisions.active_specs(session_id)
    if specs is None:
        raise HTTPException(status_code=404, detail="Architecture specs are not ready yet.")
    revisions = architecture_revisions.list(session_id)
    return {"architectures": specs, "revisions": revisions, "validation_issues": revisions[-1].validation_issues if revisions else []}


@router.get("/sessions/{session_id}/architecture/revisions")
async def get_architecture_revisions(session_id: str):
    _require_session(session_id)
    return {"revisions": architecture_revisions.list(session_id)}


@router.patch("/sessions/{session_id}/architecture")
async def update_architecture(session_id: str, request: UpdateArchitectureRequest):
    _require_session(session_id)
    try:
        revision = architecture_revisions.update(session_id, request.specs, request.reason)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    AuditLogger(session_id).event("architecture", "architecture_revision_saved", output_hash=hash_payload(revision.model_dump()))
    return {"revision": revision, "architectures": revision.specs, "revisions": architecture_revisions.list(session_id), "validation_issues": revision.validation_issues}


@router.post("/sessions/{session_id}/architecture/regenerate")
async def regenerate_architecture(session_id: str):
    _require_session(session_id)
    try:
        revision = architecture_revisions.duplicate_active_revision(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    AuditLogger(session_id).event("architecture", "architecture_revision_regenerated", output_hash=hash_payload(revision.model_dump()))
    return {"revision": revision, "architectures": revision.specs, "revisions": architecture_revisions.list(session_id), "validation_issues": revision.validation_issues}


@router.post("/sessions/{session_id}/diagrams/generate")
async def generate_diagrams(session_id: str):
    _require_session(session_id)
    active_specs = architecture_revisions.active_specs(session_id)
    if active_specs is None:
        raise HTTPException(status_code=409, detail="Generate architecture specs before diagrams.")
    repaired = architecture_revisions.ensure_governance(session_id)
    if repaired is not None:
        active_specs = repaired.specs
    issues = architecture_revisions.validate(active_specs)
    if any(issue.severity == "critical" for issue in issues):
        raise HTTPException(status_code=409, detail={"message": "Resolve critical architecture validation issues before generating diagrams.", "issues": [issue.model_dump(mode="json") for issue in issues]})
    specs = active_specs

    def work(job_id: str) -> str:
        adapter = DiagramCompilerAdapter()
        results: list[DiagramGalleryResult] = []
        total = max(1, len(specs))
        for index, spec in enumerate(specs, start=1):
            if job_manager.should_cancel(job_id):
                return "diagrams/gallery.json"
            job_manager.update(
                job_id,
                progress=10 + int(((index - 1) / total) * 80),
                message=f"Compiling {spec.mode.upper()} diagrams through the existing Archway compiler ({index}/{total}).",
            )
            if spec.mode == "poc":
                results.append(adapter.compile_poc_diagrams(spec, session_id))
            else:
                results.append(adapter.compile_production_diagrams(spec, session_id))
        job_manager.update(job_id, progress=92, message="Saving diagram gallery and artifact index.")
        gallery_path = artifacts.write_json(session_id, "diagrams", "gallery", [result.model_dump(mode="json") for result in results])
        current = _require_session(session_id)
        current.active_phase = SessionPhase.diagrams
        current.status = SessionStatus.complete
        store.save(current)
        return gallery_path

    job = job_manager.submit(session_id, "diagrams", work, "Diagram generation queued.")
    return {"job": job}


@router.get("/sessions/{session_id}/diagrams")
async def get_diagrams(session_id: str):
    galleries = _read_json(session_id, "diagrams/gallery.json")
    if galleries is None:
        raise HTTPException(status_code=404, detail="Diagram gallery is not ready yet.")
    return {"galleries": galleries}


@router.get("/sessions/{session_id}/jobs/{job_id}")
async def get_job(session_id: str, job_id: str):
    _require_session(session_id)
    try:
        job = job_manager.get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job was not found.")
    if job.session_id != session_id:
        raise HTTPException(status_code=404, detail="Job was not found.")
    return {"job": job}


@router.post("/sessions/{session_id}/jobs/{job_id}/cancel")
async def cancel_job(session_id: str, job_id: str):
    _require_session(session_id)
    try:
        job = job_manager.get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job was not found.")
    if job.session_id != session_id:
        raise HTTPException(status_code=404, detail="Job was not found.")
    return {"job": job_manager.cancel(job_id)}


@router.get("/sessions/{session_id}/artifacts/{artifact_id:path}")
async def get_artifact(session_id: str, artifact_id: str):
    _require_session(session_id)
    path = artifacts.resolve(session_id, artifact_id)
    return FileResponse(path)


@router.get("/sessions/{session_id}/diagnostics")
async def diagnostics(session_id: str):
    _require_session(session_id)
    return {"logs": read_session_logs(session_id), "health": await HealthService().check()}


@router.get("/sessions/{session_id}/export")
async def export_debug_bundle(session_id: str):
    session = _require_session(session_id)
    return {"session": session, "logs": read_session_logs(session_id), "artifacts_path": session.artifacts_path}


@router.post("/sessions/{session_id}/export/generate")
async def generate_export(session_id: str):
    _require_session(session_id)

    def work(job_id: str) -> str:
        bundle = ExportPackageService().generate(
            session_id,
            progress=lambda value, message: job_manager.update(job_id, progress=value, message=message),
        )
        job_manager.update(job_id, progress=96, message="Solution package is ready.")
        return bundle.artifact_id

    job = job_manager.submit(session_id, "export", work, "Export package queued.")
    return {"job": job}


@router.get("/sessions/{session_id}/export/package")
async def get_export_package(session_id: str):
    _require_session(session_id)
    latest = _latest_export_bundle(session_id)
    if latest is None:
        raise HTTPException(status_code=404, detail="Export package is not ready yet.")
    return {"export": latest}


def _require_session(session_id: str):
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session was not found.")
    return session


def _read_json(session_id: str, artifact_id: str):
    try:
        path = artifacts.resolve(session_id, artifact_id)
    except HTTPException:
        return None
    return __import__("json").loads(Path(path).read_text(encoding="utf-8"))


def _read_json_with_export_fallback(session_id: str, artifact_id: str, raw_export_name: str):
    payload = _read_json(session_id, artifact_id)
    if payload is not None:
        return payload
    root = artifacts.session_root(session_id) / "exports"
    raw_files = sorted(root.glob(f"archway-solution-package-*/raw/{raw_export_name}"), reverse=True)
    if not raw_files:
        return None
    return __import__("json").loads(raw_files[0].read_text(encoding="utf-8"))


def _latest_export_bundle(session_id: str):
    root = artifacts.session_root(session_id) / "exports"
    manifests = sorted(root.glob("archway-solution-package-*/manifest.json"), reverse=True)
    if not manifests:
        return None
    manifest = __import__("json").loads(manifests[0].read_text(encoding="utf-8"))
    zip_path = root / f"{manifest['name']}.zip"
    return {
        "name": manifest["name"],
        "artifact_id": artifacts.to_artifact_id(session_id, zip_path),
        "manifest_artifact_id": artifacts.to_artifact_id(session_id, manifests[0]),
        "included_artifacts": manifest.get("included_artifacts", []),
        "warnings": manifest.get("warnings", []),
    }


def _research_narrative(session_id: str, brief: dict | None, report: dict | None, pricing: dict | None, architectures: list[dict] | None, diagrams: list[dict] | None):
    if report is None:
        return None
    dossier = DeepDossierService().build(
        session_id=session_id,
        brief=brief,
        report=report,
        pricing=pricing,
        architectures=architectures,
        diagrams=diagrams,
    )
    sections = dossier.sections
    ordered_sections = [
        ("executive_verdict", "Executive verdict"),
        ("use_case_interpretation", "Use-case interpretation"),
        ("architecture_recommendation", "Recommended AWS direction"),
        ("service_decision_matrix", "Service selection rationale"),
        ("technical_feasibility", "Alternatives and trade-offs"),
        ("competitive_landscape", "Competitor / market scan"),
        ("risk_matrix", "Risks and assumptions"),
        ("pricing_analysis", "Pricing direction and drivers"),
        ("validation_plan", "Validation gates"),
        ("evidence_appendix", "Evidence appendix"),
    ]
    return {
        "executive_summary_markdown": DeepDossierService().executive_summary_markdown(dossier),
        "sections": [
            {"id": key, "title": title, "markdown": sections.get(key, "")}
            for key, title in ordered_sections
            if sections.get(key)
        ],
        "quality_score": dossier.quality_score.model_dump(mode="json"),
        "top_validation_gates": dossier.top_validation_gates,
    }


async def _apply_pricing_checkpoint_state(session_id: str, state: dict):
    session = _require_session(session_id)
    if session.current_summary is None:
        raise HTTPException(status_code=409, detail="This session does not have a brief yet.")
    report_data = _read_json(session_id, "research/report.json")
    if report_data is None:
        raise HTTPException(status_code=409, detail="Run research before pricing checkpoint.")
    report = ResearchReport.model_validate(report_data)
    overrides = {
        **(state.get("driver_values") or {}),
        "confirmed_driver_names": state.get("confirmed_driver_names") or [],
    }
    if state.get("scenario_profile_used"):
        overrides["scenario_profile_id"] = state["scenario_profile_used"]
    brief = session.current_summary.model_copy(deep=True)
    profile_metadata = dict(brief.use_case_profile or {})
    structured = dict(profile_metadata.get("structured_metrics") or {})
    structured["pricing_driver_overrides"] = overrides
    profile_metadata["structured_metrics"] = structured
    brief.use_case_profile = profile_metadata
    services = [
        item
        for item in report.aws_service_recommendations
    ]
    pricing = await PricingEngine().estimate(brief, services, pricing_driver_overrides=overrides)
    pricing_payload = pricing.model_dump(mode="json")
    artifacts.write_json(session_id, "pricing", "checkpoint_state", state)
    artifacts.write_json(session_id, "brief", "current", brief.model_dump(mode="json"))
    session.current_summary = brief
    store.save(session)
    artifacts.write_json(session_id, "pricing", "estimate", pricing_payload)
    artifacts.write_json(session_id, "pricing", "pricing_driver_closure", pricing.metadata.get("pricing_driver_closure") or {})
    report.pricing_analysis = pricing
    _refresh_report_customer_readiness(report)
    artifacts.write_json(session_id, "research", "report", report.model_dump(mode="json"))
    checkpoint = build_pricing_checkpoint(pricing_payload, session_id=session_id, state=state)
    return {"checkpoint": checkpoint, "pricing": pricing_payload, "report": report}


def _update_report_pricing(session_id: str, pricing: dict) -> None:
    report_data = _read_json(session_id, "research/report.json")
    if report_data is None:
        return
    report = ResearchReport.model_validate(report_data)
    report.pricing_analysis = report.pricing_analysis.__class__.model_validate(pricing)
    _refresh_report_customer_readiness(report)
    artifacts.write_json(session_id, "research", "report", report.model_dump(mode="json"))


def _refresh_report_customer_readiness(report: ResearchReport) -> None:
    metadata = report.metadata or {}
    customer_readiness = assess_customer_readiness(
        evidence_quality=metadata.get("evidence_quality") or {},
        citation_passed=bool(report.citation_coverage.passed if report.citation_coverage else False),
        service_decisions=metadata.get("service_decision_records") or [],
        pricing_unknowns=report.pricing_analysis.unknown_variables,
        pricing_status=report.pricing_analysis.metadata.get("status"),
        pricing_metadata=report.pricing_analysis.metadata,
        expected_views=(metadata.get("pricing_dimensions") or []),
    )
    report.metadata = {**metadata, "customer_readiness": customer_readiness.model_dump(mode="json")}
