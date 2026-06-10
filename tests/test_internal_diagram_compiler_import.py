"""Tests for the vendored (internal) diagram compiler import behavior.

The compiler was vendored from the external working tree into
packages/archway_diagram_compiler (see its SOURCE.md). Default runtime must
import the internal package; the external path env var is an explicit debug
fallback only and must never be used silently.
"""

import sys
from pathlib import Path

import pytest

import app.services.diagram_compiler_adapter as adapter_module
from app.models.domain import ArchitectureSpec, HealthStatus
from app.services.diagram_compiler_adapter import INTERNAL_COMPILER_SRC, DiagramCompilerAdapter

REPO_ROOT = Path(__file__).resolve().parents[1]
INTERNAL_PACKAGE_DIR = REPO_ROOT / "packages" / "archway_diagram_compiler" / "src"


def _imported_compiler_dir() -> Path:
    import archway_diagram_compiler

    return Path(archway_diagram_compiler.__file__).resolve().parent


# 1. Internal compiler imports without any external path.
def test_internal_diagram_compiler_imports_without_external_path(monkeypatch):
    adapter = DiagramCompilerAdapter()
    monkeypatch.setattr(adapter.settings, "diagram_compiler_path", None)
    adapter._ensure_import_path()
    assert adapter.compiler_source == "internal"
    assert INTERNAL_COMPILER_SRC == INTERNAL_PACKAGE_DIR
    assert _imported_compiler_dir().is_relative_to(INTERNAL_PACKAGE_DIR)


# 2. The adapter works end-to-end (health check) when the external env path is absent.
def test_external_compiler_path_not_required(monkeypatch):
    adapter = DiagramCompilerAdapter()
    monkeypatch.setattr(adapter.settings, "diagram_compiler_path", None)
    health = adapter.get_compiler_health()
    assert health.status == HealthStatus.ready
    assert health.details["diagram_compiler_source"] == "internal"
    assert str(INTERNAL_PACKAGE_DIR) in health.details["path"]


# 3. The crossing gate ships unchanged in the vendored package.
def test_compiler_quality_threshold_unchanged():
    DiagramCompilerAdapter()._ensure_import_path()
    from archway_diagram_compiler import quality_config

    assert quality_config.DEFAULT_QUALITY_CONFIG.logical_edge_crossing_max == 8
    assert Path(quality_config.__file__).resolve().is_relative_to(INTERNAL_PACKAGE_DIR)


# 4. Adapter reports internal source by default.
def test_diagram_compiler_adapter_uses_internal_source_by_default():
    adapter = DiagramCompilerAdapter()
    health = adapter.get_compiler_health()
    assert health.status == HealthStatus.ready
    assert adapter.compiler_source == "internal"
    assert health.details["diagram_compiler_source"] == "internal"


# 5. Smoke compile through the vendored compiler produces a diagram bundle.
def test_existing_diagram_compile_smoke():
    from app.services.pattern_catalog import (
        expected_views,
        observability_controls,
        pattern_components,
        pattern_flows,
        security_controls,
        semantic_views,
        service_recommendations,
    )
    from app.services.use_case_profile import profile_use_case
    from app.services.view_planner import diagram_view_mappings, semantic_to_compiler_mapping

    profile = profile_use_case(
        "We need a public web application with API, database, async jobs, observability, and CI/CD."
    )
    components = pattern_components(profile, production=True)
    flows = pattern_flows(profile, production=True, components=components)
    view_ids = semantic_views(profile, production=True)
    compiler_views = expected_views(profile, production=True)
    mappings = diagram_view_mappings(view_ids, "Internal Compiler Smoke")
    spec = ArchitectureSpec(
        session_id="sess_internal_compiler_smoke",
        mode="production",
        title="PRODUCTION Internal Compiler Smoke Architecture",
        summary="internal compiler smoke test",
        selected_services=service_recommendations(profile, evidence_ids=["ev_test"]),
        components=components,
        flows=flows,
        security_controls=security_controls(profile, production=True),
        observability_controls=observability_controls(profile, production=True),
        scaling_strategy="Scale from measured load.",
        resilience_strategy="Multi-AZ managed services.",
        cost_optimization_strategy="Validate measured drivers.",
        assumptions=[],
        risks=[],
        metadata={
            "semantic_views": view_ids,
            "expected_views": compiler_views,
            "requested_views": compiler_views,
            "semantic_to_compiler_view_mapping": semantic_to_compiler_mapping(view_ids),
            "diagram_view_mappings": [mapping.model_dump() for mapping in mappings],
        },
    )
    adapter = DiagramCompilerAdapter()
    result = adapter.compile_production_diagrams(spec, "sess_internal_compiler_smoke")
    assert adapter.compiler_source == "internal"
    assert result.diagrams, "compile must produce diagram artifacts"
    assert result.rendered_view_ids
    assert _imported_compiler_dir().is_relative_to(INTERNAL_PACKAGE_DIR)
    # D2 source artifacts are always produced; SVG requires the local d2 binary
    # (.tools/d2/d2 or PATH — see packages/archway_diagram_compiler/SOURCE.md).
    assert any("d2" in diagram.format_paths for diagram in result.diagrams)
    from archway_diagram_compiler.renderer import find_d2_executable

    if find_d2_executable() is not None:
        assert any("svg" in diagram.format_paths for diagram in result.diagrams), (
            "d2 binary is available but no SVG was rendered"
        )
        assert all(qa.passed for qa in result.qa_reports)


# 6. External override is explicit and visible — never the silent default.
def test_external_override_is_explicit(monkeypatch, tmp_path, caplog):
    adapter = DiagramCompilerAdapter()
    missing_internal = tmp_path / "missing_internal" / "src"
    external = tmp_path / "explicit_external"
    external.mkdir()
    monkeypatch.setattr(adapter_module, "INTERNAL_COMPILER_SRC", missing_internal)

    # Internal missing + explicit override set -> external_override, loudly.
    monkeypatch.setattr(adapter.settings, "diagram_compiler_path", external)
    with caplog.at_level("WARNING", logger="archway.diagram_compiler"):
        adapter._ensure_import_path()
    assert adapter.compiler_source == "external_override"
    assert any("external_override" in record.message for record in caplog.records)
    if str(external) in sys.path:
        sys.path.remove(str(external))

    # Internal missing + no override -> unavailable (never a silent iCloud default).
    fresh = DiagramCompilerAdapter()
    monkeypatch.setattr(fresh.settings, "diagram_compiler_path", None)
    fresh._ensure_import_path()
    assert fresh.compiler_source == "unavailable"
