from zipfile import ZipFile

import pytest

from app.core.config import get_settings
from app.db.session_store import SessionStore
from app.models.domain import AWSServiceSelection
from app.services.customer_readiness import CustomerReadinessStatus, assess_customer_readiness
from app.services.export_package import ExportPackageService
from app.services.pricing import PricingEngine
from app.services.pricing_driver_closure import build_pricing_checkpoint
from app.services.synthesis import SynthesisEngine
from tests.golden_scenarios.scenarios import GOLDEN_SCENARIOS


@pytest.mark.asyncio
async def test_pass3a_live_media_missing_bitrate_triggers_checkpoint_without_relisting_known_viewers():
    brief = SynthesisEngine().create_initial_brief(GOLDEN_SCENARIOS["live_sports"])
    estimate = await PricingEngine().estimate(
        brief,
        [
            AWSServiceSelection(service="Amazon CloudFront", purpose="cdn", rationale="managed"),
            AWSServiceSelection(service="AWS Elemental MediaLive", purpose="encoding", rationale="managed"),
        ],
    )

    checkpoint = build_pricing_checkpoint(estimate, session_id="sess_test")
    missing = {item.driver_name for item in checkpoint.closure_report.missing_drivers}

    assert "average_bitrate_mbps" in missing
    assert "concurrent_viewers" not in missing
    assert checkpoint.closure_report.pricing_maturity == "pricing_directional_with_assumptions"
    assert checkpoint.questions


@pytest.mark.asyncio
async def test_pass3a_global_major_event_profile_populates_assumption_ledger_and_line_items():
    brief = SynthesisEngine().create_initial_brief(GOLDEN_SCENARIOS["live_sports"])
    estimate = await PricingEngine().estimate(
        brief,
        [
            AWSServiceSelection(service="Amazon CloudFront", purpose="cdn", rationale="managed"),
            AWSServiceSelection(service="AWS Elemental MediaLive", purpose="encoding", rationale="managed"),
            AWSServiceSelection(service="AWS Elemental MediaTailor", purpose="ads", rationale="managed"),
        ],
        pricing_driver_overrides={
            "scenario_profile_id": "live_media_global_major_event",
            "average_viewer_hours_per_month": 20,
            "average_bitrate_mbps": 15,
            "region_traffic_mix": "global balanced across 40 countries",
            "cdn_cache_hit_ratio": 0.85,
            "live_channel_count": 4,
            "event_hours_per_month": 240,
            "ad_decision_requests_per_month": 150000000,
            "drm_license_requests_per_month": 25000000,
            "edge_function_invocations_per_month": 300000000,
            "origin_request_count_per_month": 75000000,
            "archive_storage_gb_month": 10000,
        },
    )

    closure = estimate.metadata["pricing_driver_closure"]
    assumptions = estimate.metadata["assumption_ledger"]["assumptions"]
    ledger = estimate.metadata["pricing_ledger"]["line_items"]

    assert closure["pricing_maturity"] == "pricing_customer_demo_ready"
    assert closure["scenario_profile_used"] == "live_media_global_major_event"
    assert any(item["source"] == "scenario_profile" and item["used_by_driver_ids"] for item in assumptions)
    assert any(item["assumptions"] for item in ledger)


def test_pass3a_readiness_ladder_allows_honest_scenario_pricing_demo_ready():
    readiness = assess_customer_readiness(
        evidence_quality={"evidence_authority": "strong", "customer_ready": True, "aws_docs_available": True, "aws_pricing_available": True},
        citation_passed=True,
        service_decisions=[],
        pricing_unknowns=[],
        pricing_status="directional",
        pricing_metadata={
            "pricing_maturity": "pricing_customer_demo_ready",
            "pricing_ledger": {"summary": {"procurement_ready": False, "headline_safe": False}},
        },
    )

    assert readiness.status == CustomerReadinessStatus.CUSTOMER_DEMO_READY_WITH_CAVEATS


@pytest.mark.asyncio
async def test_pass3a_export_contains_pricing_driver_closure_section(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()
    store = SessionStore()
    brief = SynthesisEngine().create_initial_brief(GOLDEN_SCENARIOS["live_sports"])
    session = store.create(GOLDEN_SCENARIOS["live_sports"], brief)
    estimate = await PricingEngine().estimate(
        brief,
        [AWSServiceSelection(service="Amazon CloudFront", purpose="cdn", rationale="managed")],
        pricing_driver_overrides={
            "scenario_profile_id": "live_media_global_major_event",
            "average_viewer_hours_per_month": 20,
            "average_bitrate_mbps": 15,
            "region_traffic_mix": "global balanced across 40 countries",
            "cdn_cache_hit_ratio": 0.85,
            "live_channel_count": 4,
            "event_hours_per_month": 240,
        },
    )
    service = ExportPackageService()
    service.artifacts.write_json(session.id, "brief", "current", brief.model_dump(mode="json"))
    service.artifacts.write_json(session.id, "pricing", "estimate", estimate.model_dump(mode="json"))

    bundle = service.generate(session.id)
    zip_path = service.artifacts.resolve(session.id, bundle.artifact_id)

    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        pricing_markdown = archive.read("03-pricing.md").decode("utf-8")
        trace_markdown = archive.read("11-pricing-trace.md").decode("utf-8")

    assert "raw/pricing_driver_closure.json" in names
    assert "Pricing Driver Closure" in pricing_markdown
    assert "Directional scenario estimate, not procurement-ready" in pricing_markdown
    assert "Confirmed vs Assumed vs Missing Drivers" in trace_markdown
