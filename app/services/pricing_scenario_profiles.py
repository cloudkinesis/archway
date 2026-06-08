from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.pricing_driver_selector import PricingDriverFamily


ScenarioUse = Literal["poc", "pilot", "regional_production", "global_production", "peak_event"]
ScenarioReadinessImpact = Literal["directional_only", "customer_demo_ready_with_caveats", "internal_only"]


class ScenarioAssumption(BaseModel):
    driver_name: str
    value: Any
    unit: str | None = None
    statement: str
    confidence: Literal["low", "medium", "high"] = "medium"
    validation_method: str


class ScenarioProfile(BaseModel):
    id: str
    workload_family: str
    label: str
    description: str
    intended_use: ScenarioUse
    assumptions: list[ScenarioAssumption] = Field(default_factory=list)
    driver_values: dict[str, Any] = Field(default_factory=dict)
    readiness_impact: ScenarioReadinessImpact


def live_media_scenario_profiles() -> list[ScenarioProfile]:
    family = PricingDriverFamily.LIVE_MEDIA_STREAMING.value
    return [
        _profile(
            "live_media_conservative_poc",
            family,
            "Conservative POC",
            "Small controlled stream used to validate playback, rights, ad, and QoE flow before traffic forecasting.",
            "poc",
            "directional_only",
            {
                "average_viewer_hours_per_month": (5, "viewer-hours/month"),
                "average_bitrate_mbps": (8, "Mbps"),
                "region_traffic_mix": ("mostly single region", None),
                "cdn_cache_hit_ratio": (0.95, "ratio"),
                "live_channel_count": (1, "channels"),
                "event_hours_per_month": (40, "hours/month"),
                "ad_decision_requests_per_month": (0, "requests/month"),
                "drm_license_requests_per_month": (10000, "requests/month"),
                "edge_function_invocations_per_month": (1000000, "requests/month"),
                "origin_request_count_per_month": (500000, "requests/month"),
                "archive_storage_gb_month": (500, "GB-month"),
            },
        ),
        _profile(
            "live_media_regional_production_pilot",
            family,
            "Regional Production Pilot",
            "A regional production-like pilot with moderate viewer engagement, rights checks, DRM, and ad decisioning.",
            "regional_production",
            "customer_demo_ready_with_caveats",
            {
                "average_viewer_hours_per_month": (10, "viewer-hours/month"),
                "average_bitrate_mbps": (10, "Mbps"),
                "region_traffic_mix": ("mostly one geography", None),
                "cdn_cache_hit_ratio": (0.90, "ratio"),
                "live_channel_count": (2, "channels"),
                "event_hours_per_month": (120, "hours/month"),
                "ad_decision_requests_per_month": (3000000, "requests/month"),
                "drm_license_requests_per_month": (1000000, "requests/month"),
                "edge_function_invocations_per_month": (5000000, "requests/month"),
                "origin_request_count_per_month": (2000000, "requests/month"),
                "archive_storage_gb_month": (2000, "GB-month"),
            },
        ),
        _profile(
            "live_media_global_major_event",
            family,
            "Global Major-Event Baseline",
            "A major global live-event baseline with broad geography, 4K-capable delivery, ad decisions, DRM, and QoE analytics.",
            "global_production",
            "customer_demo_ready_with_caveats",
            {
                "average_viewer_hours_per_month": (20, "viewer-hours/month"),
                "average_bitrate_mbps": (15, "Mbps"),
                "region_traffic_mix": ("global balanced across 40 countries", None),
                "cdn_cache_hit_ratio": (0.85, "ratio"),
                "live_channel_count": (4, "channels"),
                "event_hours_per_month": (240, "hours/month"),
                "ad_decision_requests_per_month": (150000000, "requests/month"),
                "drm_license_requests_per_month": (25000000, "requests/month"),
                "edge_function_invocations_per_month": (300000000, "requests/month"),
                "origin_request_count_per_month": (75000000, "requests/month"),
                "archive_storage_gb_month": (10000, "GB-month"),
            },
        ),
        _profile(
            "live_media_peak_global_event",
            family,
            "Peak Global Event",
            "A peak global sports-scale event with high regional variance, heavier personalization, and multiple live channels.",
            "peak_event",
            "customer_demo_ready_with_caveats",
            {
                "average_viewer_hours_per_month": (30, "viewer-hours/month"),
                "average_bitrate_mbps": (22, "Mbps"),
                "region_traffic_mix": ("global high-variance", None),
                "cdn_cache_hit_ratio": (0.80, "ratio"),
                "live_channel_count": (6, "channels"),
                "event_hours_per_month": (720, "hours/month"),
                "ad_decision_requests_per_month": (500000000, "requests/month"),
                "drm_license_requests_per_month": (100000000, "requests/month"),
                "edge_function_invocations_per_month": (1000000000, "requests/month"),
                "origin_request_count_per_month": (250000000, "requests/month"),
                "archive_storage_gb_month": (50000, "GB-month"),
            },
        ),
    ]


def scenario_profile(profile_id: str) -> ScenarioProfile | None:
    return next((profile for profile in live_media_scenario_profiles() if profile.id == profile_id), None)


def _profile(
    profile_id: str,
    family: str,
    label: str,
    description: str,
    intended_use: ScenarioUse,
    readiness_impact: ScenarioReadinessImpact,
    values: dict[str, tuple[Any, str | None]],
) -> ScenarioProfile:
    assumptions = [
        ScenarioAssumption(
            driver_name=name,
            value=value,
            unit=unit,
            statement=f"{name} is supplied by scenario profile '{label}'.",
            validation_method="Confirm with media traffic forecast, CDN logs, streaming ladder, DRM/ad platform reports, or event schedule before budgeting.",
        )
        for name, (value, unit) in values.items()
    ]
    return ScenarioProfile(
        id=profile_id,
        workload_family=family,
        label=label,
        description=description,
        intended_use=intended_use,
        assumptions=assumptions,
        driver_values={name: value for name, (value, _unit) in values.items()},
        readiness_impact=readiness_impact,
    )
