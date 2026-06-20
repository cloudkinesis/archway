from zipfile import ZipFile

from app.core.config import get_settings
from app.db.session_store import SessionStore
from app.models.domain import AWSServiceRecommendation, PricingAnalysis, ResearchReport
from app.services.convergence.golden_convergence_orchestrator import _architecture_domain_contamination_findings
from app.services.architecture import ArchitecturePlanner
from app.services.export_package import ExportPackageService
from app.services.synthesis import SynthesisEngine


NOVEL_CUSTODY_TELEMETRY_USE_CASE = (
    "A museum consortium needs a live artifact transport custody platform. "
    "The system receives barcode scans from 120 venues, GPS courier updates every 10 seconds, "
    "Bluetooth humidity logger readings every 30 seconds, and restoration intake events across four conservation labs. "
    "It must detect custody gaps within 2 minutes, notify conservators and operations managers, preserve tamper-evident "
    "audit records for 7 years, show a live dashboard of delayed handoffs and SLA breaches, and keep donor PII out of model prompts."
)


def test_export_replays_agentic_audit_without_starting_live_lanes(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    monkeypatch.setenv("ARCHWAY_AGENTIC_MODE", "live_demo")
    for var in (
        "ARCHWAY_ENABLE_AGENTIC_RESEARCH",
        "ARCHWAY_ENABLE_AGENTIC_USE_CASE_ANALYST",
        "ARCHWAY_ENABLE_AGENTIC_PRICING",
        "ARCHWAY_ENABLE_AGENTIC_NARRATIVE",
        "ARCHWAY_ENABLE_AGENTIC_REVIEWER",
        "ARCHWAY_ENABLE_AGENTIC_DIAGRAM_PLANNER",
        "ARCHWAY_ENABLE_AGENTIC_ARCHITECTURE",
    ):
        monkeypatch.setenv(var, "true")
    get_settings.cache_clear()

    def explode(*_args, **_kwargs):
        raise AssertionError("export package generation must not start fresh live-agent providers")

    import app.services.agentic.architecture_candidate_agent as architecture_candidate_agent
    import app.services.agentic.diagram_planning_agent as diagram_planning_agent
    import app.services.agentic.narrative_agent as narrative_agent
    import app.services.agentic.pricing_dimension_agent as pricing_dimension_agent
    import app.services.agentic.research_agent as research_agent
    import app.services.agentic.reviewer_agent as reviewer_agent
    import app.services.agentic.use_case_analyst as use_case_analyst

    monkeypatch.setattr(use_case_analyst, "LiveUseCaseAnalystProvider", explode)
    monkeypatch.setattr(pricing_dimension_agent, "LivePricingDimensionProvider", explode)
    monkeypatch.setattr(research_agent, "LiveResearchProvider", explode)
    monkeypatch.setattr(narrative_agent, "LiveNarrativeProvider", explode)
    monkeypatch.setattr(reviewer_agent, "LiveReviewerProvider", explode)
    monkeypatch.setattr(diagram_planning_agent, "LiveDiagramPlanningProvider", explode)
    monkeypatch.setattr(architecture_candidate_agent, "LiveArchitectureCandidateProvider", explode)

    brief = SynthesisEngine().create_initial_brief("Build a retail assistant for order questions.")
    session = SessionStore().create("Build a retail assistant for order questions.", brief)
    service = ExportPackageService()

    bundle = service.generate(session.id)
    zip_path = service.artifacts.resolve(session.id, bundle.artifact_id)

    assert zip_path.is_file()
    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
    assert "raw/live_agent_calls.json" in names
    assert "raw/agent_use_case_analyst_trace.json" in names


def test_open_world_architecture_adds_senior_sa_topology_from_generic_signals():
    brief = SynthesisEngine().create_initial_brief(NOVEL_CUSTODY_TELEMETRY_USE_CASE)
    report = _minimal_report(brief)

    specs = ArchitecturePlanner().generate(report)
    production = next(spec for spec in specs if spec.mode == "production")
    roles = {component.metadata.get("role") for component in production.components}
    text = " ".join(
        [
            production.summary,
            production.scaling_strategy,
            production.resilience_strategy,
            production.cost_optimization_strategy,
            *(component.name for component in production.components),
            *(component.logical_group or "" for component in production.components),
            *(flow.label or "" for flow in production.flows),
        ]
    ).lower()

    assert "stream_ingestion" in roles
    assert "stream_rule_processor" in roles
    assert "privacy_boundary" in roles
    assert "immutable_evidence_archive" in roles
    assert "audit_event_ledger" in roles
    assert "operational_dashboard" in roles
    assert "enterprise_integration_adapter" in roles
    assert "donor pii" not in text
    assert "sensitive data boundary" in text
    assert "audit" in text
    assert "dashboard" in text
    assert "scored anomaly events" not in text
    assert "false positives" not in text
    assert "incident state" not in text
    assert "case state" not in text


def test_generic_approval_workflow_does_not_inherit_healthcare_or_topology():
    profile_metadata = {
        "domain": "agriculture",
        "workload_families": [
            "agentic_workflow",
            "real_time_anomaly_detection",
            "approval_gated_workflow_automation",
            "event_driven_workflow",
        ],
        "excluded_families": [],
        "capabilities": [
            "real_time_ingestion",
            "event_driven_workflow",
            "predictive_ml",
            "human_approval",
            "auditability",
            "sensitive_data",
        ],
        "entities": ["seed lots", "cold-room vaults", "shipments"],
        "signals": ["rfid scans", "freezer telemetry", "shipment handoff events"],
        "actions": ["quarantine recommendation", "curator approval"],
        "capability_model": ["stream_ingestion", "ml_inference", "human_approval", "audit_trail"],
        "deployment_posture": ["hybrid"],
        "confidence": "high",
        "understanding_authoritative": True,
    }
    brief = SynthesisEngine().create_initial_brief(NOVEL_CUSTODY_TELEMETRY_USE_CASE)
    brief.use_case_profile = profile_metadata
    report = _minimal_report(brief)

    specs = ArchitecturePlanner().generate(report)
    text = _spec_text(specs)

    assert "Epic" not in text
    assert "EHR" not in text
    assert "OR command" not in text
    assert "sterile processing" not in text
    assert "surgical" not in text
    assert "hospital" not in text.lower()
    assert "Operational Event Stream" in text
    assert "Governed recovery" in text or "Tool Governance Workflow" in text


def test_architecture_domain_contamination_blocks_unsupported_healthcare_leakage():
    brief = SynthesisEngine().create_initial_brief(NOVEL_CUSTODY_TELEMETRY_USE_CASE)
    report = _minimal_report(brief)
    spec = ArchitecturePlanner().generate(report)[0]
    contaminated = spec.model_copy(update={
        "summary": spec.summary + " Integrate with Epic / EHR and the OR command center for surgical scheduling.",
    })

    findings = _architecture_domain_contamination_findings(
        NOVEL_CUSTODY_TELEMETRY_USE_CASE,
        report.model_dump(mode="json"),
        [contaminated],
    )

    assert any(item.code == "architecture.healthcare_domain_contamination" for item in findings)
    finding = next(item for item in findings if item.code == "architecture.healthcare_domain_contamination")
    assert finding.severity == "critical"
    assert finding.customer_readiness_impact == "cap_to_internal_only"


def _minimal_report(brief):
    return ResearchReport(
        session_id="sess_d31_topology",
        executive_verdict="Proceed with a scoped candidate.",
        proceed_recommendation="proceed",
        use_case_interpretation=brief.refined_problem_statement,
        feasibility_analysis="Feasible with validation.",
        viability_analysis="Viable with assumptions.",
        competitor_analysis="Not assessed.",
        recommended_poc="Validate live telemetry ingestion, audit capture, dashboard freshness, and notification latency on a representative subset.",
        recommended_production_direction="Operate a governed real-time platform with explicit edge capture, privacy filtering, audit retention, and operational dashboards.",
        pricing_analysis=PricingAnalysis(
            region="us-east-1",
            low_monthly_usd=0,
            expected_monthly_usd=0,
            high_monthly_usd=0,
            line_items=[],
            main_cost_drivers=[],
            cost_optimization_recommendations=[],
            unknown_variables=[],
            evidence_items=[],
        ),
        aws_service_recommendations=[
            AWSServiceRecommendation(service="Amazon Kinesis Data Streams", purpose="Telemetry ingestion", rationale="Ingest real-time event streams."),
            AWSServiceRecommendation(service="Amazon DynamoDB", purpose="Operational state", rationale="Hold current handoff and dashboard state."),
            AWSServiceRecommendation(service="Amazon SNS", purpose="Notifications", rationale="Notify operators on SLA breaches."),
        ],
        risks=[],
        assumptions=brief.assumptions,
        evidence_items=[],
        evidence_assessments=[],
        facts=[],
        recommendations=[],
        uncertainties=[],
        metadata={"use_case_profile": brief.use_case_profile},
    )


def _spec_text(specs) -> str:
    chunks: list[str] = []
    for spec in specs:
        chunks.extend(
            [
                spec.title,
                spec.summary,
                *(component.name for component in spec.components),
                *(component.service for component in spec.components),
                *(flow.label or "" for flow in spec.flows),
                *(rec.service for rec in spec.selected_services),
                *(rec.purpose for rec in spec.selected_services),
            ]
        )
    return "\n".join(chunks)
