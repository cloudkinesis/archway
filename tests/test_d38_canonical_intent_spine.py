from app.models.domain import AWSServiceRecommendation, ResearchReport
from app.services.architecture import ArchitecturePlanner
from app.services.canonical_intent import canonical_intent_for_profile
from app.services.pricing import derive_pricing_drivers
from app.services.source_truth_pricing_compiler import _generic_quantity_context
from app.services.synthesis import SynthesisEngine
from app.services.use_case_profile import profile_from_metadata, profile_to_metadata
from app.domain.source_of_truth import CanonicalFact, CanonicalFactsLedger


PARATRANSIT_DOCUMENT_WORKFLOW = (
    "A regional public transit agency wants an AWS platform that uses AI to review "
    "paratransit eligibility applications, extract mobility limitations from uploaded "
    "medical forms and PDFs, check policy rules for service eligibility, recommend "
    "interview follow-ups, schedule in-person assessments, notify riders and caregivers "
    "by SMS/email, and maintain a complete appeal-ready audit trail. The system must "
    "process 2,800 applications per month, support 85 case reviewers, handle document "
    "packets up to 180 pages, integrate with an existing scheduling system and rider CRM, "
    "keep medical details separated from operational dispatch notes, provide applicant "
    "status responses under 3 seconds, and generate AI-assisted eligibility summaries "
    "within 90 seconds while requiring human approval before any denial decision."
)


def _profile():
    brief = SynthesisEngine().create_initial_brief(PARATRANSIT_DOCUMENT_WORKFLOW)
    return profile_from_metadata(brief.use_case_profile, PARATRANSIT_DOCUMENT_WORKFLOW)


def test_canonical_intent_blocks_telemetry_for_document_approval_workflow():
    profile = _profile()

    intent = canonical_intent_for_profile(profile, PARATRANSIT_DOCUMENT_WORKFLOW)

    assert intent.streaming_evidence is False
    assert intent.document_evidence is True
    assert intent.notification_evidence is True
    assert intent.external_integration_evidence is True
    assert intent.audit_evidence is True
    assert intent.geospatial_evidence is False


def test_architecture_uses_document_workflow_services_without_streaming_topology():
    profile = _profile()
    report = ResearchReport.model_construct(
        session_id="test",
        use_case_interpretation=PARATRANSIT_DOCUMENT_WORKFLOW,
        executive_verdict="ok",
        recommended_poc="Validate workflow.",
        recommended_production_direction="Operate workflow.",
        aws_service_recommendations=[
            AWSServiceRecommendation(service="AWS Step Functions", purpose="Workflow", rationale="Governed workflow"),
            AWSServiceRecommendation(service="Amazon Location Service", purpose="Maps", rationale="Borrowed geospatial recommendation"),
        ],
        assumptions=[],
        risks=[],
        evidence_items=[],
        metadata={
            "use_case_profile": profile_to_metadata(profile),
            "canonical_fact_snapshot": {
                "quantities": [
                    {"source_text": "2,800 applications per month"},
                    {"source_text": "180 pages"},
                ],
                "latency_slos": ["under 3 seconds"],
            },
        },
    )

    spec = ArchitecturePlanner().generate(report)[0]
    component_text = " ".join([component.service for component in spec.components] + [str((component.metadata or {}).get("role", "")) for component in spec.components]).lower()
    flow_pairs = {(flow.source, flow.target) for flow in spec.flows}
    selected = {item.service for item in spec.selected_services}
    coverage = {item["id"]: item for item in spec.metadata["requirement_coverage"]["requirements"]}

    assert "kinesis" not in component_text
    assert "flink" not in component_text
    assert "stream_ingest" not in component_text
    assert "amazon_textract_bedrock" in component_text
    assert "telemetry_ingestion_view" not in spec.metadata["semantic_views"]
    assert "Amazon Location Service" not in selected
    assert "computer_vision_hot_path" not in coverage
    assert ("enterprise_integration_adapter", "workflow") in flow_pairs or ("enterprise_integration_adapter", "human_review_workflow") in flow_pairs
    assert ("integration_authorizer", "enterprise_integration_adapter") in flow_pairs
    assert ("workflow", "notification_service") in flow_pairs or ("human_review_workflow", "notification_service") in flow_pairs
    assert ("workflow", "operational_dashboard") in flow_pairs or ("human_review_workflow", "operational_dashboard") in flow_pairs
    assert ("workflow", "low_latency_read_model") in flow_pairs or ("human_review_workflow", "low_latency_read_model") in flow_pairs
    assert ("low_latency_read_model", "operational_dashboard") in flow_pairs
    assert {"Amazon Textract", "Amazon S3", "Amazon SNS / Amazon SES", "Amazon API Gateway", "Amazon Cognito", "Amazon S3 Object Lock", "Amazon ElastiCache"} <= selected


def test_pricing_uses_advisory_workflow_not_telemetry_defaults():
    drivers = derive_pricing_drivers(_profile())

    assert drivers.source == "advisory_discovery_directional_model"
    assert drivers.telemetry_frequency_seconds == 0
    assert drivers.flink_kpu_hours == 0
    assert drivers.asset_count != 180


def test_generic_quantity_graph_treats_pages_and_response_seconds_as_document_facts():
    facts = CanonicalFactsLedger(
        facts=[
            CanonicalFact(name="applications_per_month", value=2800, unit="applications_per_month", source="user_input", source_text="2,800 applications per month", confidence="high", validation_status="confirmed"),
            CanonicalFact(name="document_pages", value=180, unit="pages", source="user_input", source_text="document packets up to 180 pages", confidence="high", validation_status="confirmed"),
            CanonicalFact(name="status_latency", value=3, unit="seconds", source="user_input", source_text="applicant status responses under 3 seconds", confidence="high", validation_status="confirmed"),
        ]
    )

    context = _generic_quantity_context(facts)

    assert context["asset_count"] == 0
    assert context["cadence_seconds"] == 0
    assert context["monthly_events"] == 2800
    assert context["monthly_document_pages"] == 504000
    assert context["storage_gb_month_by_class"]["evidence"] > 0
