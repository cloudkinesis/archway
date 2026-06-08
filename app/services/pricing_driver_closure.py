from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.pricing_driver_selector import PricingDriverFamily
from app.services.pricing_scenario_profiles import ScenarioProfile, live_media_scenario_profiles


PricingClosureStatus = Literal["complete", "complete_with_assumptions", "missing_non_critical", "missing_critical", "invalid"]
PricingMaturity = Literal[
    "pricing_not_available",
    "pricing_placeholder_only",
    "pricing_directional_with_assumptions",
    "pricing_customer_demo_ready",
    "pricing_procurement_ready",
]
CheckpointAction = Literal["ask_checkpoint", "use_scenario_profile", "proceed_without_headline", "ready_for_directional_pricing", "ready_for_procurement_pricing"]
DriverInputType = Literal["number", "percentage", "choice", "distribution", "duration", "unknown"]
DriverImpactArea = Literal["cdn_egress", "edge_compute", "media_encoding", "ad_decisioning", "drm", "storage", "analytics", "observability", "overall"]


class MissingPricingDriver(BaseModel):
    driver_name: str
    display_name: str
    why_needed: str
    impact_area: DriverImpactArea
    required_for_headline_pricing: bool
    can_use_scenario_default: bool = True
    suggested_question: str
    allowed_input_type: DriverInputType
    recommended_default: Any = None
    low_default: Any = None
    expected_default: Any = None
    high_default: Any = None


class PricingCheckpointOption(BaseModel):
    id: str
    label: str
    description: str
    driver_values: dict[str, Any] = Field(default_factory=dict)


class PricingCheckpointQuestion(BaseModel):
    id: str
    driver_names: list[str]
    prompt: str
    options: list[PricingCheckpointOption] = Field(default_factory=list)
    allow_custom_value: bool = False


class PricingCheckpoint(BaseModel):
    session_id: str | None = None
    workload_family: str
    message: str
    questions: list[PricingCheckpointQuestion] = Field(default_factory=list)
    scenario_profiles: list[ScenarioProfile] = Field(default_factory=list)
    actions: list[CheckpointAction] = Field(default_factory=list)
    closure_report: "PricingDriverClosureReport"


class PricingDriverClosureReport(BaseModel):
    workload_family: str
    status: PricingClosureStatus
    pricing_maturity: PricingMaturity
    confirmed_drivers: list[str] = Field(default_factory=list)
    assumed_drivers: list[str] = Field(default_factory=list)
    missing_drivers: list[MissingPricingDriver] = Field(default_factory=list)
    headline_pricing_allowed: bool = False
    directional_scenario_allowed: bool = False
    procurement_ready: bool = False
    scenario_profile_used: str | None = None
    recommended_next_action: CheckpointAction
    next_validation_steps: list[str] = Field(default_factory=list)


LIVE_MEDIA_DRIVER_CATALOG: dict[str, MissingPricingDriver] = {
    "average_viewer_hours_per_month": MissingPricingDriver(
        driver_name="average_viewer_hours_per_month",
        display_name="Average viewer watch time",
        why_needed="CloudFront, origin, analytics, and logging costs scale with total viewer-hours.",
        impact_area="cdn_egress",
        required_for_headline_pricing=True,
        suggested_question="How much content does an average viewer watch per month?",
        allowed_input_type="duration",
        low_default=5,
        expected_default=20,
        high_default=30,
        recommended_default=20,
    ),
    "average_bitrate_mbps": MissingPricingDriver(
        driver_name="average_bitrate_mbps",
        display_name="Average delivered bitrate",
        why_needed="CDN egress and origin transfer costs scale directly with delivered bitrate.",
        impact_area="cdn_egress",
        required_for_headline_pricing=True,
        suggested_question="Which average delivered bitrate should Archway model?",
        allowed_input_type="number",
        low_default=8,
        expected_default=15,
        high_default=22,
        recommended_default=15,
    ),
    "region_traffic_mix": MissingPricingDriver(
        driver_name="region_traffic_mix",
        display_name="Regional traffic mix",
        why_needed="CloudFront data transfer pricing depends on geography and price class.",
        impact_area="cdn_egress",
        required_for_headline_pricing=True,
        suggested_question="Which regional traffic mix is closest?",
        allowed_input_type="distribution",
        recommended_default="global balanced across 40 countries",
    ),
    "cdn_cache_hit_ratio": MissingPricingDriver(
        driver_name="cdn_cache_hit_ratio",
        display_name="CDN cache hit ratio",
        why_needed="Cache behavior affects origin request, packaging, and storage-related traffic.",
        impact_area="cdn_egress",
        required_for_headline_pricing=True,
        suggested_question="How efficient should CDN caching be?",
        allowed_input_type="percentage",
        low_default=0.80,
        expected_default=0.85,
        high_default=0.95,
        recommended_default=0.85,
    ),
    "live_channel_count": MissingPricingDriver(
        driver_name="live_channel_count",
        display_name="Live channel count",
        why_needed="MediaLive and packaging costs scale with simultaneous live channels.",
        impact_area="media_encoding",
        required_for_headline_pricing=True,
        suggested_question="How many simultaneous live channels/events should Archway model?",
        allowed_input_type="number",
        low_default=1,
        expected_default=4,
        high_default=6,
        recommended_default=4,
    ),
    "event_hours_per_month": MissingPricingDriver(
        driver_name="event_hours_per_month",
        display_name="Live event hours",
        why_needed="Encoding, origin, and archive costs scale with live event runtime.",
        impact_area="media_encoding",
        required_for_headline_pricing=True,
        suggested_question="How many live event hours per month should Archway model?",
        allowed_input_type="duration",
        low_default=40,
        expected_default=240,
        high_default=720,
        recommended_default=240,
    ),
    "ad_decision_requests_per_month": MissingPricingDriver(
        driver_name="ad_decision_requests_per_month",
        display_name="Ad decision requests",
        why_needed="Server-side ad insertion and ad-decisioning have request-driven cost and integration scale.",
        impact_area="ad_decisioning",
        required_for_headline_pricing=False,
        suggested_question="How much ad decisioning should Archway model?",
        allowed_input_type="number",
        recommended_default=150000000,
    ),
    "drm_license_requests_per_month": MissingPricingDriver(
        driver_name="drm_license_requests_per_month",
        display_name="DRM license requests",
        why_needed="DRM and entitlement integrations create request-driven cost and capacity needs.",
        impact_area="drm",
        required_for_headline_pricing=False,
        suggested_question="How many DRM license requests should Archway model?",
        allowed_input_type="number",
        recommended_default=25000000,
    ),
    "origin_request_count_per_month": MissingPricingDriver(
        driver_name="origin_request_count_per_month",
        display_name="Origin requests",
        why_needed="Origin and packaging systems scale with cache miss and personalization behavior.",
        impact_area="cdn_egress",
        required_for_headline_pricing=False,
        suggested_question="How many origin requests should Archway model?",
        allowed_input_type="number",
        recommended_default=75000000,
    ),
    "archive_storage_gb_month": MissingPricingDriver(
        driver_name="archive_storage_gb_month",
        display_name="Archive storage",
        why_needed="Replay/archive retention influences S3 and analytics storage cost.",
        impact_area="storage",
        required_for_headline_pricing=False,
        suggested_question="How much archive storage should Archway model?",
        allowed_input_type="number",
        recommended_default=10000,
    ),
}

LIVE_MEDIA_CRITICAL_DRIVERS = {
    "concurrent_viewers",
    "average_viewer_hours_per_month",
    "average_bitrate_mbps",
    "region_traffic_mix",
    "cdn_cache_hit_ratio",
    "live_channel_count",
    "event_hours_per_month",
}


def build_pricing_driver_closure(pricing: dict[str, Any] | Any, *, scenario_profile_used: str | None = None, proceed_without_headline: bool = False) -> PricingDriverClosureReport:
    payload = pricing if isinstance(pricing, dict) else pricing.model_dump(mode="json")
    metadata = payload.get("metadata") or {}
    compiler = metadata.get("source_truth_pricing_compiler") or {}
    family = compiler.get("workload_family") or metadata.get("pricing_driver_family") or "generic_directional"
    bindings = metadata.get("pricing_driver_bindings") or []
    assumptions = {
        item.get("id"): item
        for item in ((metadata.get("assumption_ledger") or {}).get("assumptions") or [])
        if item.get("id")
    }
    ledger_summary = (metadata.get("pricing_ledger") or {}).get("summary") or {}
    if family != PricingDriverFamily.LIVE_MEDIA_STREAMING.value:
        return _generic_report(family, ledger_summary)

    confirmed = [item["driver_name"] for item in bindings if item.get("status") == "confirmed"]
    assumed = [item["driver_name"] for item in bindings if item.get("status") in {"assumed", "derived"}]
    missing = [
        _missing_driver(item.get("driver_name"))
        for item in bindings
        if _binding_still_missing(item, assumptions, scenario_profile_used) and _missing_driver(item.get("driver_name")) is not None
    ]
    missing = [item for item in missing if item is not None]
    critical_missing = [item for item in missing if item.required_for_headline_pricing]
    procurement_ready = bool(ledger_summary.get("procurement_ready"))
    if procurement_ready:
        maturity: PricingMaturity = "pricing_procurement_ready"
        status: PricingClosureStatus = "complete"
        next_action: CheckpointAction = "ready_for_procurement_pricing"
        headline_allowed = True
        directional_allowed = True
    elif proceed_without_headline:
        maturity = "pricing_placeholder_only"
        status = "missing_critical" if critical_missing else "missing_non_critical"
        next_action = "proceed_without_headline"
        headline_allowed = False
        directional_allowed = False
    elif scenario_profile_used and not critical_missing:
        maturity = "pricing_customer_demo_ready"
        status = "complete_with_assumptions"
        next_action = "ready_for_directional_pricing"
        headline_allowed = False
        directional_allowed = True
    elif scenario_profile_used:
        maturity = "pricing_directional_with_assumptions"
        status = "missing_non_critical" if not critical_missing else "missing_critical"
        next_action = "ask_checkpoint"
        headline_allowed = False
        directional_allowed = True
    elif critical_missing:
        maturity = "pricing_directional_with_assumptions"
        status = "missing_critical"
        next_action = "ask_checkpoint"
        headline_allowed = False
        directional_allowed = False
    elif missing:
        maturity = "pricing_directional_with_assumptions"
        status = "missing_non_critical"
        next_action = "use_scenario_profile"
        headline_allowed = False
        directional_allowed = True
    else:
        maturity = "pricing_directional_with_assumptions"
        status = "complete_with_assumptions"
        next_action = "ready_for_directional_pricing"
        headline_allowed = False
        directional_allowed = True
    return PricingDriverClosureReport(
        workload_family=family,
        status=status,
        pricing_maturity=maturity,
        confirmed_drivers=confirmed,
        assumed_drivers=assumed,
        missing_drivers=missing,
        headline_pricing_allowed=headline_allowed,
        directional_scenario_allowed=directional_allowed,
        procurement_ready=procurement_ready,
        scenario_profile_used=scenario_profile_used,
        recommended_next_action=next_action,
        next_validation_steps=_validation_steps(missing),
    )


def build_pricing_checkpoint(pricing: dict[str, Any] | Any, *, session_id: str | None = None, state: dict[str, Any] | None = None) -> PricingCheckpoint:
    scenario_profile_used = (state or {}).get("scenario_profile_used")
    proceed_without_headline = bool((state or {}).get("proceed_without_headline"))
    closure = build_pricing_driver_closure(pricing, scenario_profile_used=scenario_profile_used, proceed_without_headline=proceed_without_headline)
    missing = closure.missing_drivers
    question_driver_names = {item.driver_name for item in missing}
    questions = _live_media_questions(question_driver_names) if closure.workload_family == PricingDriverFamily.LIVE_MEDIA_STREAMING.value else []
    actions: list[CheckpointAction] = ["proceed_without_headline"]
    if questions:
        actions.insert(0, "ask_checkpoint")
    if closure.workload_family == PricingDriverFamily.LIVE_MEDIA_STREAMING.value:
        actions.insert(1 if questions else 0, "use_scenario_profile")
    if closure.status in {"complete", "complete_with_assumptions", "missing_non_critical"}:
        actions.append("ready_for_directional_pricing")
    return PricingCheckpoint(
        session_id=session_id,
        workload_family=closure.workload_family,
        message=f"Archway can continue, but pricing will be more useful if we close {len(missing)} workload-specific drivers.",
        questions=questions,
        scenario_profiles=live_media_scenario_profiles() if closure.workload_family == PricingDriverFamily.LIVE_MEDIA_STREAMING.value else [],
        actions=list(dict.fromkeys(actions)),
        closure_report=closure,
    )


def _generic_report(family: str, ledger_summary: dict[str, Any]) -> PricingDriverClosureReport:
    procurement_ready = bool(ledger_summary.get("procurement_ready"))
    return PricingDriverClosureReport(
        workload_family=family,
        status="complete" if procurement_ready else "missing_non_critical",
        pricing_maturity="pricing_procurement_ready" if procurement_ready else "pricing_directional_with_assumptions",
        headline_pricing_allowed=procurement_ready,
        directional_scenario_allowed=not procurement_ready,
        procurement_ready=procurement_ready,
        recommended_next_action="ready_for_procurement_pricing" if procurement_ready else "ready_for_directional_pricing",
        next_validation_steps=["Confirm workload-specific usage quantities and exact AWS SKU/tier rates before procurement."],
    )


def _missing_driver(name: str | None) -> MissingPricingDriver | None:
    if not name:
        return None
    return LIVE_MEDIA_DRIVER_CATALOG.get(name)


def _binding_still_missing(binding: dict[str, Any], assumptions: dict[str, dict[str, Any]], scenario_profile_used: str | None) -> bool:
    status = binding.get("status")
    if status == "missing":
        return True
    if status != "assumed":
        return False
    assumption = assumptions.get(binding.get("assumption_id"))
    if scenario_profile_used and assumption and assumption.get("source") == "scenario_profile":
        return False
    return True


def _validation_steps(missing: list[MissingPricingDriver]) -> list[str]:
    if not missing:
        return ["Replace scenario assumptions with measured traffic forecast, CDN logs, event schedule, and media platform reports before budgeting."]
    return [f"Confirm {item.display_name}: {item.why_needed}" for item in missing[:8]]


def _live_media_questions(driver_names: set[str]) -> list[PricingCheckpointQuestion]:
    questions = [
        PricingCheckpointQuestion(
            id="viewer_watch_time",
            driver_names=["average_viewer_hours_per_month"],
            prompt="How much content does an average viewer watch per month?",
            options=[
                PricingCheckpointOption(id="short_clips", label="Short clips/highlights", description="Model 5 viewer-hours per month.", driver_values={"average_viewer_hours_per_month": 5}),
                PricingCheckpointOption(id="typical_sports", label="Typical sports session", description="Model 10 viewer-hours per month.", driver_values={"average_viewer_hours_per_month": 10}),
                PricingCheckpointOption(id="full_events", label="Full match/event", description="Model 20 viewer-hours per month.", driver_values={"average_viewer_hours_per_month": 20}),
                PricingCheckpointOption(id="marathon", label="Multi-event marathon", description="Model 30 viewer-hours per month.", driver_values={"average_viewer_hours_per_month": 30}),
            ],
            allow_custom_value=True,
        ),
        PricingCheckpointQuestion(
            id="average_bitrate",
            driver_names=["average_bitrate_mbps"],
            prompt="Which average delivered bitrate should Archway use?",
            options=[
                PricingCheckpointOption(id="optimized_abr", label="Optimized ABR", description="Model 8 Mbps.", driver_values={"average_bitrate_mbps": 8}),
                PricingCheckpointOption(id="high_quality_4k", label="High-quality 4K", description="Model 15 Mbps.", driver_values={"average_bitrate_mbps": 15}),
                PricingCheckpointOption(id="premium_4k_hdr", label="Premium 4K HDR", description="Model 22 Mbps.", driver_values={"average_bitrate_mbps": 22}),
            ],
            allow_custom_value=True,
        ),
        PricingCheckpointQuestion(
            id="regional_mix",
            driver_names=["region_traffic_mix"],
            prompt="CloudFront pricing depends on geography. Which traffic mix is closest?",
            options=[
                PricingCheckpointOption(id="na_eu", label="Mostly North America / Europe", description="Model mostly NA/EU transfer.", driver_values={"region_traffic_mix": "mostly North America / Europe"}),
                PricingCheckpointOption(id="global_balanced", label="Global balanced", description="Model a balanced 40-country audience.", driver_values={"region_traffic_mix": "global balanced across 40 countries"}),
                PricingCheckpointOption(id="heavy_apac_latam", label="Heavy APAC / LATAM", description="Model higher-variance global delivery.", driver_values={"region_traffic_mix": "heavy APAC / Latin America / emerging regions"}),
            ],
            allow_custom_value=True,
        ),
        PricingCheckpointQuestion(
            id="cache_behavior",
            driver_names=["cdn_cache_hit_ratio", "origin_request_count_per_month"],
            prompt="Which CDN cache/origin behavior is closest?",
            options=[
                PricingCheckpointOption(id="high_cache", label="High cache efficiency", description="Model 95% cache hit ratio.", driver_values={"cdn_cache_hit_ratio": 0.95}),
                PricingCheckpointOption(id="moderate_cache", label="Moderate cache efficiency", description="Model 85% cache hit ratio.", driver_values={"cdn_cache_hit_ratio": 0.85}),
                PricingCheckpointOption(id="low_cache", label="Low cache efficiency", description="Model 80% cache hit ratio.", driver_values={"cdn_cache_hit_ratio": 0.80}),
            ],
            allow_custom_value=True,
        ),
        PricingCheckpointQuestion(
            id="monetization_rights",
            driver_names=["ad_decision_requests_per_month", "drm_license_requests_per_month"],
            prompt="Which ad decisioning and DRM mode should Archway model?",
            options=[
                PricingCheckpointOption(id="poc_low", label="POC / low personalization", description="Model low ad and DRM request volume.", driver_values={"ad_decision_requests_per_month": 0, "drm_license_requests_per_month": 10000}),
                PricingCheckpointOption(id="moderate", label="Moderate ad + DRM", description="Model regional production ad and DRM requests.", driver_values={"ad_decision_requests_per_month": 3000000, "drm_license_requests_per_month": 1000000}),
                PricingCheckpointOption(id="heavy", label="Heavy personalization", description="Model major-event ad and DRM requests.", driver_values={"ad_decision_requests_per_month": 150000000, "drm_license_requests_per_month": 25000000}),
            ],
            allow_custom_value=True,
        ),
    ]
    return [question for question in questions if set(question.driver_names) & driver_names]


PricingCheckpoint.model_rebuild()
