import pytest

from app.models.domain import AWSServiceSelection
from app.models.domain import ArchitectureSpec
from app.services.diagram_compiler_adapter import DiagramCompilerAdapter
from app.services.pattern_catalog import pattern_components, service_recommendations
from app.services.pattern_catalog import expected_views, observability_controls, pattern_flows, security_controls, semantic_views
from app.services.pricing import PricingEngine
from app.services.pricing_driver_selector import PricingDriverFamily, select_pricing_driver_family
from app.services.synthesis import SynthesisEngine
from app.services.use_case_profile import profile_use_case
from app.services.view_planner import diagram_view_mappings, semantic_to_compiler_mapping
from tests.golden_scenarios.scenarios import GOLDEN_SCENARIOS


@pytest.mark.asyncio
async def test_live_media_streaming_uses_media_family_services_and_pricing():
    brief = SynthesisEngine().create_initial_brief(GOLDEN_SCENARIOS["live_sports"])
    profile = profile_use_case(GOLDEN_SCENARIOS["live_sports"])

    assert profile.domain == "media"
    assert "live_streaming" in profile.workload_families
    assert select_pricing_driver_family(profile) == PricingDriverFamily.LIVE_MEDIA_STREAMING

    component_services = {component.service for component in pattern_components(profile, production=True)}
    assert {"medialive", "mediapackage", "cloudfront"} <= component_services

    services = service_recommendations(profile, evidence_ids=["ev_test"])
    service_names = {item.service for item in services}
    assert "AWS IoT Core" not in service_names
    assert "AWS IoT SiteWise / time-series storage decision" not in service_names
    estimate = await PricingEngine().estimate(brief, [AWSServiceSelection(service=item.service, purpose=item.purpose, rationale=item.rationale) for item in services])

    assert estimate.metadata["pricing_driver_family"] == "live_media_streaming"
    assert estimate.metadata["pricing_can_be_displayed_as_headline"] is False
    assert any("concurrent_viewers=25000000" in item for item in estimate.main_cost_drivers)
    assert any(line.service == "Amazon CloudFront" and line.expected_monthly_usd > 100000 for line in estimate.line_items)


def test_pass1c_live_media_brief_uses_media_words_not_generic_telemetry():
    brief = SynthesisEngine().create_initial_brief(GOLDEN_SCENARIOS["live_sports"])
    readiness = SynthesisEngine().readiness(brief)
    text = " ".join(
        [
            *(item.text for item in brief.assumptions),
            *(item.text for item in brief.open_questions),
            *(item.prompt for item in readiness.recommended_minimum_questions),
            *(item.text for item in readiness.assumptions_if_skipped),
            *(item.name for item in brief.data_sources),
        ]
    ).lower()

    assert "viewer-hours" in text
    assert "drm" in text
    assert "qoe" in text
    assert "reporting frequency" not in text
    assert "payload size" not in text
    assert "telemetry streams" not in text


def test_pass1c_live_media_pattern_has_rights_consent_geo_and_qoe_components():
    profile = profile_use_case(GOLDEN_SCENARIOS["live_sports"])
    components = pattern_components(profile, production=True)
    component_text = " ".join([component.name + " " + component.service + " " + str(component.metadata) for component in components]).lower()

    assert "drm" in component_text
    assert "consent" in component_text
    assert "geo_rights_policy_store" in component_text
    assert "qoe_latency_monitoring" in component_text


def test_pass2a_live_media_requests_native_media_views_without_empty_data_view():
    profile = profile_use_case(GOLDEN_SCENARIOS["live_sports"])

    assert semantic_views(profile, production=True) == [
        "logical_service_flow",
        "live_media_delivery_view",
        "media_rights_ad_decisioning_view",
        "media_qoe_analytics_view",
        "security_observability_view",
    ]
    assert expected_views(profile, production=True) == [
        "production_logical_service_flow",
        "live_media_delivery_view",
        "media_rights_ad_decisioning_view",
        "media_qoe_analytics_view",
        "security_observability_controls",
    ]


def test_pass2a_compiler_catalog_has_first_class_media_placement():
    adapter = DiagramCompilerAdapter()
    adapter._ensure_import_path()
    from archway_diagram_compiler.providers import get_provider_catalog

    catalog = get_provider_catalog("aws")

    assert catalog.get_service_info("AWS Elemental MediaLive").placement_scope == "regional_managed_data"
    assert catalog.get_service_info("AWS Elemental MediaPackage").placement_scope == "regional_managed_data"
    assert catalog.get_service_info("AWS Elemental MediaTailor").placement_scope == "regional_integration"
    assert catalog.get_service_info("AWS Lambda@Edge").placement_scope == "global_edge"
    assert catalog.get_service_info("CloudFront Functions").placement_scope == "global_edge"


def test_pass2a_live_media_compiler_views_pass_without_scope_or_crossing_errors():
    profile = profile_use_case(GOLDEN_SCENARIOS["live_sports"])
    components = pattern_components(profile, production=True)
    flows = pattern_flows(profile, production=True, components=components)
    view_ids = semantic_views(profile, production=True)
    compiler_views = expected_views(profile, production=True)
    mappings = diagram_view_mappings(view_ids, "Live Streaming")
    spec = ArchitectureSpec(
        session_id="sess_pass2a_test",
        mode="production",
        title="PRODUCTION Live Streaming Architecture",
        summary="Live media architecture compile test.",
        selected_services=service_recommendations(profile, evidence_ids=["ev_test"]),
        components=components,
        flows=flows,
        security_controls=security_controls(profile, production=True),
        observability_controls=observability_controls(profile, production=True),
        scaling_strategy="Scale live media delivery from measured viewer load.",
        resilience_strategy="Use managed resilient media services.",
        cost_optimization_strategy="Validate viewer-hours, bitrate, and CDN egress.",
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

    result = DiagramCompilerAdapter().compile_production_diagrams(spec, "sess_pass2a_test")

    diagnostics = [diagnostic for qa in result.qa_reports for diagnostic in qa.diagnostics]
    assert all(qa.passed for qa in result.qa_reports)
    assert {"live_media_delivery_view", "media_rights_ad_decisioning_view", "media_qoe_analytics_view"} <= set(result.rendered_view_ids)
    assert not any(item.get("code") in {"invalid_scope", "too_many_edge_crossings"} for item in diagnostics)
    assert not result.missing_requested_views
