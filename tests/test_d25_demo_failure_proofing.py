from __future__ import annotations

import json
from pathlib import Path

from app.core.config import get_settings
from app.services.convergence.golden_convergence_orchestrator import _diagram_findings
from app.services.open_world_understanding import CanonicalWorkloadUnderstanding, build_result_from_understanding
from app.services.pricing import derive_pricing_drivers
from app.services.pricing_driver_selector import PricingDriverFamily, select_pricing_driver_family
from app.services.use_case_profile import ExtractedMetric, UseCaseProfile, profile_use_case


def _profile(**overrides) -> UseCaseProfile:
    base = {
        "domain": "open_world_operations",
        "workload_families": ["operational_event_prediction_workflow"],
        "excluded_families": [],
        "capabilities": ["real_time_ingestion"],
        "entities": [],
        "signals": [],
        "actions": ["notify_operator"],
        "metrics": [],
        "business_targets": [],
    }
    base.update(overrides)
    return UseCaseProfile(**base)


def test_video_payload_without_audience_intent_does_not_select_live_media_pricing():
    profile = _profile(
        capabilities=["video_streaming", "computer_vision", "real_time_ingestion"],
        signals=["inspection_video", "thermal_images", "defect_evidence"],
        business_targets=["Analyze uploaded inspection footage and retain warranty evidence."],
    )

    assert select_pricing_driver_family(profile) is PricingDriverFamily.GENERIC_DIRECTIONAL


def test_public_analytics_with_ingested_video_is_not_live_media_streaming():
    profile = profile_use_case(
        "A coastal habitat restoration program ingests drone imagery, underwater robot video, "
        "water sensors, field notes, and permit PDFs. It predicts restoration risk every "
        "15 minutes, schedules crews for approval, keeps evidence for 25 years, and publishes "
        "a public progress dashboard for 50,000 monthly visitors and 5,000 concurrent viewers."
    )

    assert "live_streaming" not in profile.workload_families
    assert "video_streaming" not in profile.capability_model
    assert select_pricing_driver_family(profile) is PricingDriverFamily.GENERIC_DIRECTIONAL


def test_source_documents_do_not_select_document_rag_without_retrieval_intent():
    profile = profile_use_case(
        "A regulator ingests permit PDFs, inspection photos, and field notes as evidence "
        "for risk scoring, audit retention, and operational approvals."
    )

    assert "document_intelligence" not in profile.workload_families
    assert "rag_assistant" not in profile.workload_families
    assert "document_retrieval" not in profile.capability_model
    assert select_pricing_driver_family(profile) is PricingDriverFamily.GENERIC_DIRECTIONAL


def test_explicit_document_retrieval_intent_still_selects_document_rag():
    profile = profile_use_case(
        "A legal team needs RAG question answering with citations over 5,000 contracts, "
        "clause obligations, semantic document search, and reviewer approval workflows."
    )

    assert {"document_intelligence", "rag_assistant"} & set(profile.workload_families)
    assert select_pricing_driver_family(profile) is PricingDriverFamily.DOCUMENT_RAG_WORKFLOW


def test_video_distribution_with_viewer_intent_still_selects_live_media_pricing():
    profile = _profile(
        workload_families=["live_streaming"],
        capabilities=["video_streaming", "content_delivery"],
        signals=["playback_events", "cdn_logs"],
        business_targets=["Serve live channels to 80,000 concurrent viewers with CDN and DRM."],
    )

    assert select_pricing_driver_family(profile) is PricingDriverFamily.LIVE_MEDIA_STREAMING


def test_explicit_active_asset_quantity_beats_location_count_without_domain_terms():
    profile = _profile(
        metrics=[
            ExtractedMetric(label="site_count", value=11, unit="count", raw="11 locations", kind="asset_count"),
            ExtractedMetric(label="total_monitored_assets", value=11, unit="count", raw="sum of monitored asset counts", kind="asset_count"),
            ExtractedMetric(label="explicit_quantity_active_units_1", value=42_000, unit="active_units", raw="42,000 active units", kind="business_target"),
            ExtractedMetric(label="explicit_quantity_signal_reads_per_2", value=95_000, unit="signal_reads_per", raw="95,000 signal reads per month", kind="business_target"),
        ],
        business_targets=["Track 42,000 active units across 11 locations."],
    )

    drivers = derive_pricing_drivers(profile)

    assert drivers.asset_count == 42_000


def test_network_outage_wording_does_not_hijack_process_manufacturing_to_telecom():
    profile = profile_use_case(
        "A specialty manufacturer monitors batch reactors, solvent recovery skids, historian tags, "
        "MES batch records, LIMS quality results, spectroscopy files, off-spec release risk, and plant "
        "network outages that can last four hours."
    )

    assert profile.domain == "manufacturing"
    assert "telecom_network_analytics" not in profile.workload_families
    assert "cdr_congestion_prediction" not in profile.workload_families
    assert "industrial_iot_streaming_ml" in profile.workload_families


def test_open_world_missing_domain_is_repaired_from_source_without_telecom_drift():
    raw = (
        "A specialty chemical manufacturer monitors batch reactors, solvent recovery skids, "
        "historian tags, MES batch records, LIMS quality results, spectroscopy files, off-spec "
        "release risk, and plant network outages."
    )
    understanding = CanonicalWorkloadUnderstanding(
        domain_candidates=[],
        workload_intent="Monitor and optimize specialty chemical manufacturing processes.",
        events_signals=[],
        missing_questions=[],
    )

    result = build_result_from_understanding(raw, understanding, provider="fixture")

    assert result.profile is not None
    assert result.profile.domain == "manufacturing"
    assert "telecom_network_analytics" not in result.profile.workload_families
    assert any(issue.code == "open_world_understanding.domain_repaired" for issue in result.trace.validation_issues)


def test_latest_export_bundle_self_heals_missing_zip(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHWAY_DATA_DIR", str(tmp_path / ".archway"))
    get_settings.cache_clear()

    import app.api.routes as routes
    from app.services.artifacts import ArtifactStore

    routes.artifacts = ArtifactStore()
    session_id = "sess_missing_zip"
    export_name = "archway-solution-package-sess_missing_zip-20260618T000000Z"
    package_dir = routes.artifacts.session_root(session_id) / "exports" / export_name
    raw_dir = package_dir / "raw"
    raw_dir.mkdir(parents=True)
    (package_dir / "README.md").write_text("Package ready", encoding="utf-8")
    (raw_dir / "live_agent_calls.json").write_text("[]", encoding="utf-8")
    (package_dir / "manifest.json").write_text(
        json.dumps({
            "name": export_name,
            "session_id": session_id,
            "included_artifacts": ["README.md", "raw/live_agent_calls.json", "manifest.json"],
            "warnings": [],
        }),
        encoding="utf-8",
    )

    latest = routes._latest_export_bundle(session_id)

    assert latest is not None
    assert Path(latest["zip_path"]).is_file()
    assert Path(latest["zip_path"]).stat().st_size > 0
    assert latest["download_url"].endswith(f"/exports/{export_name}.zip")


def test_warning_only_diagram_qa_does_not_fail_customer_readiness():
    findings = _diagram_findings([{
        "mode": "production",
        "qa_reports": [{
            "view_id": "bundle",
            "passed": False,
            "diagnostics": [
                {"severity": "warning", "code": "aws_service_catalog_fallback", "message": "Service placement inferred from catalog fallback."},
                {"severity": "info", "code": "observability_coverage_added", "message": "Added observability coverage."},
            ],
        }],
    }])

    assert [item.code for item in findings] == ["diagram.qa_warning_only"]
    assert findings[0].severity == "warning"
    assert findings[0].customer_readiness_impact == "cap_to_workshop"
