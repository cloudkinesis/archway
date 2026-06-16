import pytest

from app.models.domain import AWSServiceSelection
from app.services.pattern_catalog import expected_views, pricing_dimensions, service_recommendations
from app.services.pricing import PricingEngine, derive_pricing_drivers
from app.services.pricing_driver_selector import PricingDriverFamily, select_pricing_driver_family
from app.services.synthesis import SynthesisEngine
from app.services.use_case_profile import profile_use_case


HEALTHCARE_TERMS = (
    "operating room",
    "or schedule",
    "or utilization",
    "or command center",
    "ehr",
    "phi",
    "patient",
    "clinical",
    "charge nurse",
    "epic",
    "sterile processing",
)

HEALTHCARE_DRIVER_NAMES = (
    "hospital_count",
    "operating_room_count",
    "active_or_count_poc",
    "scheduled_surgeries_per_day",
    "refresh_cadence_minutes",
    "recommendation_runs_per_day",
    "approval_workflow_executions_per_day",
    "ehr_writeback_attempts_per_day",
    "occupancy_readiness_events_per_day",
    "active_coordinator_users",
)


def _combined_profile_output(text: str) -> str:
    profile = profile_use_case(text)
    brief = SynthesisEngine().create_initial_brief(text)
    services = service_recommendations(profile, evidence_ids=["ev_test"])
    return "\n".join(
        [
            str(profile.domain),
            " ".join(profile.workload_families),
            " ".join(profile.capabilities),
            " ".join(expected_views(profile, production=True)),
            " ".join(pricing_dimensions(profile)),
            " ".join(item.service for item in services),
            " ".join(item.purpose for item in services),
            " ".join(item.rationale for item in services),
            " ".join(question.text for question in brief.open_questions),
            " ".join(assumption.text for assumption in brief.assumptions),
            " ".join(source.name for source in brief.data_sources),
        ]
    ).lower()


def _assert_no_healthcare_terms(output: str) -> None:
    assert not any(term in output for term in HEALTHCARE_TERMS)
    assert not any(driver in output for driver in HEALTHCARE_DRIVER_NAMES)


def test_generic_web_app_does_not_become_healthcare_shaped():
    use_case = "We need a public web application with API, database, async jobs, observability, and CI/CD."
    profile = profile_use_case(use_case)
    output = _combined_profile_output(use_case)

    assert profile.workload_families == ["web_api_application"]
    assert profile.domain is None
    assert select_pricing_driver_family(profile) == PricingDriverFamily.GENERIC_DIRECTIONAL
    assert "healthcare_operations_scheduling" not in profile.workload_families
    assert "ai_security_governance_view" not in expected_views(profile, production=True)
    _assert_no_healthcare_terms(output)


def test_telecom_hbase_migration_stays_telecom_and_asks_access_pattern_first():
    use_case = "We need to migrate a telecom HBase/HDFS real-time analytics platform to AWS."
    profile = profile_use_case(use_case)
    brief = SynthesisEngine().create_initial_brief(use_case)
    output = _combined_profile_output(use_case)

    assert profile.domain == "telecommunications"
    assert "telecom_network_analytics" in profile.workload_families or "data_platform_analytics" in profile.workload_families
    assert select_pricing_driver_family(profile) == PricingDriverFamily.TELECOM_CDR_ANALYTICS
    assert derive_pricing_drivers(profile).pricing_driver_family == PricingDriverFamily.TELECOM_CDR_ANALYTICS.value
    assert "healthcare_operations_scheduling" not in profile.workload_families
    assert "healthcare_operations_scheduling" not in expected_views(profile, production=True)
    assert "ai_security_governance_view" not in expected_views(profile, production=True)
    assert brief.open_questions
    assert "hbase access patterns" in brief.open_questions[0].text.lower()
    assert "target store" in brief.open_questions[0].text.lower()
    _assert_no_healthcare_terms(output)


@pytest.mark.asyncio
async def test_legal_contract_rag_workflow_asks_document_pricing_questions_not_telemetry():
    use_case = (
        "AI-assisted legal contract review and obligation-tracking platform with 5,000 historical contracts, "
        "RAG Q&A, clause extraction, obligation tracking, approval workflow, and audit trail."
    )
    profile = profile_use_case(use_case)
    brief = SynthesisEngine().create_initial_brief(use_case)
    next_question = SynthesisEngine().next_question(brief)
    text = " ".join(
        [
            str(profile.domain),
            " ".join(profile.workload_families),
            " ".join(pricing_dimensions(profile)),
            " ".join(question.text for question in brief.open_questions),
            " ".join(assumption.text for assumption in brief.assumptions),
            " ".join(source.name for source in brief.data_sources),
            next_question.prompt if next_question else "",
        ]
    ).lower()

    assert profile.domain == "legal"
    assert "document_intelligence" in profile.workload_families
    assert "rag_assistant" in profile.workload_families
    assert "field_service_automation" not in profile.workload_families
    assert select_pricing_driver_family(profile) == PricingDriverFamily.DOCUMENT_RAG_WORKFLOW
    assert "telecom_network_analytics" not in profile.workload_families
    assert "telemetry pricing" not in text
    assert "reporting frequency" not in text
    assert "payload size" not in text
    assert "telemetry streams" not in text
    assert "historical contracts" in text or "historical contracts/documents" in text
    assert "average pages or mb per document" in text
    assert "new or updated documents per month" in text
    assert "rag queries" in text
    assert "embedding/indexing frequency" in text
    assert "obligation approval volume" in text
    assert "audit retention" in text

    estimate = await PricingEngine().estimate(
        brief,
        [
            AWSServiceSelection(service="Amazon S3", purpose="contract source storage", rationale="durable"),
            AWSServiceSelection(service="Amazon Bedrock", purpose="RAG Q&A and clause extraction", rationale="managed foundation model"),
            AWSServiceSelection(service="AWS Step Functions", purpose="obligation approval workflow", rationale="auditable workflow"),
        ],
    )
    pricing_text = " ".join(
        [
            " ".join(estimate.main_cost_drivers),
            " ".join(estimate.cost_optimization_recommendations),
            str(estimate.metadata),
        ]
    ).lower()

    assert estimate.metadata["pricing_driver_family"] == "document_rag_workflow"
    assert "historical_contract_or_document_count=5000" in pricing_text
    assert "rag_queries_per_day" in pricing_text
    assert "average pages or mb" in pricing_text
    assert "telemetry frequency" not in pricing_text
    assert "payload size" not in pricing_text


@pytest.mark.asyncio
async def test_media_qoe_platform_uses_media_pricing_without_healthcare_drivers():
    use_case = "We need a video streaming analytics platform for viewer QoE and CDN logs."
    profile = profile_use_case(use_case)
    brief = SynthesisEngine().create_initial_brief(use_case)
    services = service_recommendations(profile, evidence_ids=["ev_test"])

    estimate = await PricingEngine().estimate(
        brief,
        [AWSServiceSelection(service=item.service, purpose=item.purpose, rationale=item.rationale) for item in services],
    )
    output = "\n".join(
        [
            _combined_profile_output(use_case),
            " ".join(estimate.main_cost_drivers),
            " ".join(line.unit_basis for line in estimate.line_items),
            str(estimate.metadata),
        ]
    ).lower()

    assert "live_streaming" in profile.workload_families
    assert select_pricing_driver_family(profile) == PricingDriverFamily.LIVE_MEDIA_STREAMING
    assert estimate.metadata["pricing_driver_family"] == "live_media_streaming"
    assert "media" in output or "streaming" in output
    assert "ai_security_governance_view" not in expected_views(profile, production=True)
    _assert_no_healthcare_terms(output)


@pytest.mark.asyncio
async def test_healthcare_pricing_family_and_reserved_lint_are_not_global():
    non_healthcare = "A utility platform dispatches field crews and checks depot inventory for transformer outages."
    profile = profile_use_case(non_healthcare)
    brief = SynthesisEngine().create_initial_brief(non_healthcare)
    estimate = await PricingEngine().estimate(
        brief,
        [AWSServiceSelection(service="Amazon EventBridge", purpose="event routing", rationale="managed")],
    )

    assert "healthcare_operations_scheduling" not in profile.workload_families
    assert select_pricing_driver_family(profile) != PricingDriverFamily.HEALTHCARE_OPERATIONS_SCHEDULING
    assert estimate.metadata["pricing_driver_family"] != "healthcare_operations_scheduling"
    assert estimate.metadata["reserved_vocabulary_findings"] == []


def test_healthcare_pricing_family_is_only_selected_for_healthcare_operations_profile():
    healthcare = profile_use_case(
        "A hospital needs operating room delay prediction with Epic schedule data, patient check-in, charge nurse approval, PHI controls, and sterile processing readiness."
    )
    generic = profile_use_case("We need a public web application with API, database, async jobs, observability, and CI/CD.")
    telecom = profile_use_case("We need to migrate a telecom HBase/HDFS real-time analytics platform to AWS.")
    media = profile_use_case("We need a video streaming analytics platform for viewer QoE and CDN logs.")

    assert select_pricing_driver_family(healthcare) == PricingDriverFamily.HEALTHCARE_OPERATIONS_SCHEDULING
    assert all(
        select_pricing_driver_family(profile) != PricingDriverFamily.HEALTHCARE_OPERATIONS_SCHEDULING
        for profile in (generic, telecom, media)
    )


def test_core_compiler_lane_categories_remain_domain_neutral():
    from app.services.diagram_compiler_adapter import DiagramCompilerAdapter

    adapter = DiagramCompilerAdapter()
    adapter._ensure_import_path()
    from archway_diagram_compiler.lane_templates import LANE_TEMPLATES

    lane_text = str(LANE_TEMPLATES).lower()
    forbidden = ("ehr", "phi", "patient", "clinical", "charge nurse", "epic", "sterile processing", "operating room")
    assert not any(term in lane_text for term in forbidden)
