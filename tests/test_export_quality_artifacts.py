"""Tests for export quality-artifact reliability.

Covers: no event-loop warnings, explicit quality-artifact status records instead
of bare "missing optional artifact: quality/*" warnings, deduplicated warnings,
fail-closed customer readiness, and continued presence of core export files.
"""

import asyncio
import json
from zipfile import ZipFile

from app.core.config import get_settings
from app.db.session_store import SessionStore
from app.services.export_package import ExportPackageService
from app.services.synthesis import SynthesisEngine

_ALLOWED_STATUSES = {"present", "skipped", "deferred", "not_applicable", "failed"}
_EVENT_LOOP_PHRASES = ("already running inside an event loop", "asyncio.run() cannot be called", "cannot be called from a running event loop")


def _make_session(use_case="Build a retail assistant for order questions."):
    brief = SynthesisEngine().create_initial_brief(use_case)
    return SessionStore().create(use_case, brief)


def _latest_manifest(service: ExportPackageService, session_id: str) -> dict:
    root = service.artifacts.session_root(session_id) / "exports"
    manifest = sorted(root.glob("*/manifest.json"))[-1]
    return json.loads(manifest.read_text(encoding="utf-8"))


def _quality_missing_warnings(warnings):
    return [w for w in warnings if w.startswith("Missing optional artifact: quality/")]


def _event_loop_warnings(warnings):
    return [w for w in warnings if any(p in w for p in _EVENT_LOOP_PHRASES)]


def test_export_does_not_emit_event_loop_warning(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    session = _make_session()

    async def run_inside_loop():
        return ExportPackageService().generate(session.id)

    bundle = asyncio.run(run_inside_loop())

    assert _event_loop_warnings(bundle.warnings) == []
    # Quality artifacts were collected (convergence ran loop-safely), not deferred.
    manifest = _latest_manifest(ExportPackageService(), session.id)
    assert manifest["quality_artifact_status"]["golden_convergence"]["status"] in _ALLOWED_STATUSES
    assert manifest["quality_artifact_status"]["golden_convergence"]["status"] != "deferred"


def test_missing_quality_artifacts_get_status_records(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    session = _make_session()

    async def run_inside_loop():
        return ExportPackageService().generate(session.id)

    bundle = asyncio.run(run_inside_loop())

    # No bare "Missing optional artifact: quality/*" warnings.
    assert _quality_missing_warnings(bundle.warnings) == []

    manifest = _latest_manifest(ExportPackageService(), session.id)
    status = manifest["quality_artifact_status"]
    for key in ("golden_convergence", "build_status", "customer_readiness", "quality_findings", "repair_plan", "golden_convergence_result", "diagram_qa", "pricing_headline_safety", "pricing_readiness"):
        assert key in status, f"missing status entry: {key}"
        assert status[key]["status"] in _ALLOWED_STATUSES


def test_warnings_are_deduplicated(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    session = _make_session()
    bundle = ExportPackageService().generate(session.id)

    # No warning is repeated.
    assert len(bundle.warnings) == len(set(bundle.warnings))
    # Specifically, quality artifacts are never listed as repeated missing warnings.
    assert _quality_missing_warnings(bundle.warnings) == []


def test_readiness_fails_closed_when_not_computed(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    session = _make_session()
    service = ExportPackageService()
    root = service.artifacts.ensure_layout(session.id)

    # Simulate the case where convergence could not run: no precomputed quality artifacts.
    payloads, records = service._collect_quality_artifacts(session.id, root, "failed", "ArchitectureError: boom")

    readiness = payloads["customer_readiness"]
    assert readiness["computed"] is False
    assert readiness["customer_ready"] is False
    assert readiness["procurement_ready"] is False
    assert readiness["status"] == "directional_only"

    # Other quality artifacts carry an explicit failed status (not a missing warning).
    assert records["golden_convergence_result"]["status"] == "failed"
    assert records["quality_findings"]["status"] == "failed"
    # And placeholders were persisted to the session quality dir.
    assert (root / "quality" / "customer_readiness.json").is_file()
    assert (root / "quality" / "golden_convergence_result.json").is_file()


def test_readiness_placeholder_is_not_customer_ready_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    session = _make_session()
    service = ExportPackageService()
    root = service.artifacts.ensure_layout(session.id)

    for status in ("deferred", "failed"):
        payloads, _ = service._collect_quality_artifacts(session.id, root, status, "reason")
        # Even a placeholder must never imply customer/procurement readiness.
        assert payloads["customer_readiness"]["customer_ready"] is False
        assert payloads["customer_readiness"]["procurement_ready"] is False


def test_export_still_includes_core_files(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    session = _make_session()
    service = ExportPackageService()
    # Provide core artifacts so the export carries brief/architecture/diagram content.
    service.artifacts.write_json(session.id, "brief", "current", {"title": "Retail assistant", "refined_problem_statement": "x", "assumptions": [], "open_questions": []})
    service.artifacts.write_json(session.id, "architecture", "specs", [{"mode": "poc", "title": "POC", "summary": "Scoped", "security_controls": [], "observability_controls": []}])
    service.artifacts.write_json(session.id, "architecture", "revisions", [{"version": 1, "reason": "Generated", "validation_issues": []}])

    bundle = service.generate(session.id)
    zip_path = service.artifacts.resolve(session.id, bundle.artifact_id)
    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())

    for required in (
        "README.md",
        "01-solution-brief.md",
        "02-research-report.md",
        "03-pricing.md",
        "04-architecture.md",
        "05-diagrams.md",
        "07-diagnostics.md",
        "10-quality-and-repair-summary.md",
        "raw/session.json",
        "raw/customer_readiness.json",
        "raw/golden_convergence_result.json",
        "raw/quality_findings.json",
        "raw/repair_plan.json",
        "raw/quality_artifact_status.json",
        "manifest.json",
    ):
        assert required in names, f"core export file missing: {required}"

    manifest = _latest_manifest(service, session.id)
    assert "quality_artifact_status" in manifest
    assert _event_loop_warnings(manifest["warnings"]) == []
