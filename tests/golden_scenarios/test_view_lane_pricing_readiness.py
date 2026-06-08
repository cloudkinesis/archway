from app.domain.capabilities import ArchitectureCapability
from app.models.domain import CitationCoverageReport, EvidenceItem
from app.services.customer_readiness import CustomerReadinessStatus, assess_customer_readiness
from app.services.evidence_quality import summarize_evidence_quality
from app.services.lane_planner import plan_lanes
from app.services.pattern_catalog import pattern_components
from app.services.pricing import derive_industrial_iot_pricing_model
from app.services.use_case_profile import profile_use_case
from app.services.view_planner import plan_semantic_views
from tests.golden_scenarios.scenarios import UTILITY_GRID


def test_view_planner_emits_industrial_iot_views_without_rag():
    profile = profile_use_case(UTILITY_GRID)
    views = plan_semantic_views(profile.capability_model, production=True, network_required=True)

    assert "telemetry_ingestion_view" in views
    assert "stream_processing_view" in views
    assert "predictive_failure_detection_view" in views
    assert "dispatch_workflow_view" in views
    assert "data_lake_model_lifecycle_view" in views
    assert "security_observability_view" in views
    assert "network_private_connectivity_view" in views
    assert "rag_retrieval_view" not in views
    assert "rag_ingestion_view" not in views


def test_lane_planner_uses_semantic_lanes_not_chatbot_lanes():
    profile = profile_use_case(UTILITY_GRID)
    components = pattern_components(profile, production=True)
    lane_plan = plan_lanes(profile.capability_model, components)
    labels = {lane.label for lane in lane_plan.lanes}

    assert "Sources and edge" in labels
    assert "Telemetry ingestion" in labels
    assert "Streaming analytics" in labels
    assert "Prediction and scoring" in labels
    assert "Workflow and integrations" in labels
    assert "Data and model lifecycle" in labels
    assert "Observability and audit" in labels
    assert "Source Documents" not in labels
    assert "Model Invocation" not in labels


def test_industrial_iot_pricing_does_not_price_everything_from_raw_events():
    profile = profile_use_case(UTILITY_GRID)
    model = derive_industrial_iot_pricing_model(profile)

    assert model.telemetry.asset_count == 215000
    assert model.telemetry.daily_raw_event_volume == 309600000
    assert model.ml_scoring.scoring_events_per_day != model.telemetry.daily_raw_event_volume
    assert model.workflow.dispatch_workflow_executions_per_day != model.telemetry.daily_raw_event_volume
    assert model.ml_scoring.scoring_strategy == "score_aggregated_windows"


def test_local_policy_evidence_keeps_customer_readiness_directional():
    evidence = [
        EvidenceItem(source_type="local_policy", title="Local", quote_or_summary="Local assumption.", confidence="medium"),
        EvidenceItem(source_type="user_input", title="User", quote_or_summary="User input.", confidence="high"),
    ]
    quality = summarize_evidence_quality(evidence, CitationCoverageReport(total_claims=1, cited_claims=1, uncited_claims=0, coverage_percent=100, passed=False))
    readiness = assess_customer_readiness(
        evidence_quality=quality.model_dump(),
        citation_passed=False,
        service_decisions=[],
        pricing_unknowns=["confirmed payload size"],
    )

    assert quality.evidence_authority == "limited"
    assert readiness.status == CustomerReadinessStatus.DIRECTIONAL_ONLY
    assert readiness.blockers


def test_official_web_fallback_evidence_is_citable_but_not_customer_ready():
    evidence = [
        EvidenceItem(
            source_type="aws_docs",
            title="AWS docs fallback",
            quote_or_summary="Official AWS docs result.",
            tool_name="AWS Documentation official web fallback",
            confidence="medium",
        ),
        EvidenceItem(
            source_type="aws_pricing",
            title="AWS pricing fallback",
            quote_or_summary="Official AWS pricing page.",
            tool_name="AWS Pricing official web fallback",
            confidence="medium",
        ),
    ]
    quality = summarize_evidence_quality(
        evidence,
        CitationCoverageReport(total_claims=2, cited_claims=2, uncited_claims=0, coverage_percent=100, passed=True),
    )
    readiness = assess_customer_readiness(
        evidence_quality=quality.model_dump(),
        citation_passed=True,
        service_decisions=[],
        pricing_unknowns=[],
    )

    assert quality.evidence_authority == "mixed"
    assert quality.customer_ready is False
    assert readiness.status == CustomerReadinessStatus.DIRECTIONAL_ONLY
    assert not readiness.blockers
    assert readiness.warnings
