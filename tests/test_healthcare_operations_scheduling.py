import pytest

from app.core.config import get_settings
from app.models.domain import ArchitectureSpec
from app.services.diagram_compiler_adapter import _missing_requested_views
from app.services.pricing import PricingEngine
from app.services.pricing_driver_selector import PricingDriverFamily, select_pricing_driver_family
from app.services.architecture_revisions import ArchitectureRevisionService
from app.services.pattern_catalog import (
    expected_views,
    observability_controls,
    pattern_components,
    pattern_flows,
    poc_scope,
    production_scope,
    security_controls,
    service_recommendations,
)
from app.services.synthesis import SynthesisEngine
from app.services.use_case_profile import profile_from_metadata, profile_use_case


HOSPITAL_OR_USE_CASE = """
A large hospital network wants to build an AI-powered operating room utilization and surgical delay prediction platform across
18 hospitals and 240 operating rooms. The platform ingests real-time OR schedule data, patient check-in status, anesthesia
readiness, surgical team availability, sterile instrument tray tracking, room turnover timestamps, and video-derived room
occupancy signals from ceiling cameras. The system predicts whether each scheduled surgery will start late, finish late, or
require room reassignment, and recommends schedule adjustments to reduce idle OR time and avoid downstream cancellations. It
must integrate with Epic for patient/surgery schedule data, the hospital's nurse staffing system, sterile processing inventory,
and the existing OR command center dashboard. Predictions must refresh every 2 minutes, but final schedule changes require human
approval from the OR charge nurse or command center supervisor. The platform must protect PHI, comply with HIPAA, retain audit
logs for 7 years, and avoid storing identifiable patient video unless explicitly approved.
"""


def test_hospital_or_use_case_routes_to_healthcare_operations_not_iot_or_field_service():
    profile = profile_use_case(HOSPITAL_OR_USE_CASE)

    assert profile.domain == "healthcare"
    assert profile.workload_families[:3] == [
        "healthcare_operations_scheduling",
        "surgical_scheduling_prediction",
        "clinical_workflow_decision_support",
    ]
    assert "industrial_iot_streaming_ml" in profile.excluded_families
    assert "field_service_automation" in profile.excluded_families
    assert "computer_vision_quality_inspection" in profile.excluded_families

    services = service_recommendations(profile, evidence_ids=["ev_test"])
    service_names = {item.service for item in services}

    assert "AWS IoT Core" not in service_names
    assert "AWS IoT SiteWise / time-series storage decision" not in service_names
    assert "AWS Outposts" not in service_names
    assert "External workforce management system" not in service_names
    assert "External depot inventory system" not in service_names
    assert "External Epic / EHR system" in service_names
    assert "External OR command center" in service_names
    assert "AWS Step Functions" in service_names
    assert select_pricing_driver_family(profile) == PricingDriverFamily.HEALTHCARE_OPERATIONS_SCHEDULING


def test_interview_answers_are_promoted_to_canonical_healthcare_profile():
    engine = SynthesisEngine()
    brief = engine.create_initial_brief("A hospital wants to improve operating room utilization and surgical scheduling.")

    answers = [
        "Charge nurse approval is required before any schedule change is written.",
        "Epic is authoritative; staffing, sterile processing, room turnover, and occupancy metadata arrive as near-real-time feeds.",
        "No patient-identifiable video should be stored; only ephemeral occupancy metadata is allowed.",
        "Predictions must refresh in under 2 minutes for the OR command center.",
    ]
    for answer in answers:
        brief = engine.respond(brief, answer).brief

    profile = profile_from_metadata(brief.use_case_profile, brief.raw_use_case)

    assert profile.workload_families[0] == "healthcare_operations_scheduling"
    assert "field_service_automation" not in profile.workload_families
    assert "industrial_iot_streaming_ml" not in profile.workload_families
    assert "approval_gated_workflow" in profile.capabilities
    assert "video_metadata_processing" in profile.capabilities


def test_healthcare_operations_architecture_has_governed_clinical_flows_without_critical_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    profile = profile_use_case(HOSPITAL_OR_USE_CASE)
    components = pattern_components(profile, production=True)
    flows = pattern_flows(profile, production=True, components=components)
    service_names = {component.name for component in components}

    assert "Epic / EHR System" in service_names
    assert "Existing OR Command Center Dashboard" in service_names
    assert "PHI-safe Operational Store" in service_names
    assert "Occupancy Metadata Processor" in service_names
    assert "Proposed Schedule Change Store" in service_names
    assert "Action Policy Evaluator" in service_names
    assert "Approved Writeback Adapter" in service_names
    assert any(flow.metadata.get("classification") == "external_write" for flow in flows)
    assert any(flow.metadata.get("classification") == "human_approval" for flow in flows)
    ehr_writeback = next(flow for flow in flows if flow.target == "ehr" and flow.metadata.get("classification") == "external_write")
    assert ehr_writeback.metadata["governance_mode"] == "approval_required"
    assert ehr_writeback.metadata["action_type"] == "ehr_writeback"
    assert ehr_writeback.metadata["external_write"] is True
    assert ehr_writeback.metadata["approval_required"] is True
    assert ehr_writeback.metadata["approver_role"] == "charge_nurse"
    assert ehr_writeback.metadata["audit_required"] is True
    assert ehr_writeback.metadata["idempotency_required"] is True
    assert ehr_writeback.metadata["rollback_or_compensation_required"] is True
    assert ehr_writeback.metadata["policy_control_id"]
    assert "network_private_connectivity" in expected_views(profile, production=True)
    assert "OR schedule-event ingestion" in poc_scope(profile)
    assert "approval-gated schedule changes" in production_scope(profile)

    spec = ArchitectureSpec(
        session_id="sess_healthcare_or_test",
        mode="production",
        title="PRODUCTION Healthcare Operations Scheduling Architecture",
        summary="Healthcare OR scheduling architecture validation test.",
        selected_services=service_recommendations(profile, evidence_ids=["ev_test"]),
        components=components,
        flows=flows,
        security_controls=security_controls(profile, production=True),
        observability_controls=observability_controls(profile, production=True),
        scaling_strategy="Scale by hospitals, ORs, schedule events, prediction refresh, and approval tasks.",
        resilience_strategy="Use private integrations, durable event queues, idempotent adapters, and supervised failover.",
        cost_optimization_strategy="Validate schedule event volume, metadata event volume, inference cadence, and audit retention.",
        assumptions=[],
        risks=[],
    )

    revision = ArchitectureRevisionService().initialize("sess_healthcare_or_test", [spec])
    critical = [issue for issue in revision.validation_issues if issue.severity == "critical"]

    assert not critical
    assert any(control.control_type == "human_approval" for control in revision.specs[0].governance_controls)
    assert any(control.control_type == "audit_trail" for control in revision.specs[0].governance_controls)
    governed_ids = {flow_id for control in revision.specs[0].governance_controls for flow_id in control.governed_flow_ids}
    assert ehr_writeback.id in governed_ids


@pytest.mark.asyncio
async def test_healthcare_pricing_uses_or_drivers_not_iot_or_incident_fallback():
    engine = SynthesisEngine()
    brief = engine.create_initial_brief(HOSPITAL_OR_USE_CASE)
    profile = profile_from_metadata(brief.use_case_profile, brief.raw_use_case)
    services = service_recommendations(profile, evidence_ids=["ev_test"])

    estimate = await PricingEngine().estimate(brief, services)

    metadata = estimate.metadata
    assert metadata["pricing_driver_family"] == "healthcare_operations_scheduling"
    assert metadata["driver_source"] == "healthcare_or_extracted_operating_room_metrics"
    assert metadata["pricing_can_be_displayed_as_headline"] is False
    assert not metadata["reserved_vocabulary_findings"]
    assert metadata["pricing_ledger"]["line_items"]
    assert metadata["pricing_ledger"]["summary"]["headline_safe"] is False

    drivers_text = "\n".join(estimate.main_cost_drivers)
    assert "hospital_count=18" in drivers_text
    assert "operating_room_count=240" in drivers_text
    assert "active_or_count_poc=8" in drivers_text
    assert "refresh_cadence_minutes=2" in drivers_text
    assert "recommendation_runs_per_day=2880" in drivers_text
    assert "asset_count=" not in drivers_text
    forbidden = [
        "depot",
        "dispatch",
        "confirmed incident",
        "confirmed_incident",
        "candidate anomaly",
        "candidate_anomaly",
        "asset telemetry",
        "inventory_or_depot",
        "predictive failure",
        "outage",
        "restoration",
    ]
    output = "\n".join([
        drivers_text,
        *[item.unit_basis for item in estimate.line_items],
        *[str(item.pricing_trace) for item in estimate.line_items],
    ]).lower()
    assert not any(term in output for term in forbidden)
    prediction_lines = [item for item in estimate.line_items if item.service in {"Amazon SageMaker", "Amazon Bedrock"}]
    assert prediction_lines
    assert any("active ORs" in item.pricing_trace.get("driver_formula", "") or "active ORs" in str(item.pricing_trace) for item in prediction_lines)


def test_healthcare_semantic_prediction_governance_view_is_requested_and_missing_is_semantic():
    profile = profile_use_case(HOSPITAL_OR_USE_CASE)
    semantic = expected_views(profile, production=True)
    assert "ai_security_governance_view" in semantic

    spec = ArchitectureSpec(
        session_id="sess_semantic_healthcare",
        mode="production",
        title="PRODUCTION Healthcare OR",
        summary="test",
        selected_services=service_recommendations(profile, evidence_ids=["ev_test"]),
        components=pattern_components(profile, production=True),
        flows=pattern_flows(profile, production=True, components=pattern_components(profile, production=True)),
        security_controls=security_controls(profile, production=True),
        observability_controls=observability_controls(profile, production=True),
        scaling_strategy="test",
        resilience_strategy="test",
        cost_optimization_strategy="test",
        assumptions=[],
        risks=[],
        metadata={
            "expected_views": ["production_logical_service_flow", "ai_security_governance_view"],
            "diagram_view_mappings": [
                {
                    "semantic_view_id": "predictive_failure_detection_view",
                    "compiler_view_id": "ai_security_governance_view",
                    "user_title": "AI Detection And Governance",
                    "user_description": "Model prediction and governance controls.",
                    "rendered_as_native_view": True,
                    "fallback_reason": None,
                }
            ],
        },
    )

    class Bundle:
        artifact_paths = {}

    missing = _missing_requested_views(spec, ["production_logical_service_flow"], Bundle())
    assert any(item["missing_level"] == "semantic" and item["semantic_view_id"] == "predictive_failure_detection_view" for item in missing)
    assert any(item["compiler_view_id"] == "ai_security_governance_view" for item in missing)
