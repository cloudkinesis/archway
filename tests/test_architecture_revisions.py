from app.core.config import get_settings
from app.models.domain import (
    ArchitectureComponent,
    ArchitectureFlow,
    ArchitectureSpec,
    ObservabilityControl,
    SecurityControl,
)
from app.models.schemas import ArchitectureSpecPatch
from app.services.architecture_revisions import ArchitectureRevisionService


def test_architecture_revisions_preserve_history_and_active_specs(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    service = ArchitectureRevisionService()
    specs = [_spec("session-1", "poc")]

    initial = service.initialize("session-1", specs)
    updated = service.update(
        "session-1",
        {"poc": ArchitectureSpecPatch(summary="Edited summary", security_controls=[{"name": "KMS encryption", "rationale": "Protect data at rest."}])},
        "Tighten POC security",
    )

    assert initial.version == 1
    assert updated.version == 2
    assert len(service.list("session-1")) == 2
    assert service.active_specs("session-1")[0].summary == "Edited summary"
    assert service.active_specs("session-1")[0].security_controls[0].name == "KMS encryption"


def test_architecture_validation_flags_unresolved_effectful_flow_governance(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    service = ArchitectureRevisionService()
    spec = _spec("session-2", "production")
    spec.flows = [ArchitectureFlow(id="write", source="api", target="db", label="Write customer update")]
    spec.security_controls = [SecurityControl(name="KMS encryption", rationale="Protect data at rest.")]

    issues = service.validate([spec])

    assert any(issue.code == "write_without_governance" and issue.severity == "critical" for issue in issues)


def test_architecture_initialize_auto_adds_typed_governance_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    service = ArchitectureRevisionService()
    spec = _spec("session-3", "production")
    spec.flows = [ArchitectureFlow(id="dispatch", source="events", target="workflow", label="Dispatch field crew")]
    spec.security_controls = [SecurityControl(name="KMS encryption", rationale="Protect data at rest.")]

    revision = service.initialize("session-3", [spec])

    enriched = revision.specs[0]
    assert not [issue for issue in revision.validation_issues if issue.severity == "critical"]
    assert any(control.control_type == "human_approval" and "dispatch" in control.governed_flow_ids for control in enriched.governance_controls)
    assert any(control.control_type == "manual_override" and "dispatch" in control.governed_flow_ids for control in enriched.governance_controls)
    assert enriched.flows[0].metadata["action_type"] == "dispatch"


def _spec(session_id: str, mode: str) -> ArchitectureSpec:
    return ArchitectureSpec(
        session_id=session_id,
        mode=mode,
        title=f"{mode.title()} architecture",
        summary="Initial summary",
        selected_services=[],
        components=[
            ArchitectureComponent(id="api", name="API", service="Amazon API Gateway"),
            ArchitectureComponent(id="db", name="Data", service="Amazon DynamoDB"),
        ],
        flows=[ArchitectureFlow(id="read", source="api", target="db", label="Read lookup")],
        security_controls=[
            SecurityControl(name="KMS encryption", rationale="Protect data at rest."),
            SecurityControl(name="Human approval", rationale="Required before governed writes."),
        ],
        observability_controls=[ObservabilityControl(name="CloudWatch logs", rationale="Audit requests and failures.")],
        scaling_strategy="Use managed autoscaling.",
        resilience_strategy="Use managed multi-AZ durability.",
        cost_optimization_strategy="Start with on-demand usage.",
        assumptions=[],
        risks=[],
    )
