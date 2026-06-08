import pytest

from app.core.config import get_settings
from app.db.session_store import SessionStore
from app.models.domain import DiagramArtifact, DiagramGalleryResult, DiagramQAReport
from app.services.architecture import ArchitecturePlanner
from app.services.architecture_revisions import ArchitectureRevisionService
from app.services.artifacts import ArtifactStore
from app.services.research import ResearchOrchestrator
from app.services.synthesis import SynthesisEngine


@pytest.mark.asyncio
async def test_completed_session_hydrates_saved_phase_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()

    import app.api.routes as routes

    routes.store = SessionStore()
    routes.artifacts = ArtifactStore()
    routes.architecture_revisions = ArchitectureRevisionService()

    brief = SynthesisEngine().create_initial_brief(
        "A hospital network needs AWS OR scheduling analytics with PHI protection, audit retention, and approval-gated workflow changes."
    )
    session = routes.store.create(brief.raw_use_case, brief)
    routes.artifacts.write_json(session.id, "brief", "current", brief.model_dump(mode="json"))

    report = await ResearchOrchestrator().run_research(brief, session.id)
    routes.artifacts.write_json(session.id, "research", "report", report.model_dump(mode="json"))
    routes.artifacts.write_json(session.id, "pricing", "estimate", report.pricing_analysis.model_dump(mode="json"))

    specs = ArchitecturePlanner().generate(report)
    routes.architecture_revisions.initialize(session.id, specs)
    gallery = DiagramGalleryResult(
        session_id=session.id,
        architecture_spec_id=specs[0].id,
        mode="poc",
        diagrams=[
            DiagramArtifact(
                id="diagram_test",
                title="Logical service flow",
                mode="poc",
                view_id="production_logical_service_flow",
                format_paths={"svg": "diagrams/poc/test/diagram.svg", "d2": "diagrams/poc/test/diagram.d2"},
                preview_svg_artifact_id="diagrams/poc/test/diagram.svg",
            )
        ],
        qa_reports=[DiagramQAReport(view_id="production_logical_service_flow", passed=True, diagnostics=[], metrics={})],
        rendered_view_ids=["production_logical_service_flow"],
    )
    routes.artifacts.write_json(session.id, "diagrams", "gallery", [gallery.model_dump(mode="json")])

    payload = await routes.hydrate_session(session.id)

    assert payload["session"].id == session.id
    assert payload["research"]["executive_verdict"]
    assert payload["research_narrative"]["sections"]
    view_model = payload["research_view_model"]
    assert view_model.executive_briefing.headline
    assert view_model.overview.use_case_interpretation
    assert view_model.architecture_rationale.service_groups
    assert view_model.pricing_poc.assumptions
    assert view_model.pricing_production.line_items
    assert view_model.competitor_scan.status in {"completed", "not_run", "skipped", "failed"}
    assert view_model.evidence_summary.top_sources
    assert all(source.debug_id is None for source in view_model.evidence_summary.top_sources)

    rendered = view_model.model_dump_json()
    assert "telemetry_frequency_seconds" not in rendered
    assert "asset_count" not in rendered
    assert "operating room" in rendered.lower()

    assert payload["architecture"]["architectures"]
    assert payload["architecture"]["revisions"]
    assert payload["diagrams"][0]["diagrams"][0]["title"] == "Logical service flow"
