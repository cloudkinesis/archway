from zipfile import ZipFile

from app.core.config import get_settings
from app.db.session_store import SessionStore
from app.services.export_package import ExportPackageService, _await_or_none
from app.services.synthesis import SynthesisEngine


def test_export_package_contains_core_files(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    store = SessionStore()
    brief = SynthesisEngine().create_initial_brief("Build a retail assistant for order questions.")
    session = store.create("Build a retail assistant for order questions.", brief)
    service = ExportPackageService()

    bundle = service.generate(session.id)
    zip_path = service.artifacts.resolve(session.id, bundle.artifact_id)

    assert zip_path.is_file()
    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
    assert "README.md" in names
    assert "01-solution-brief.md" in names
    assert "02A-executive-summary.md" in names
    assert "02B-deep-research-dossier.md" in names
    assert "02C-claim-register.md" in names
    assert "02D-evidence-map.md" in names
    assert "02E-consistency-check.md" in names
    assert "10-quality-and-repair-summary.md" in names
    assert "11-pricing-trace.md" in names
    assert "12-source-policy.md" in names
    assert "raw/session.json" in names
    assert "raw/deep_research_dossier.json" in names
    assert "raw/research_claims.json" in names
    assert "raw/claim_evidence_map.json" in names
    assert "raw/dossier_consistency_check.json" in names
    assert "raw/dossier_quality_score.json" in names
    assert "raw/llm_call_telemetry.json" in names
    assert "raw/deep_use_case_understanding.json" in names
    assert "raw/understanding_validation.json" in names
    assert "raw/understanding_conflicts.json" in names
    assert "raw/pricing_sanity_review.json" in names
    assert "raw/canonical_facts.json" in names
    assert "raw/assumption_ledger.json" in names
    assert "raw/pricing_driver_bindings.json" in names
    assert "raw/service_usage_dimensions.json" in names
    assert "raw/aws_rate_bindings.json" in names
    assert "raw/pricing_ledger.json" in names
    assert "raw/readiness_report.json" in names
    assert "raw/source_policy.json" in names
    assert "raw/architecture_critiques.json" in names
    assert "raw/golden_convergence_result.json" in names
    assert "raw/quality_findings.json" in names
    assert "raw/repair_plan.json" in names
    assert "raw/customer_readiness.json" in names
    assert "manifest.json" in names


def test_export_package_includes_architecture_revisions(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    store = SessionStore()
    brief = SynthesisEngine().create_initial_brief("Build a retail assistant for order questions.")
    session = store.create("Build a retail assistant for order questions.", brief)
    artifact_store = ExportPackageService().artifacts
    artifact_store.write_json(session.id, "architecture", "specs", [{"mode": "poc", "title": "POC", "summary": "Scoped", "security_controls": [], "observability_controls": []}])
    artifact_store.write_json(session.id, "architecture", "revisions", [{"version": 1, "reason": "Generated", "validation_issues": []}])

    bundle = ExportPackageService().generate(session.id)
    zip_path = artifact_store.resolve(session.id, bundle.artifact_id)

    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        architecture_markdown = archive.read("04-architecture.md").decode("utf-8")
    assert "raw/architecture_revisions.json" in names
    assert "Revision 1: Generated" in architecture_markdown


def test_export_package_skips_unsafe_diagram_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    store = SessionStore()
    brief = SynthesisEngine().create_initial_brief("Build a retail assistant for order questions.")
    session = store.create("Build a retail assistant for order questions.", brief)
    artifact_store = ExportPackageService().artifacts
    artifact_store.write_json(
        session.id,
        "diagrams",
        "gallery",
        [
            {
                "mode": "poc",
                "diagrams": [
                    {
                        "title": "Unsafe",
                        "view_id": "unsafe",
                        "format_paths": {"svg": "../secret.svg"},
                    }
                ],
            }
        ],
    )

    bundle = ExportPackageService().generate(session.id)

    assert any("unsafe diagram artifact path" in warning for warning in bundle.warnings)


def test_export_package_preserves_diagram_artifact_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    store = SessionStore()
    brief = SynthesisEngine().create_initial_brief("Build a retail assistant for order questions.")
    session = store.create("Build a retail assistant for order questions.", brief)
    artifact_store = ExportPackageService().artifacts
    artifact_path = artifact_store.session_root(session.id) / "diagrams/poc/service_flow/diagram.svg"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("<svg></svg>", encoding="utf-8")
    artifact_store.write_json(
        session.id,
        "diagrams",
        "gallery",
        [
            {
                "mode": "poc",
                "diagrams": [
                    {
                        "title": "Service Flow",
                        "view_id": "service_flow",
                        "format_paths": {"svg": "diagrams/poc/service_flow/diagram.svg"},
                    }
                ],
                "qa_reports": [{"view_id": "service_flow", "passed": True, "diagnostics": [], "metrics": {}}],
            }
        ],
    )

    bundle = ExportPackageService().generate(session.id)
    zip_path = artifact_store.resolve(session.id, bundle.artifact_id)

    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
    assert "raw/diagram_gallery.json" in names
    assert "diagrams/poc/service_flow/diagram.svg" in names


def test_async_optional_export_collection_degrades_inside_running_loop():
    async def sample():
        return {"ok": True}

    async def run_inside_loop():
        warnings = []
        value = _await_or_none(sample(), warnings, "sample")
        return value, warnings

    import asyncio

    value, warnings = asyncio.run(run_inside_loop())

    assert value is None
    assert "already running inside an event loop" in warnings[0]
