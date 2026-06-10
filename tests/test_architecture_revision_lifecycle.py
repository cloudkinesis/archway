"""Lifecycle tests for architecture revisions.

Covers the fix for the silent-no-op regeneration bug: ``record_generation``
must always append a new revision (so re-generating updates the active specs),
prior revisions stay accessible, and the active revision / diagram source always
points at the newest generated specs (no stale specs).
"""

from app.core.config import get_settings
from app.models.domain import (
    ArchitectureComponent,
    ArchitectureFlow,
    ArchitectureSpec,
    ObservabilityControl,
    SecurityControl,
)
from app.services.architecture_revisions import ArchitectureRevisionService


def _spec(session_id: str, mode: str, summary: str) -> ArchitectureSpec:
    return ArchitectureSpec(
        session_id=session_id,
        mode=mode,
        title=f"{mode.title()} architecture",
        summary=summary,
        selected_services=[],
        components=[
            ArchitectureComponent(id="api", name="API", service="Amazon API Gateway"),
            ArchitectureComponent(id="db", name="Data", service="Amazon DynamoDB"),
        ],
        flows=[ArchitectureFlow(id="read", source="api", target="db", label="Read lookup")],
        security_controls=[SecurityControl(name="KMS encryption", rationale="Protect data at rest.")],
        observability_controls=[ObservabilityControl(name="CloudWatch logs", rationale="Audit requests.")],
        scaling_strategy="Use managed autoscaling.",
        resilience_strategy="Use managed multi-AZ durability.",
        cost_optimization_strategy="Start with on-demand usage.",
        assumptions=[],
        risks=[],
    )


def test_record_generation_appends_new_revision_and_updates_active(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    service = ArchitectureRevisionService()
    sid = "sess_gen"

    first = service.record_generation(sid, [_spec(sid, "poc", "GEN-1 specs")])
    assert first.version == 1
    assert service.active_specs(sid)[0].summary == "GEN-1 specs"

    # Re-generating with different specs must append, not no-op.
    second = service.record_generation(sid, [_spec(sid, "poc", "GEN-2 specs")])
    assert second.version == 2
    assert len(service.list(sid)) == 2

    # Active revision points to the NEWEST generated specs (no stale specs).
    assert service.active_specs(sid)[0].summary == "GEN-2 specs"

    # The persisted specs.json (what the diagram phase reads via active_specs) is current.
    assert service.list(sid)[-1].specs[0].summary == "GEN-2 specs"


def test_prior_revisions_remain_accessible_after_regeneration(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    service = ArchitectureRevisionService()
    sid = "sess_history"

    service.record_generation(sid, [_spec(sid, "poc", "GEN-1 specs")])
    service.record_generation(sid, [_spec(sid, "poc", "GEN-2 specs")])
    service.record_generation(sid, [_spec(sid, "poc", "GEN-3 specs")])

    revisions = service.list(sid)
    assert [r.version for r in revisions] == [1, 2, 3]
    # All historical specs are still retrievable.
    assert [r.specs[0].summary for r in revisions] == ["GEN-1 specs", "GEN-2 specs", "GEN-3 specs"]
    # Active is the latest.
    assert service.active_specs(sid)[0].summary == "GEN-3 specs"


def test_active_specs_is_diagram_source_and_never_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    service = ArchitectureRevisionService()
    sid = "sess_diagram_source"

    service.record_generation(sid, [_spec(sid, "poc", "OLD specs")])
    service.record_generation(sid, [_spec(sid, "production", "NEW specs")])

    # The diagram phase compiles from active_specs(); it must be the newest revision.
    active = service.active_specs(sid)
    assert active is not None
    assert active[0].summary == "NEW specs"
    assert active[0].mode == "production"
    # Newest revision matches active (the diagram source) exactly.
    assert service.list(sid)[-1].specs[0].summary == active[0].summary


def test_initialize_remains_idempotent_first_time_only(tmp_path, monkeypatch):
    # initialize() keeps its idempotent contract (used elsewhere for first-time setup):
    # it must NOT overwrite an existing revision.
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    service = ArchitectureRevisionService()
    sid = "sess_init"

    first = service.initialize(sid, [_spec(sid, "poc", "INIT specs")])
    again = service.initialize(sid, [_spec(sid, "poc", "SHOULD-BE-IGNORED")])

    assert first.version == 1
    assert again.version == 1
    assert len(service.list(sid)) == 1
    assert service.active_specs(sid)[0].summary == "INIT specs"


def test_duplicate_active_revision_copies_without_rederiving(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    service = ArchitectureRevisionService()
    sid = "sess_dup"

    service.record_generation(sid, [_spec(sid, "poc", "BASE specs")])
    duplicated = service.duplicate_active_revision(sid)

    assert duplicated.version == 2
    assert duplicated.specs[0].summary == "BASE specs"  # a copy, not a re-derivation
    assert duplicated.specs[0].metadata.get("duplicated_from_active") is True

    # Backward-compatible alias behaves identically.
    via_alias = service.regenerate_from_active(sid)
    assert via_alias.version == 3
    assert via_alias.specs[0].metadata.get("duplicated_from_active") is True


def test_duplicate_active_revision_requires_existing_specs(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    service = ArchitectureRevisionService()
    with pytest.raises(ValueError):
        service.duplicate_active_revision("sess_empty")
