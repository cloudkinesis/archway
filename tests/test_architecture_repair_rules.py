from __future__ import annotations
from app.domain.quality_findings import finding, QualityFinding
from app.models.domain import ArchitectureSpec, ArchitectureComponent, ArchitectureFlow, SecurityControl, ObservabilityControl
from app.services.convergence.architecture_repairer import ArchitectureRepairer

def _spec(components, flows=None, mode="production"):
    return ArchitectureSpec(
        session_id="test_session",
        mode=mode,
        title=f"{mode.title()} architecture",
        summary="Test summary",
        selected_services=[],
        components=components,
        flows=flows or [],
        security_controls=[],
        observability_controls=[],
        scaling_strategy="Use managed autoscaling.",
        resilience_strategy="Use managed multi-AZ durability.",
        cost_optimization_strategy="Start with on-demand usage.",
        assumptions=[],
        risks=[],
    )

def test_private_connectivity_repair_rule():
    spec = _spec(
        components=[
            ArchitectureComponent(
                id="external_source",
                name="External Feeds",
                service="External",
                scope="external_actor"
            )
        ],
        mode="production"
    )
    findings = [
        finding(
            code="missing_connectivity",
            severity="warning",
            category="architecture",
            title="Missing Connectivity",
            description="The architecture has no private connectivity to external systems."
        )
    ]
    repairer = ArchitectureRepairer()
    repaired, notes = repairer.repair([spec], findings)
    
    assert len(repaired) == 1
    assert any("Direct Connect" in c.service for c in repaired[0].components)
    assert any("private connectivity" in note.lower() for note in notes)


def test_observability_repair_rule():
    spec = _spec(
        components=[
            ArchitectureComponent(
                id="app_server",
                name="Application Server",
                service="Amazon EC2",
                scope="vpc_resident"
            )
        ],
        mode="production"
    )
    findings = [
        finding(
            code="missing_logging",
            severity="warning",
            category="architecture",
            title="Missing Observability",
            description="The architecture lacks centralized CloudWatch logs."
        )
    ]
    repairer = ArchitectureRepairer()
    repaired, notes = repairer.repair([spec], findings)
    
    assert len(repaired) == 1
    assert any("CloudWatch" in c.service for c in repaired[0].components)
    assert any("logging" in note.lower() for note in notes)
