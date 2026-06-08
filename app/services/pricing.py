from dataclasses import asdict, dataclass, field
from typing import Any

from app.domain.assumption_profiles import INDUSTRIAL_IOT_DEFAULT_ASSUMPTIONS
from app.domain.pricing_drivers import (
    IndustrialIoTPricingModel,
    MLScoringPricingDrivers,
    StreamProcessingPricingDrivers,
    TelemetryPricingDrivers,
    WorkflowPricingDrivers,
)
from app.models.domain import AWSServiceSelection, EvidenceItem, PricingAnalysis, PricingLineItem, UseCaseBrief
from app.services.pattern_catalog import pricing_dimensions
from app.services.pricing_driver_selector import PricingDriverFamily, select_pricing_driver_family
from app.services.source_truth_pricing_compiler import SourceTruthPricingCompiler
from app.services.use_case_profile import UseCaseProfile, profile_from_metadata


@dataclass(frozen=True)
class PricingDrivers:
    asset_count: int
    telemetry_frequency_seconds: int
    payload_kb: float
    daily_event_volume: int
    monthly_event_volume: int
    stream_retention_hours: int
    hot_retention_days: int
    cold_retention_months: int
    flink_kpu_hours: int
    feature_windows_per_day: int
    inference_events_per_day: int
    sagemaker_endpoint_hours: int
    candidate_anomalies_per_day: int
    confirmed_incidents_per_day: int
    workflow_executions_per_day: int
    state_transitions_per_execution: int
    integration_api_calls_per_day: int
    notification_events_per_day: int
    scoring_strategy: str
    source: str
    positions_count: int = 0
    exchange_count: int = 0
    risk_windows_per_day: int = 0
    risk_compute_jobs_per_day: int = 0
    hpc_compute_hours_per_month: int = 0
    risk_grid_nodes: int = 0
    market_data_ingest_gb_per_day: float = 0.0
    result_storage_gb_per_month: float = 0.0
    audit_storage_gb_steady_state: float = 0.0
    reporting_query_tb_scanned_monthly: float = 0.0
    cache_node_hours_monthly: int = 0
    pricing_driver_family: str = "generic_directional"
    average_viewer_hours_per_month: float = 0.0
    average_bitrate_mbps: float = 0.0
    region_traffic_mix: str | None = None
    cdn_cache_hit_ratio: float = 0.0
    live_channel_count: int = 0
    event_hours_per_month: int = 0
    drm_license_requests_per_month: int = 0
    ad_decision_requests_per_month: int = 0
    edge_function_invocations_per_month: int = 0
    origin_request_count_per_month: int = 0
    archive_storage_gb_month: float = 0.0
    scenario_profile_id: str | None = None
    pricing_driver_overrides: dict[str, Any] = field(default_factory=dict)
    hospital_count: int = 0
    operating_room_count: int = 0
    active_or_count_poc: int = 0
    scheduled_surgeries_per_day: int = 0
    refresh_cadence_minutes: int = 0
    recommendation_runs_per_day: int = 0
    approval_workflow_executions_per_day: int = 0
    ehr_writeback_attempts_per_day: int = 0
    occupancy_readiness_events_per_day: int = 0
    active_coordinator_users: int = 0


class PricingEngine:
    async def estimate(self, brief: UseCaseBrief, service_plan: list[AWSServiceSelection], pricing_driver_overrides: dict[str, Any] | None = None) -> PricingAnalysis:
        profile = profile_from_metadata(brief.use_case_profile, brief.raw_use_case)
        driver_family = select_pricing_driver_family(profile)
        drivers = derive_pricing_drivers(profile, pricing_driver_overrides=pricing_driver_overrides)
        validation = _pricing_validation(profile, drivers)
        evidence = [
            EvidenceItem(
                source_type="local_policy",
                title="Archway deterministic pricing driver model",
                quote_or_summary=(
                    "Pricing uses extracted workload facts plus conservative local assumptions when live AWS pricing is unavailable. "
                    f"Drivers: {asdict(drivers)}"
                ),
                tool_name="local_policy",
                confidence="medium",
            )
        ]
        catalog = _catalog(drivers)
        line_items: list[PricingLineItem] = []
        for item in service_plan:
            key = _catalog_key(item.service)
            low, expected, high, basis, scale = catalog.get(key, (20, 60, 180, "usage-based managed service charges", 1.0))
            line_items.append(
                PricingLineItem(
                    service=item.service,
                    unit_basis=basis,
                    low_monthly_usd=round(low * scale, 2),
                    expected_monthly_usd=round(expected * scale, 2),
                    high_monthly_usd=round(high * scale, 2),
                    assumptions=_line_assumptions(brief, drivers),
                    evidence_ids=[evidence[0].id],
                    pricing_trace={
                        "calculation_source": drivers.source,
                        "procurement_ready": False,
                        "scale_applied": validation["scale_applied"],
                        "pricing_validity": validation["status"],
                        "reason": validation["reason"],
                        **_pricing_formula_trace(item.service, drivers, low * scale, expected * scale, high * scale),
                    },
                )
            )
        low_total = round(sum(item.low_monthly_usd for item in line_items), 2)
        expected_total = round(sum(item.expected_monthly_usd for item in line_items), 2)
        high_total = round(sum(item.high_monthly_usd for item in line_items), 2)
        analysis = PricingAnalysis(
            region="us-east-1",
            low_monthly_usd=low_total,
            expected_monthly_usd=expected_total,
            high_monthly_usd=high_total,
            line_items=line_items,
            main_cost_drivers=_known_cost_drivers(profile, drivers),
            cost_optimization_recommendations=_cost_optimization_recommendations(drivers),
            unknown_variables=_unknown_variables(profile),
            evidence_items=evidence,
            metadata=validation,
        )
        return SourceTruthPricingCompiler().compile(profile=profile, drivers=drivers, pricing=analysis)


def derive_pricing_drivers(profile: UseCaseProfile, pricing_driver_overrides: dict[str, Any] | None = None) -> PricingDrivers:
    selected_family = select_pricing_driver_family(profile)
    overrides = pricing_driver_overrides or _profile_pricing_overrides(profile)
    if selected_family == PricingDriverFamily.HEALTHCARE_OPERATIONS_SCHEDULING:
        hospital_count = int(_structured_metric(profile, "asset_counts", "hospital_count") or _metric_value(profile, "hospital_count") or _metric_max(profile, ("hospital",)) or 1)
        operating_room_count = int(_structured_metric(profile, "asset_counts", "operating_room_count") or _metric_value(profile, "operating_room_count") or _metric_max(profile, ("operating_room", "operating_rooms")) or 8)
        active_or_count_poc = int(overrides.get("active_or_count_poc") or min(operating_room_count, 8))
        refresh_cadence_minutes = int(_structured_metric(profile, "business_targets", "refresh_cadence_minutes") or _metric_value(profile, "refresh_cadence_minutes") or 2)
        scheduled_surgeries_per_day = int(_structured_metric(profile, "business_targets", "scheduled_surgeries_per_day") or _metric_value(profile, "scheduled_surgeries_per_day") or max(active_or_count_poc * 4, 16))
        operating_hours_per_day = int(overrides.get("operating_hours_per_day") or 12)
        recommendation_runs_per_day = max(1, int(active_or_count_poc * (operating_hours_per_day * 60 / max(1, refresh_cadence_minutes))))
        approval_workflows = int(overrides.get("approval_workflow_executions_per_day") or max(1, scheduled_surgeries_per_day // 4))
        ehr_writebacks = int(overrides.get("ehr_writeback_attempts_per_day") or approval_workflows)
        occupancy_events = int(overrides.get("occupancy_readiness_events_per_day") or max(scheduled_surgeries_per_day * 8, active_or_count_poc * operating_hours_per_day * 12))
        audit_years = int(_structured_metric(profile, "business_targets", "audit_retention_years") or _metric_value(profile, "audit_retention_years") or 7)
        active_users = int(overrides.get("active_coordinator_users") or max(10, active_or_count_poc * 2))
        return PricingDrivers(
            asset_count=active_or_count_poc,
            telemetry_frequency_seconds=refresh_cadence_minutes * 60,
            payload_kb=2.0,
            daily_event_volume=occupancy_events,
            monthly_event_volume=occupancy_events * 30,
            stream_retention_hours=24,
            hot_retention_days=90,
            cold_retention_months=audit_years * 12,
            flink_kpu_hours=max(720, int((occupancy_events / 1_000_000) * 720) or 720),
            feature_windows_per_day=recommendation_runs_per_day,
            inference_events_per_day=recommendation_runs_per_day,
            sagemaker_endpoint_hours=720,
            candidate_anomalies_per_day=approval_workflows,
            confirmed_incidents_per_day=0,
            workflow_executions_per_day=approval_workflows,
            state_transitions_per_execution=10,
            integration_api_calls_per_day=ehr_writebacks + occupancy_events,
            notification_events_per_day=approval_workflows + active_users,
            scoring_strategy="score_active_or_windows_by_refresh_cadence",
            source="healthcare_or_extracted_operating_room_metrics",
            pricing_driver_family=PricingDriverFamily.HEALTHCARE_OPERATIONS_SCHEDULING.value,
            pricing_driver_overrides=overrides,
            hospital_count=hospital_count,
            operating_room_count=operating_room_count,
            active_or_count_poc=active_or_count_poc,
            scheduled_surgeries_per_day=scheduled_surgeries_per_day,
            refresh_cadence_minutes=refresh_cadence_minutes,
            recommendation_runs_per_day=recommendation_runs_per_day,
            approval_workflow_executions_per_day=approval_workflows,
            ehr_writeback_attempts_per_day=ehr_writebacks,
            occupancy_readiness_events_per_day=occupancy_events,
            active_coordinator_users=active_users,
        )
    if selected_family == PricingDriverFamily.DOCUMENT_RAG_WORKFLOW:
        document_count = int(
            _structured_metric(profile, "asset_counts", "historical_contract_count")
            or _structured_metric(profile, "asset_counts", "document_count")
            or _metric_value(profile, "historical_contract_count")
            or _metric_value(profile, "document_count")
            or 1_000
        )
        rag_queries_per_day = int(overrides.get("rag_queries_per_day") or max(250, document_count // 10))
        new_documents_per_month = int(overrides.get("new_or_updated_documents_per_month") or max(25, document_count // 20))
        approval_workflows = int(overrides.get("obligation_review_approvals_per_month") or max(50, new_documents_per_month * 2))
        audit_months = int(overrides.get("audit_retention_months") or 84)
        active_users = int(overrides.get("active_legal_users") or 25)
        average_document_mb = float(overrides.get("average_document_mb") or 1.5)
        return PricingDrivers(
            asset_count=document_count,
            telemetry_frequency_seconds=0,
            payload_kb=average_document_mb * 1024,
            daily_event_volume=rag_queries_per_day + max(1, new_documents_per_month // 30),
            monthly_event_volume=rag_queries_per_day * 30 + new_documents_per_month,
            stream_retention_hours=0,
            hot_retention_days=90,
            cold_retention_months=audit_months,
            flink_kpu_hours=0,
            feature_windows_per_day=max(1, new_documents_per_month // 30),
            inference_events_per_day=rag_queries_per_day,
            sagemaker_endpoint_hours=720,
            candidate_anomalies_per_day=max(1, approval_workflows // 30),
            confirmed_incidents_per_day=0,
            workflow_executions_per_day=max(1, approval_workflows // 30),
            state_transitions_per_execution=8,
            integration_api_calls_per_day=max(1, new_documents_per_month // 30) + max(1, approval_workflows // 30),
            notification_events_per_day=active_users,
            scoring_strategy="rag_query_and_document_ingestion_directional_model",
            source="document_rag_workflow_extracted_contract_metrics",
            pricing_driver_family=PricingDriverFamily.DOCUMENT_RAG_WORKFLOW.value,
            pricing_driver_overrides=overrides,
            result_storage_gb_per_month=document_count * average_document_mb,
            audit_storage_gb_steady_state=document_count * average_document_mb,
            reporting_query_tb_scanned_monthly=max(0.1, document_count * average_document_mb / 1024),
        )
    if _is_financial_fraud_profile(profile):
        transactions_per_day = int(_structured_metric(profile, "business_targets", "transactions_per_day") or _metric_value(profile, "transactions_per_day") or _metric_max(profile, ("transaction",)) or 100_000)
        latency_ms = int(_structured_metric(profile, "business_targets", "latency_target_ms") or _metric_value(profile, "latency_target_ms") or 250)
        audit_years = int(_structured_metric(profile, "business_targets", "audit_retention_years") or _metric_value(profile, "audit_retention_years") or _structured_metric(profile, "business_targets", "retention_years") or 7)
        scoring_events_per_day = transactions_per_day
        case_creation_rate = 0.01
        block_rate = 0.001
        candidate_cases = max(1, int(transactions_per_day * case_creation_rate))
        confirmed_blocks = max(1, int(transactions_per_day * block_rate))
        peak_multiplier = 5 if latency_ms <= 250 else 3
        return PricingDrivers(
            asset_count=transactions_per_day,
            telemetry_frequency_seconds=1,
            payload_kb=2.0,
            daily_event_volume=transactions_per_day,
            monthly_event_volume=transactions_per_day * 30,
            stream_retention_hours=24,
            hot_retention_days=90,
            cold_retention_months=audit_years * 12,
            flink_kpu_hours=max(720, int((transactions_per_day / 10_000_000) * 720 * peak_multiplier)),
            feature_windows_per_day=scoring_events_per_day,
            inference_events_per_day=scoring_events_per_day,
            sagemaker_endpoint_hours=max(720, 720 * min(8, peak_multiplier)),
            candidate_anomalies_per_day=candidate_cases,
            confirmed_incidents_per_day=confirmed_blocks,
            workflow_executions_per_day=candidate_cases if profile.actions else max(1, candidate_cases),
            state_transitions_per_execution=12,
            integration_api_calls_per_day=max(1, candidate_cases + confirmed_blocks),
            notification_events_per_day=max(1, candidate_cases),
            scoring_strategy="score_every_transaction_under_latency_target",
            source="financial_fraud_extracted_transaction_metrics",
            pricing_driver_family=PricingDriverFamily.PAYMENT_FRAUD_SCORING.value,
        )
    if selected_family == PricingDriverFamily.LIVE_MEDIA_STREAMING:
        concurrent_viewers = int(_structured_metric(profile, "business_targets", "concurrent_viewers") or _metric_value(profile, "concurrent_viewers") or _metric_max(profile, ("viewer",)) or 100_000)
        latency_seconds = int(_structured_metric(profile, "business_targets", "glass_to_glass_latency_seconds") or _metric_value(profile, "glass_to_glass_latency_seconds") or 10)
        countries = int(_structured_metric(profile, "business_targets", "country_count") or _metric_value(profile, "country_count") or 1)
        assumed_bitrate_mbps = float(overrides.get("average_bitrate_mbps") or (18.0 if any(term in set(profile.capabilities + profile.capability_model) for term in ("video_streaming", "low_latency_media_delivery")) else 6.0))
        average_viewer_hours_per_month = float(overrides.get("average_viewer_hours_per_month") or 90)
        live_channel_count = int(overrides.get("live_channel_count") or 1)
        event_hours_per_month = int(overrides.get("event_hours_per_month") or 720)
        region_traffic_mix = str(overrides.get("region_traffic_mix") or ("global balanced across 40 countries" if countries > 1 else "mostly single region"))
        cdn_cache_hit_ratio = float(overrides.get("cdn_cache_hit_ratio") or 0.85)
        total_viewer_hours_per_month = max(1.0, concurrent_viewers * average_viewer_hours_per_month)
        cdn_egress_gb_per_day = total_viewer_hours_per_month / 30 * assumed_bitrate_mbps * 3600 / 8 / 1024
        default_ad_decisions_month = concurrent_viewers * 6 * 30 if "targeted_ad_decisioning" in set(profile.capabilities + profile.capability_model) else 0
        ad_decisions_per_month = int(overrides.get("ad_decision_requests_per_month") or default_ad_decisions_month)
        drm_license_requests_per_month = int(overrides.get("drm_license_requests_per_month") or max(concurrent_viewers, countries * 1000))
        edge_invocations_per_month = int(overrides.get("edge_function_invocations_per_month") or concurrent_viewers * 30)
        origin_requests_per_month = int(overrides.get("origin_request_count_per_month") or max(1, int(edge_invocations_per_month * (1 - cdn_cache_hit_ratio))))
        archive_storage_gb_month = float(overrides.get("archive_storage_gb_month") or 0)
        return PricingDrivers(
            asset_count=concurrent_viewers,
            telemetry_frequency_seconds=max(1, latency_seconds),
            payload_kb=assumed_bitrate_mbps * 125,
            daily_event_volume=max(concurrent_viewers, int(ad_decisions_per_month / 30)),
            monthly_event_volume=max(concurrent_viewers * 30, ad_decisions_per_month),
            stream_retention_hours=6,
            hot_retention_days=14,
            cold_retention_months=12,
            flink_kpu_hours=0,
            feature_windows_per_day=max(1, int(ad_decisions_per_month / 30)),
            inference_events_per_day=max(1, int(ad_decisions_per_month / 30)),
            sagemaker_endpoint_hours=0,
            candidate_anomalies_per_day=max(1, countries),
            confirmed_incidents_per_day=max(1, countries),
            workflow_executions_per_day=max(1, countries),
            state_transitions_per_execution=6,
            integration_api_calls_per_day=max(1, int(ad_decisions_per_month / 30)),
            notification_events_per_day=max(1, countries * 24),
            scoring_strategy="score_candidate_anomalies_only",
            source="live_media_streaming_extracted_viewer_metrics",
            market_data_ingest_gb_per_day=round(cdn_egress_gb_per_day, 2),
            reporting_query_tb_scanned_monthly=round(cdn_egress_gb_per_day * 30 / 1024 * 0.05, 2),
            pricing_driver_family=PricingDriverFamily.LIVE_MEDIA_STREAMING.value,
            average_viewer_hours_per_month=average_viewer_hours_per_month,
            average_bitrate_mbps=assumed_bitrate_mbps,
            region_traffic_mix=region_traffic_mix,
            cdn_cache_hit_ratio=cdn_cache_hit_ratio,
            live_channel_count=live_channel_count,
            event_hours_per_month=event_hours_per_month,
            drm_license_requests_per_month=drm_license_requests_per_month,
            ad_decision_requests_per_month=ad_decisions_per_month,
            edge_function_invocations_per_month=edge_invocations_per_month,
            origin_request_count_per_month=origin_requests_per_month,
            archive_storage_gb_month=archive_storage_gb_month,
            scenario_profile_id=str(overrides.get("scenario_profile_id")) if overrides.get("scenario_profile_id") else None,
            pricing_driver_overrides=overrides,
        )
    model = derive_industrial_iot_pricing_model(profile)
    if _is_streaming_ml_profile(profile):
        return _flatten_industrial_model(model)
    cdrs_per_day = _structured_metric(profile, "business_targets", "cdrs_per_day")
    if cdrs_per_day:
        asset_count = int(_structured_metric(profile, "asset_counts", "cell_towers") or _asset_count(profile) or 1)
        daily_event_volume = int(cdrs_per_day)
        monthly_event_volume = daily_event_volume * 30
        retention_years = int(_structured_metric(profile, "business_targets", "retention_years") or 2)
        prediction_minutes = int(_structured_metric(profile, "business_targets", "prediction_horizon_minutes") or 15)
        return PricingDrivers(
            asset_count=asset_count,
            telemetry_frequency_seconds=max(60, prediction_minutes * 60),
            payload_kb=1.0,
            daily_event_volume=daily_event_volume,
            monthly_event_volume=monthly_event_volume,
            stream_retention_hours=24,
            hot_retention_days=30,
            cold_retention_months=retention_years * 12,
            flink_kpu_hours=max(720, int((daily_event_volume / 50_000_000) * 24 * 30)),
            feature_windows_per_day=max(asset_count * int(1440 / max(1, prediction_minutes)), daily_event_volume // 1000),
            inference_events_per_day=max(asset_count * int(1440 / max(1, prediction_minutes)), daily_event_volume // 1000),
            sagemaker_endpoint_hours=720,
            candidate_anomalies_per_day=max(1, daily_event_volume // 100_000),
            confirmed_incidents_per_day=max(1, daily_event_volume // 10_000_000),
            workflow_executions_per_day=max(1, daily_event_volume // 10_000_000) if profile.actions else 0,
            state_transitions_per_execution=8,
            integration_api_calls_per_day=max(1, daily_event_volume // 10_000_000) if profile.actions else 0,
            notification_events_per_day=max(1, daily_event_volume // 1_000_000),
            scoring_strategy="score_aggregated_windows",
            source="telecom_cdr_extracted_metrics",
            pricing_driver_family=PricingDriverFamily.TELECOM_CDR_ANALYTICS.value,
        )
    positions = _structured_metric(profile, "asset_counts", "open_derivatives_positions")
    greeks_seconds = _structured_metric(profile, "business_targets", "greeks_frequency_seconds")
    if positions and greeks_seconds:
        positions_count = int(positions)
        exchanges = int(_structured_metric(profile, "asset_counts", "exchanges") or 1)
        risk_windows_per_day = int(86400 / max(1, int(greeks_seconds)))
        risk_compute_jobs_per_day = risk_windows_per_day
        risk_grid_nodes = max(16, exchanges * 4)
        hpc_compute_hours_per_month = int(risk_compute_jobs_per_day * 30 * risk_grid_nodes * 0.25)
        market_data_ingest_gb_per_day = float(exchanges * 50)
        result_storage_gb_per_month = round((positions_count * risk_windows_per_day * 30 * 0.25) / 1024 / 1024, 2)
        audit_storage_gb_steady_state = round(result_storage_gb_per_month * 84, 2)
        reporting_query_tb_scanned_monthly = round(max(10.0, result_storage_gb_per_month / 1024 * 0.2), 2)
        portfolio_state_ops_per_day = int(positions_count * risk_windows_per_day)
        return PricingDrivers(
            asset_count=positions_count,
            telemetry_frequency_seconds=int(greeks_seconds),
            payload_kb=0.25,
            daily_event_volume=risk_compute_jobs_per_day,
            monthly_event_volume=risk_compute_jobs_per_day * 30,
            stream_retention_hours=24,
            hot_retention_days=30,
            cold_retention_months=84,
            flink_kpu_hours=0,
            feature_windows_per_day=risk_windows_per_day,
            inference_events_per_day=risk_windows_per_day,
            sagemaker_endpoint_hours=0,
            candidate_anomalies_per_day=max(1, exchanges * risk_windows_per_day),
            confirmed_incidents_per_day=max(1, exchanges * 24),
            workflow_executions_per_day=risk_compute_jobs_per_day,
            state_transitions_per_execution=10,
            integration_api_calls_per_day=max(1, exchanges * 24),
            notification_events_per_day=max(1, exchanges * 24),
            scoring_strategy="portfolio_window_risk_recalculation",
            source="capital_markets_risk_extracted_metrics",
            pricing_driver_family=PricingDriverFamily.CAPITAL_MARKETS_RISK_ENGINE.value,
            positions_count=positions_count,
            exchange_count=exchanges,
            risk_windows_per_day=risk_windows_per_day,
            risk_compute_jobs_per_day=risk_compute_jobs_per_day,
            hpc_compute_hours_per_month=hpc_compute_hours_per_month,
            risk_grid_nodes=risk_grid_nodes,
            market_data_ingest_gb_per_day=market_data_ingest_gb_per_day,
            result_storage_gb_per_month=result_storage_gb_per_month,
            audit_storage_gb_steady_state=audit_storage_gb_steady_state,
            reporting_query_tb_scanned_monthly=reporting_query_tb_scanned_monthly,
            cache_node_hours_monthly=risk_grid_nodes * 720,
        )
    advisory_driver_names = _advisory_pricing_driver_names(profile)
    if advisory_driver_names and "real_time_ingestion" not in profile.capabilities:
        active_users = int(
            _structured_metric(profile, "asset_counts", "active_users")
            or _metric_value(profile, "active_users")
            or _metric_max(profile, ("user", "users"))
            or max(_asset_count(profile), 100)
        )
        api_requests_per_day = int(
            _structured_metric(profile, "business_targets", "requests_per_day")
            or _metric_value(profile, "requests_per_day")
            or max(5_000, active_users * 25)
        )
        background_jobs_per_day = int(
            _structured_metric(profile, "business_targets", "background_jobs_per_day")
            or _metric_value(profile, "background_jobs_per_day")
            or max(100, api_requests_per_day // 10)
        )
        approval_workflows_per_day = int(
            _structured_metric(profile, "business_targets", "approval_workflow_executions_per_day")
            or _metric_value(profile, "approval_workflow_executions_per_day")
            or (max(25, background_jobs_per_day // 5) if profile.actions else 0)
        )
        audit_months = int(
            _structured_metric(profile, "business_targets", "audit_retention_months")
            or _metric_value(profile, "audit_retention_months")
            or (_structured_metric(profile, "business_targets", "audit_retention_years") or 1) * 12
        )
        return PricingDrivers(
            asset_count=active_users,
            telemetry_frequency_seconds=0,
            payload_kb=0,
            daily_event_volume=api_requests_per_day + background_jobs_per_day,
            monthly_event_volume=(api_requests_per_day + background_jobs_per_day) * 30,
            stream_retention_hours=0,
            hot_retention_days=30,
            cold_retention_months=audit_months,
            flink_kpu_hours=0,
            feature_windows_per_day=background_jobs_per_day,
            inference_events_per_day=max(0, api_requests_per_day // 20) if "generative_ai" in profile.capabilities else 0,
            sagemaker_endpoint_hours=0,
            candidate_anomalies_per_day=max(0, approval_workflows_per_day),
            confirmed_incidents_per_day=0,
            workflow_executions_per_day=approval_workflows_per_day,
            state_transitions_per_execution=6 if approval_workflows_per_day else 3,
            integration_api_calls_per_day=max(0, approval_workflows_per_day),
            notification_events_per_day=max(active_users, approval_workflows_per_day),
            scoring_strategy="directional_discovery_driver_model",
            source="advisory_discovery_directional_model",
            pricing_driver_family=selected_family.value,
            result_storage_gb_per_month=round(max(10.0, active_users * 0.1), 2),
            reporting_query_tb_scanned_monthly=round(max(0.1, (api_requests_per_day * 30) / 10_000_000), 2),
            pricing_driver_overrides=overrides,
        )
    asset_count = _asset_count(profile)
    if asset_count == 0:
        asset_count = int(_metric_max(profile, ("request", "event", "message", "transaction")) or 1000)
    telemetry_frequency_seconds = 300
    payload_kb = 2.0
    if "real_time_ingestion" in profile.capabilities:
        telemetry_frequency_seconds = 60
    daily_event_volume = int(asset_count * 86400 / telemetry_frequency_seconds)
    monthly_event_volume = daily_event_volume * 30
    stream_retention_hours = 24
    hot_retention_days = 30
    cold_retention_months = 18 if any(metric.label == "target_timeline_months" for metric in profile.metrics) else 12
    flink_kpu_hours = max(720, int((daily_event_volume / 1_000_000) * 24))
    inference_events_per_day = daily_event_volume if "predictive_ml" in profile.capabilities else max(1000, daily_event_volume // 10)
    sagemaker_endpoint_hours = 720 if "predictive_ml" in profile.capabilities else 0
    workflow_executions_per_day = max(100, int(daily_event_volume * 0.001)) if profile.actions else 0
    integration_api_calls_per_day = workflow_executions_per_day * max(1, len(profile.actions))
    return PricingDrivers(
        asset_count=asset_count,
        telemetry_frequency_seconds=telemetry_frequency_seconds,
        payload_kb=payload_kb,
        daily_event_volume=daily_event_volume,
        monthly_event_volume=monthly_event_volume,
        stream_retention_hours=stream_retention_hours,
        hot_retention_days=hot_retention_days,
        cold_retention_months=cold_retention_months,
        flink_kpu_hours=flink_kpu_hours,
        feature_windows_per_day=max(0, daily_event_volume // 300),
        inference_events_per_day=inference_events_per_day,
        sagemaker_endpoint_hours=sagemaker_endpoint_hours,
        candidate_anomalies_per_day=workflow_executions_per_day,
        confirmed_incidents_per_day=workflow_executions_per_day,
        workflow_executions_per_day=workflow_executions_per_day,
        state_transitions_per_execution=8 if profile.actions else 3,
        integration_api_calls_per_day=integration_api_calls_per_day,
        notification_events_per_day=workflow_executions_per_day,
        scoring_strategy="score_every_event" if "predictive_ml" in profile.capabilities else "score_aggregated_windows",
        source="extracted_metrics_plus_conservative_defaults",
        pricing_driver_family=selected_family.value,
    )


def derive_industrial_iot_pricing_model(profile: UseCaseProfile) -> IndustrialIoTPricingModel:
    assumptions = INDUSTRIAL_IOT_DEFAULT_ASSUMPTIONS
    smart_meters = _metric_value(profile, "smart_meters")
    transformers = _metric_value(profile, "distribution_transformers") or _metric_value(profile, "transformers")
    asset_count = int(_structured_metric(profile, "asset_counts", "total_monitored_assets") or _asset_count(profile) or 1000)
    telemetry_frequency_seconds = int(assumptions["telemetry_frequency_seconds"]["expected"])
    payload_kb = float(assumptions["payload_kb"]["expected"])
    raw_samples_per_second = _structured_metric(profile, "business_targets", "raw_sensor_samples_per_second")
    sample_rate_khz = _structured_metric(profile, "business_targets", "streaming_sample_rate_khz")
    if raw_samples_per_second:
        telemetry_frequency_seconds = 1
        daily_raw = int(raw_samples_per_second * 86400)
    else:
        daily_raw = int(asset_count * 86400 / telemetry_frequency_seconds)
    monthly_raw = daily_raw * 30
    hot_retention_days = 30
    cold_retention_months = int(_structured_metric(profile, "business_targets", "target_timeline_months") or 12)
    aggregation_window_seconds = int(assumptions["aggregation_window_seconds"]["expected"])
    feature_windows_per_day = max(asset_count, int(asset_count * 86400 / aggregation_window_seconds))
    candidate_rate = float(assumptions["candidate_anomaly_rate_percent"]["expected"])
    confirmed_rate = float(assumptions["confirmed_incident_rate_percent"]["expected"])
    scoring_events = feature_windows_per_day
    candidate_anomalies = max(1, int(scoring_events * candidate_rate / 100))
    confirmed_incidents = max(1, int(candidate_anomalies * confirmed_rate / 100))
    flink_expected = max(1, int((daily_raw / 50_000_000) + 1))
    workflow_count = confirmed_incidents if profile.actions else 0
    assumptions_list = [
        "Assumption profile: balanced_production for industrial IoT telemetry until exact device frequency and payload size are confirmed.",
        f"Telemetry frequency {'derived from explicit kHz/channel scale' if sample_rate_khz else 'assumed'} at {telemetry_frequency_seconds} seconds; low/high profile values are {assumptions['telemetry_frequency_seconds']['low']}s and {assumptions['telemetry_frequency_seconds']['high']}s.",
        f"Payload size assumed at {payload_kb:g} KB; low/high profile values are {assumptions['payload_kb']['low']} KB and {assumptions['payload_kb']['high']} KB.",
        f"Candidate anomaly rate assumed at {candidate_rate:g}%; confirmed incident rate assumed at {confirmed_rate:g}%.",
        "ML scoring is priced on aggregated feature windows by default, not every raw telemetry event.",
        "Dispatch workflow, external API calls, and notifications are priced on confirmed incidents by default, not raw telemetry events.",
    ]
    unknowns = [
        "confirmed device telemetry frequency",
        "confirmed payload size",
        "measured candidate anomaly rate",
        "measured confirmed incident rate",
        "feature aggregation window",
        "model scoring strategy",
        "human approval rate",
    ]
    return IndustrialIoTPricingModel(
        telemetry=TelemetryPricingDrivers(
            asset_count=asset_count,
            smart_meter_count=int(smart_meters) if smart_meters else None,
            transformer_count=int(transformers) if transformers else None,
            telemetry_frequency_seconds=telemetry_frequency_seconds,
            payload_kb=payload_kb,
            daily_raw_event_volume=daily_raw,
            monthly_raw_event_volume=monthly_raw,
            hot_retention_days=hot_retention_days,
            cold_retention_months=cold_retention_months,
        ),
        stream_processing=StreamProcessingPricingDrivers(
            raw_events_per_day=daily_raw,
            aggregation_window_seconds=aggregation_window_seconds,
            feature_windows_per_day=feature_windows_per_day,
            estimated_flink_kpus_low=max(1, flink_expected // 2),
            estimated_flink_kpus_expected=flink_expected,
            estimated_flink_kpus_high=max(flink_expected + 1, flink_expected * 3),
        ),
        ml_scoring=MLScoringPricingDrivers(
            raw_events_per_day=daily_raw,
            scoring_strategy="score_aggregated_windows",
            scoring_events_per_day=scoring_events,
            candidate_anomaly_rate_percent=candidate_rate,
            confirmed_incident_rate_percent=confirmed_rate,
        ),
        workflow=WorkflowPricingDrivers(
            candidate_anomalies_per_day=candidate_anomalies,
            confirmed_incidents_per_day=confirmed_incidents,
            dispatch_workflow_executions_per_day=workflow_count,
            external_workforce_api_calls_per_day=workflow_count,
            depot_inventory_api_calls_per_day=workflow_count,
            notification_events_per_day=max(candidate_anomalies, workflow_count),
        ),
        assumptions=assumptions_list,
        unknowns=unknowns,
    )


def _flatten_industrial_model(model: IndustrialIoTPricingModel) -> PricingDrivers:
    return PricingDrivers(
        asset_count=model.telemetry.asset_count,
        telemetry_frequency_seconds=model.telemetry.telemetry_frequency_seconds,
        payload_kb=model.telemetry.payload_kb,
        daily_event_volume=model.telemetry.daily_raw_event_volume,
        monthly_event_volume=model.telemetry.monthly_raw_event_volume,
        stream_retention_hours=24,
        hot_retention_days=model.telemetry.hot_retention_days,
        cold_retention_months=model.telemetry.cold_retention_months,
        flink_kpu_hours=model.stream_processing.estimated_flink_kpus_expected * 720,
        feature_windows_per_day=model.stream_processing.feature_windows_per_day,
        inference_events_per_day=model.ml_scoring.scoring_events_per_day,
        sagemaker_endpoint_hours=720,
        candidate_anomalies_per_day=model.workflow.candidate_anomalies_per_day,
        confirmed_incidents_per_day=model.workflow.confirmed_incidents_per_day,
        workflow_executions_per_day=model.workflow.dispatch_workflow_executions_per_day,
        state_transitions_per_execution=8,
        integration_api_calls_per_day=model.workflow.external_workforce_api_calls_per_day + model.workflow.depot_inventory_api_calls_per_day,
        notification_events_per_day=model.workflow.notification_events_per_day,
        scoring_strategy=model.ml_scoring.scoring_strategy,
        source="industrial_iot_assumption_profile_plus_extracted_metrics",
        pricing_driver_family=PricingDriverFamily.INDUSTRIAL_IOT_STREAMING.value,
    )


def _catalog(drivers: PricingDrivers) -> dict[str, tuple[float, float, float, str, float]]:
    if drivers.source == "healthcare_or_extracted_operating_room_metrics":
        or_scale = max(0.5, drivers.active_or_count_poc / 8)
        prediction_scale = max(0.5, drivers.recommendation_runs_per_day / 1000)
        workflow_scale = max(0.5, drivers.approval_workflow_executions_per_day / 100)
        event_scale = max(0.5, drivers.occupancy_readiness_events_per_day / 10_000)
        user_scale = max(0.5, drivers.active_coordinator_users / 50)
        storage_scale = max(0.5, drivers.monthly_event_volume * drivers.payload_kb / 1024 / 1024 / 50)
        return {
            "eventbridge": (15, 60, 220, f"{drivers.occupancy_readiness_events_per_day:,} OR readiness/status events per day", event_scale),
            "kinesis": (50, 180, 650, f"{drivers.occupancy_readiness_events_per_day:,} OR readiness events/day with {drivers.stream_retention_hours}h stream retention", event_scale),
            "kinesis_stream_analytics": (120, 420, 1400, f"{drivers.flink_kpu_hours:,} estimated Flink KPU-hours/month for OR readiness windows", max(1.0, drivers.flink_kpu_hours / 720)),
            "sagemaker": (180, 850, 3000, f"{drivers.recommendation_runs_per_day:,} delay/reassignment recommendation runs/day", prediction_scale),
            "bedrock": (50, 220, 900, f"{drivers.recommendation_runs_per_day:,} governed recommendation explanations/day", prediction_scale),
            "dynamodb": (45, 180, 720, "PHI-safe OR operational state, idempotency keys, and current readiness state", max(event_scale, workflow_scale)),
            "step_functions": (30, 160, 650, f"{drivers.approval_workflow_executions_per_day:,} approval workflow executions/day", workflow_scale),
            "lambda": (25, 120, 480, f"{drivers.ehr_writeback_attempts_per_day:,} approved EHR writeback attempts/day plus policy checks", workflow_scale),
            "api_gateway": (10, 55, 200, f"{drivers.active_coordinator_users:,} active coordinator users and command-center API traffic", user_scale),
            "cognito": (0, 15, 60, f"{drivers.active_coordinator_users:,} active OR coordinator users", user_scale),
            "s3": (20, 100, 420, f"OR event history, model artifacts, audit evidence, and {drivers.cold_retention_months}mo retention", storage_scale),
            "cloudwatch": (60, 260, 950, "OR workflow logs, latency metrics, approval/audit alarms, and dashboards", max(event_scale, workflow_scale)),
            "cloudtrail": (20, 90, 360, "control-plane and selected writeback audit events for clinical scheduling operations", workflow_scale),
            "kms": (8, 40, 160, "keys and cryptographic requests for PHI-adjacent state, logs, and audit records", max(event_scale, workflow_scale)),
            "direct_connect": (500, 1800, 6000, "private EHR/hospital-system connectivity; carrier/cross-connect charges excluded", max(1.0, drivers.hospital_count / 4)),
            "external_actor": (0, 0, 0, "Epic/EHR, staffing, sterile processing, OR command center, and hospital systems are existing external actors and excluded from AWS estimate.", 1.0),
        }
    if drivers.source == "live_media_streaming_extracted_viewer_metrics":
        viewer_millions = max(0.1, drivers.asset_count / 1_000_000)
        egress_tb_month = drivers.market_data_ingest_gb_per_day * 30 / 1024
        ad_millions = max(0.1, drivers.integration_api_calls_per_day * 30 / 1_000_000)
        country_scale = max(1.0, drivers.candidate_anomalies_per_day / 10)
        return {
            "medialive": (2500, 9000, 45000, f"live encoding/channel hours for {drivers.asset_count:,} peak concurrent viewers and {drivers.telemetry_frequency_seconds}s latency target", country_scale),
            "mediapackage": (800, 3500, 18000, f"origin packaging and manifest requests for {drivers.asset_count:,} concurrent viewers", viewer_millions),
            "cloudfront": (egress_tb_month * 35, egress_tb_month * 85, egress_tb_month * 160, f"{egress_tb_month:,.0f} TB/month estimated CDN egress from viewer-hours and assumed bitrate", 1.0),
            "lambda_edge": (120, 900, 6500, f"edge geo-rights/entitlement checks across {drivers.candidate_anomalies_per_day:g} countries", max(viewer_millions, country_scale)),
            "mediatailor": (ad_millions * 20, ad_millions * 80, ad_millions * 240, f"{drivers.integration_api_calls_per_day:,} ad decision/insertion events per day when ad workflow is enabled", 1.0),
            "s3": (100, 700, 4500, "media archives, logs, clips, and event evidence retention", max(1.0, egress_tb_month / 100)),
            "cloudwatch": (500, 2500, 15000, "live channel health, CDN metrics, playback errors, policy decisions, and alarms", max(1.0, viewer_millions)),
            "kms": (50, 300, 1800, "keys and cryptographic requests for media artifacts, logs, and policy data", max(1.0, viewer_millions / 5)),
            "cloudtrail": (80, 500, 3000, "control-plane audit for live channel, CDN, rights policy, and ad workflow changes", country_scale),
            "external_actor": (0, 0, 0, "External contribution feed and third-party rights/ad systems are excluded from AWS estimate.", 1.0),
        }
    if drivers.source == "capital_markets_risk_extracted_metrics":
        hpc_low = drivers.hpc_compute_hours_per_month * 0.08
        hpc_expected = drivers.hpc_compute_hours_per_month * 0.22
        hpc_high = drivers.hpc_compute_hours_per_month * 0.85
        s3_low = drivers.audit_storage_gb_steady_state * 0.004
        s3_expected = drivers.audit_storage_gb_steady_state * 0.012
        s3_high = drivers.audit_storage_gb_steady_state * 0.026
        fsx_low = max(1000, drivers.result_storage_gb_per_month * 0.08)
        fsx_expected = max(3000, drivers.result_storage_gb_per_month * 0.16)
        fsx_high = max(9000, drivers.result_storage_gb_per_month * 0.36)
        market_stream_scale = max(1.0, drivers.market_data_ingest_gb_per_day * 30 / 1000)
        state_scale = max(1.0, drivers.positions_count / 1_000_000)
        cache_expected = max(2500, drivers.cache_node_hours_monthly * 0.18)
        query_expected = max(500, drivers.reporting_query_tb_scanned_monthly * 5)
        return {
            "msk": (900, 2400, 7200, f"{drivers.market_data_ingest_gb_per_day:g} GB/day assumed market-data ingest across {drivers.exchange_count} exchanges", market_stream_scale),
            "kinesis": (700, 1800, 5800, f"{drivers.market_data_ingest_gb_per_day:g} GB/day assumed market-data ingest across {drivers.exchange_count} exchanges", market_stream_scale),
            "dynamodb": (2500, 9000, 40000, f"{drivers.positions_count:,} positions with hot portfolio/risk state access per {drivers.risk_windows_per_day:,} risk windows/day", state_scale),
            "elasticache": (max(900, cache_expected * 0.45), cache_expected, cache_expected * 3.0, f"{drivers.risk_grid_nodes} assumed cache/risk-grid nodes and {drivers.cache_node_hours_monthly:,} node-hours/month", 1.0),
            "batch": (hpc_low, hpc_expected, hpc_high, f"{drivers.risk_compute_jobs_per_day:,} risk jobs/day and {drivers.hpc_compute_hours_per_month:,} assumed compute node-hours/month", 1.0),
            "fsx_lustre": (fsx_low, fsx_expected, fsx_high, f"{drivers.result_storage_gb_per_month:,.0f} GB/month risk result/scratch footprint with high-throughput simulation access", 1.0),
            "s3": (s3_low, s3_expected, s3_high, f"{drivers.result_storage_gb_per_month:,.0f} GB/month risk result output and {drivers.audit_storage_gb_steady_state:,.0f} GB steady-state audit retention", 1.0),
            "step_functions": (80, 420, 1800, f"{drivers.risk_compute_jobs_per_day:,} risk orchestration windows/day", max(1.0, drivers.risk_compute_jobs_per_day / 1000)),
            "eventbridge": (20, 120, 500, f"{drivers.confirmed_incidents_per_day:,} risk/compliance decision events/day", max(1.0, drivers.confirmed_incidents_per_day / 1000)),
            "lambda": (20, 160, 800, f"{drivers.integration_api_calls_per_day:,} pre-trade/compliance adapter calls/day", max(1.0, drivers.integration_api_calls_per_day / 1000)),
            "athena": (max(100, query_expected * 0.4), query_expected, query_expected * 4, f"{drivers.reporting_query_tb_scanned_monthly:g} TB/month assumed investigation and reporting scans", 1.0),
            "direct_connect": (500, 1800, 6000, "private market-data and enterprise connectivity circuit estimate; carrier/cross-connect charges excluded", max(1.0, drivers.exchange_count / 4)),
            "cloudwatch": (1200, 5000, 25000, "risk-grid logs, market-data ingestion health, audit alarms, and SLA dashboards", max(1.0, drivers.risk_grid_nodes / 16)),
            "kms": (150, 700, 4000, "encryption keys and cryptographic requests for risk data, audit stores, and logs", max(1.0, drivers.positions_count / 2_000_000)),
            "cloudtrail": (300, 1400, 9000, "control-plane and selected data-event audit trail for regulated risk platform", max(1.0, drivers.result_storage_gb_per_month / 10_000)),
            "external_actor": (0, 0, 0, "External market data/exchange/internal system costs are excluded from AWS estimate.", 1.0),
        }
    event_millions = max(0.1, drivers.monthly_event_volume / 1_000_000)
    daily_millions = max(0.1, drivers.daily_event_volume / 1_000_000)
    asset_scale = max(0.5, drivers.asset_count / 10000)
    stream_scale = max(0.5, event_millions / 100)
    flink_scale = max(1.0, drivers.flink_kpu_hours / 720)
    inference_scale = max(0.5, drivers.inference_events_per_day / 1_000_000)
    workflow_scale = max(0.5, drivers.workflow_executions_per_day / 1000)
    monthly_storage_gb = drivers.monthly_event_volume * drivers.payload_kb / 1024 / 1024
    retention_multiplier = max(1.0, drivers.cold_retention_months / 12)
    storage_scale = max(0.5, (monthly_storage_gb * retention_multiplier) / 100)
    return {
        "iot_core": (35, 110, 330, f"{drivers.asset_count:,} assets publishing every {drivers.telemetry_frequency_seconds}s at {drivers.payload_kb:g} KB", event_millions / 100),
        "kinesis": (60, 220, 700, f"{drivers.monthly_event_volume:,} monthly events and {drivers.stream_retention_hours}h stream retention", stream_scale),
        "kinesis_stream_analytics": (180, 650, 2100, f"{drivers.flink_kpu_hours:,} estimated Flink KPU-hours/month", flink_scale),
        "sagemaker": (250, 1100, 4200, f"{drivers.inference_events_per_day:,} scoring events/day ({drivers.scoring_strategy}) and {drivers.sagemaker_endpoint_hours} endpoint hours/month", inference_scale),
        "time_series_database": (90, 320, 1200, f"{drivers.daily_event_volume:,} writes/day, {drivers.hot_retention_days}d hot retention, {drivers.cold_retention_months}mo cold retention", daily_millions),
        "iot_sitewise": (80, 280, 1000, f"{drivers.asset_count:,} industrial assets and modeled telemetry properties", asset_scale),
        "dynamodb": (35, 160, 650, "alert/case state, dedupe state, feature cache, and low-latency reads/writes", max(0.6, daily_millions / 3)),
        "eventbridge": (12, 70, 260, f"{drivers.candidate_anomalies_per_day:,} candidate anomaly events/day", max(0.5, drivers.candidate_anomalies_per_day / 1000)),
        "sns": (5, 35, 120, f"{drivers.notification_events_per_day:,} operator notifications and fan-out deliveries/day", max(0.5, drivers.notification_events_per_day / 1000)),
        "sqs": (5, 35, 120, "buffered dispatch and depot integration messages", workflow_scale),
        "step_functions": (18, 120, 450, f"{drivers.workflow_executions_per_day:,} confirmed-incident executions/day, {drivers.state_transitions_per_execution} transitions/execution", workflow_scale),
        "lambda": (10, 80, 320, f"{drivers.integration_api_calls_per_day:,} confirmed-incident integration calls/day plus policy checks", workflow_scale),
        "s3": (15, 90, 380, f"raw/curated data, model artifacts, audit evidence, and {drivers.cold_retention_months}mo cold retention", storage_scale),
        "glue": (30, 140, 560, "catalog, ETL, and data quality job hours", storage_scale),
        "athena": (10, 75, 300, "historical query scan volume", storage_scale),
        "redshift": (250, 900, 3500, "optional warehouse capacity, snapshots, and concurrency", 1.0),
        "bedrock": (35, 160, 650, "model invocation tokens, guardrails, and evaluation volume", inference_scale),
        "opensearch_serverless": (90, 260, 780, "search/vector capacity, indexing, and storage", storage_scale),
        "opensearch": (90, 260, 780, "search/vector capacity, indexing, and storage", storage_scale),
        "api_gateway": (5, 35, 130, "API requests and data transfer", workflow_scale),
        "cloudwatch": (30, 140, 520, "logs, metrics, alarms, dashboards, and retention", max(stream_scale, workflow_scale)),
        "cognito": (0, 10, 35, "monthly active users", 1.0),
        "kms": (4, 18, 70, "keys and cryptographic requests", max(stream_scale, workflow_scale)),
        "waf": (8, 35, 130, "web ACLs, rules, bot controls, and inspected requests", 1.0),
        "shield": (0, 0, 3000, "standard protection or optional Advanced subscription", 1.0),
        "ecs": (45, 180, 700, "container runtime, load, and autoscaling floor", 1.0),
        "cloudtrail": (8, 40, 150, "management/data events and log delivery", max(stream_scale, workflow_scale)),
        "batch": (180, 650, 2500, "batch compute orchestration and worker runtime", max(1.0, drivers.flink_kpu_hours / 720)),
        "fsx_lustre": (250, 900, 3500, "high-throughput file storage and scratch throughput", 1.0),
        "elasticache": (80, 260, 900, "low-latency cache node hours and data transfer", 1.0),
        "msk": (150, 650, 2200, "streaming broker capacity, storage, and data transfer", stream_scale),
        "direct_connect": (500, 1800, 6000, "dedicated private connectivity; carrier/cross-connect charges excluded", 1.0),
        "external_actor": (0, 0, 0, "External system costs are excluded; only AWS integration adapter costs are estimated.", 1.0),
    }


def _line_assumptions(brief: UseCaseBrief, drivers: PricingDrivers) -> list[str]:
    if drivers.source == "healthcare_or_extracted_operating_room_metrics":
        return [
            f"Enterprise scope extracted: {drivers.hospital_count:,} hospital(s) and {drivers.operating_room_count:,} operating rooms.",
            f"POC pricing scope: {drivers.active_or_count_poc:,} active ORs, not the full enterprise fleet.",
            f"Prediction volume is active ORs x operating window x refresh cadence: {drivers.recommendation_runs_per_day:,} recommendation runs/day at {drivers.refresh_cadence_minutes}-minute cadence.",
            f"Occupancy/readiness event volume: {drivers.occupancy_readiness_events_per_day:,}/day; scheduled surgeries: {drivers.scheduled_surgeries_per_day:,}/day.",
            f"Approval workflows: {drivers.approval_workflow_executions_per_day:,}/day; approved EHR writeback attempts: {drivers.ehr_writeback_attempts_per_day:,}/day.",
            f"Audit retention modeled for {drivers.cold_retention_months} months.",
            *[assumption.text for assumption in brief.assumptions[:2]],
        ]
    if drivers.source == "document_rag_workflow_extracted_contract_metrics":
        return [
            f"Historical contract/document count: {drivers.asset_count:,}.",
            f"Assumed average document size: {drivers.payload_kb / 1024:g} MB until average pages or MB per document is confirmed.",
            f"Document ingestion/indexing cadence: {drivers.feature_windows_per_day:,} batch(es)/day from new or updated document volume.",
            f"RAG query volume: {drivers.inference_events_per_day:,}/day.",
            f"Obligation review/approval workflow volume: {drivers.workflow_executions_per_day:,}/day.",
            f"Audit retention modeled for {drivers.cold_retention_months} months.",
            *[assumption.text for assumption in brief.assumptions[:2]],
        ]
    if drivers.source == "capital_markets_risk_extracted_metrics":
        return [
            f"Confirmed open derivatives positions: {drivers.positions_count:,}.",
            f"Confirmed exchange/feed count: {drivers.exchange_count:,}.",
            f"Confirmed Greeks/risk refresh cadence: every {drivers.telemetry_frequency_seconds} seconds, modeled as {drivers.risk_windows_per_day:,} portfolio risk windows/day.",
            "Position refresh cadence is not treated as raw telemetry ingestion volume; market data, state refresh, compute jobs, and audit outputs are priced separately.",
            f"Directional compute assumption: {drivers.risk_grid_nodes:,} risk-grid nodes at {drivers.hpc_compute_hours_per_month:,} node-hours/month until measured Monte Carlo path count and runtime are provided.",
            f"Directional storage assumption: {drivers.result_storage_gb_per_month:,.0f} GB/month risk outputs and {drivers.audit_storage_gb_steady_state:,.0f} GB steady-state audit retention.",
            *[assumption.text for assumption in brief.assumptions[:2]],
        ]
    if drivers.source == "financial_fraud_extracted_transaction_metrics":
        return [
            f"Confirmed transaction volume: {drivers.daily_event_volume:,}/day and {drivers.monthly_event_volume:,}/month.",
            f"Scoring volume: {drivers.inference_events_per_day:,}/day using {drivers.scoring_strategy}.",
            f"Audit retention modeled for {drivers.cold_retention_months // 12:g} years; exact hot/cold tier split requires confirmation.",
            f"Analyst review/case queue assumed at {drivers.candidate_anomalies_per_day:,}/day until measured fraud and review rates are supplied.",
            f"Policy-approved block workflows assumed at {drivers.confirmed_incidents_per_day:,}/day until measured block rate is supplied.",
            *[assumption.text for assumption in brief.assumptions[:2]],
        ]
    if drivers.source == "live_media_streaming_extracted_viewer_metrics":
        return [
            f"Peak concurrent viewers: {drivers.asset_count:,}.",
            f"Glass-to-glass latency target: {drivers.telemetry_frequency_seconds} seconds.",
            f"Assumed average delivered bitrate: {drivers.payload_kb / 125:g} Mbps until the encoding ladder is confirmed.",
            "Assumed average viewer engagement: 3 viewer-hours per peak concurrent viewer per day until event traffic forecasts are confirmed.",
            f"Estimated CDN egress: {drivers.market_data_ingest_gb_per_day:,.0f} GB/day from viewer-hours and assumed bitrate.",
            f"Estimated edge policy requests: {drivers.asset_count * 30:,}/month.",
            f"Estimated ad decision requests: {drivers.integration_api_calls_per_day * 30:,}/month when targeted ads are enabled.",
            "Region traffic mix, CDN cache-hit ratio, DRM license requests, origin request count, and simultaneous live channel count require confirmation before procurement use.",
            *[assumption.text for assumption in brief.assumptions[:2]],
        ]
    if drivers.source == "advisory_discovery_directional_model":
        profile = profile_from_metadata(brief.use_case_profile, brief.raw_use_case)
        advisory_drivers = _advisory_pricing_driver_names(profile)
        readable = ", ".join(_humanize_driver_name(item) for item in advisory_drivers[:6]) or "workload-specific usage drivers"
        return [
            f"Directional pricing is anchored to discovery-planner workload drivers, not telemetry defaults: {readable}.",
            f"Assumed active users or primary actors: {drivers.asset_count:,}.",
            f"Assumed application/API/background workload: {drivers.daily_event_volume:,} combined requests/jobs per day.",
            f"Approval-gated workflow volume modeled at {drivers.workflow_executions_per_day:,}/day where external writes or governed actions are in scope.",
            f"Audit and retained evidence modeled for {drivers.cold_retention_months} months until exact retention policy is confirmed.",
            *[assumption.text for assumption in brief.assumptions[:2]],
        ]
    return [
        f"Total monitored assets: {drivers.asset_count:,}.",
        f"Assumed telemetry frequency: every {drivers.telemetry_frequency_seconds} seconds at {drivers.payload_kb:g} KB/message.",
        f"Derived event volume: {drivers.daily_event_volume:,}/day and {drivers.monthly_event_volume:,}/month.",
        f"Derived feature windows: {drivers.feature_windows_per_day:,}/day.",
        f"ML scoring volume: {drivers.inference_events_per_day:,}/day using {drivers.scoring_strategy}.",
        f"Candidate anomalies: {drivers.candidate_anomalies_per_day:,}/day; confirmed incidents/workflows: {drivers.confirmed_incidents_per_day:,}/day.",
        *[assumption.text for assumption in brief.assumptions[:2]],
    ]


def _known_cost_drivers(profile: UseCaseProfile, drivers: PricingDrivers) -> list[str]:
    if drivers.source == "document_rag_workflow_extracted_contract_metrics":
        return [
            f"historical_contract_or_document_count={drivers.asset_count}",
            f"assumed_average_document_mb={drivers.payload_kb / 1024:g}",
            f"assumed_new_or_updated_documents_per_month={drivers.monthly_event_volume - (drivers.inference_events_per_day * 30)}",
            f"assumed_rag_queries_per_day={drivers.inference_events_per_day}",
            f"assumed_embedding_indexing_batches_per_day={drivers.feature_windows_per_day}",
            f"assumed_obligation_review_approvals_per_day={drivers.workflow_executions_per_day}",
            f"assumed_audit_retention_months={drivers.cold_retention_months}",
            f"assumed_document_storage_gb={drivers.result_storage_gb_per_month:g}",
        ]
    if drivers.source == "healthcare_or_extracted_operating_room_metrics":
        return [
            f"hospital_count={drivers.hospital_count}",
            f"operating_room_count={drivers.operating_room_count}",
            f"active_or_count_poc={drivers.active_or_count_poc}",
            f"scheduled_surgeries_per_day={drivers.scheduled_surgeries_per_day}",
            f"refresh_cadence_minutes={drivers.refresh_cadence_minutes}",
            f"recommendation_runs_per_day={drivers.recommendation_runs_per_day}",
            f"approval_workflow_executions_per_day={drivers.approval_workflow_executions_per_day}",
            f"ehr_writeback_attempts_per_day={drivers.ehr_writeback_attempts_per_day}",
            f"occupancy_readiness_events_per_day={drivers.occupancy_readiness_events_per_day}",
            f"audit_retention_months={drivers.cold_retention_months}",
            f"active_coordinator_users={drivers.active_coordinator_users}",
        ]
    if drivers.source == "capital_markets_risk_extracted_metrics":
        return [
            f"open_positions={drivers.positions_count}",
            f"exchange_count={drivers.exchange_count}",
            f"greeks_frequency_seconds={drivers.telemetry_frequency_seconds}",
            f"risk_windows_per_day={drivers.risk_windows_per_day}",
            f"risk_compute_jobs_per_day={drivers.risk_compute_jobs_per_day}",
            f"assumed_risk_grid_nodes={drivers.risk_grid_nodes}",
            f"assumed_hpc_compute_hours_per_month={drivers.hpc_compute_hours_per_month}",
            f"assumed_market_data_ingest_gb_per_day={drivers.market_data_ingest_gb_per_day:g}",
            f"assumed_result_storage_gb_per_month={drivers.result_storage_gb_per_month:g}",
            f"assumed_reporting_query_tb_scanned_monthly={drivers.reporting_query_tb_scanned_monthly:g}",
        ]
    if drivers.source == "financial_fraud_extracted_transaction_metrics":
        known = [
            f"transactions_per_day={drivers.daily_event_volume}",
            f"monthly_transactions={drivers.monthly_event_volume}",
            f"scoring_events_per_day={drivers.inference_events_per_day}",
            f"feature_windows_per_day={drivers.feature_windows_per_day}",
            f"flink_kpu_hours={drivers.flink_kpu_hours}",
            f"sagemaker_endpoint_hours={drivers.sagemaker_endpoint_hours}",
            f"analyst_review_queue_events_per_day={drivers.candidate_anomalies_per_day}",
            f"policy_block_events_per_day={drivers.confirmed_incidents_per_day}",
            f"audit_retention_months={drivers.cold_retention_months}",
        ]
        latency = _structured_metric(profile, "business_targets", "latency_target_ms") or _metric_value(profile, "latency_target_ms")
        if latency:
            known.append(f"latency_target_ms={int(latency)}")
        false_positive = _structured_metric(profile, "business_targets", "false_positive_reduction_target_percent") or _metric_value(profile, "false_positive_reduction_target_percent")
        if false_positive:
            known.append(f"false_positive_reduction_target_percent={false_positive:g}")
        return known + [item for item in pricing_dimensions(profile) if item not in _known_dimension_names(profile)]
    if drivers.source == "live_media_streaming_extracted_viewer_metrics":
        return [
            f"concurrent_viewers={drivers.asset_count}",
            f"glass_to_glass_latency_seconds={drivers.telemetry_frequency_seconds}",
            f"assumed_bitrate_kb_per_second={drivers.payload_kb:g}",
            f"estimated_cdn_egress_gb_per_day={drivers.market_data_ingest_gb_per_day:g}",
            f"country_count={drivers.candidate_anomalies_per_day}",
            f"ad_decision_events_per_day={drivers.integration_api_calls_per_day}",
            f"reporting_query_tb_scanned_monthly={drivers.reporting_query_tb_scanned_monthly:g}",
        ]
    if drivers.source == "advisory_discovery_directional_model":
        return _advisory_driver_values(profile, drivers)
    known = [
        f"asset_count={drivers.asset_count}",
        f"telemetry_frequency_seconds={drivers.telemetry_frequency_seconds}",
        f"payload_kb={drivers.payload_kb:g}",
        f"daily_event_volume={drivers.daily_event_volume}",
        f"feature_windows_per_day={drivers.feature_windows_per_day}",
        f"flink_kpu_hours={drivers.flink_kpu_hours}",
        f"inference_events_per_day={drivers.inference_events_per_day}",
        f"candidate_anomalies_per_day={drivers.candidate_anomalies_per_day}",
        f"confirmed_incidents_per_day={drivers.confirmed_incidents_per_day}",
        f"workflow_executions_per_day={drivers.workflow_executions_per_day}",
    ]
    return known + [item for item in pricing_dimensions(profile) if item not in _known_dimension_names(profile)]


def _cost_optimization_recommendations(drivers: PricingDrivers) -> list[str]:
    if drivers.source == "document_rag_workflow_extracted_contract_metrics":
        return [
            "Confirm historical contract/document count, average pages or MB, and monthly new/updated document volume before procurement.",
            "Measure OCR/text extraction rate, embedding refresh cadence, and RAG query volume from the POC.",
            "Use lifecycle policies for contract source files, extracted text, embeddings, obligation records, audit logs, and evidence artifacts.",
            "Keep obligation updates and downstream metadata writes approval-gated until legal operating policy is confirmed.",
        ]
    if drivers.source == "advisory_discovery_directional_model":
        return [
            "Confirm the discovery-planner workload drivers with the customer before procurement; these estimates are directional and advisory only.",
            "Measure primary workload volume, active user concurrency, approval workflow frequency, and retention policy during the POC.",
            "Tune compute, queue, database, and observability capacity from measured workload usage during the POC.",
            "Keep external writes, approvals, and governed actions behind explicit policy and human approval until operating rules are confirmed.",
        ]
    return [
        "Confirm telemetry frequency and payload size before procurement.",
        "Tune stream retention, Flink KPU capacity, and inference cadence from measured POC traffic.",
        "Use lifecycle policies for telemetry, logs, evidence artifacts, and model outputs.",
        "Separate shadow-mode validation from production write automation until false-positive and approval rates are measured.",
    ]


def _unknown_variables(profile: UseCaseProfile) -> list[str]:
    known = _known_dimension_names(profile)
    unknown = [item for item in pricing_dimensions(profile) if item not in known]
    return list(dict.fromkeys(unknown + ["exact AWS region", "availability target", "measured false-positive rate"]))


def _pricing_validation(profile: UseCaseProfile, drivers: PricingDrivers) -> dict:
    structured = profile.structured_metrics or {}
    business = structured.get("business_targets") or {}
    assets = structured.get("asset_counts") or {}
    explicit_scale = {
        "cdrs_per_day": _structured_metric(profile, "business_targets", "cdrs_per_day"),
        "open_derivatives_positions": _structured_metric(profile, "asset_counts", "open_derivatives_positions"),
        "raw_sensor_samples_per_second": _structured_metric(profile, "business_targets", "raw_sensor_samples_per_second"),
        "transactions_per_day": _structured_metric(profile, "business_targets", "transactions_per_day"),
        "audit_retention_years": _structured_metric(profile, "business_targets", "audit_retention_years"),
        "latency_target_ms": _structured_metric(profile, "business_targets", "latency_target_ms"),
        "cell_towers": _structured_metric(profile, "asset_counts", "cell_towers"),
        "manufacturing_tools": _structured_metric(profile, "asset_counts", "manufacturing_tools"),
        "hospital_count": _structured_metric(profile, "asset_counts", "hospital_count"),
        "operating_room_count": _structured_metric(profile, "asset_counts", "operating_room_count"),
        "refresh_cadence_minutes": _structured_metric(profile, "business_targets", "refresh_cadence_minutes"),
    }
    provided = {key: value for key, value in explicit_scale.items() if value}
    scale_applied = True
    reasons = []
    if provided:
        if provided.get("cdrs_per_day") and drivers.daily_event_volume < int(provided["cdrs_per_day"]):
            scale_applied = False
            reasons.append("CDR/day scale from the prompt was not applied to daily_event_volume.")
        if provided.get("open_derivatives_positions") and drivers.asset_count < int(provided["open_derivatives_positions"]):
            scale_applied = False
            reasons.append("Open derivatives position count was not applied to asset_count.")
        if provided.get("raw_sensor_samples_per_second") and drivers.daily_event_volume < int(provided["raw_sensor_samples_per_second"] * 86400):
            scale_applied = False
            reasons.append("High-frequency raw sensor scale was not applied to daily_event_volume.")
        if provided.get("transactions_per_day") and drivers.daily_event_volume < int(provided["transactions_per_day"]):
            scale_applied = False
            reasons.append("Transactions/day scale from the prompt was not applied to daily_event_volume.")
        if provided.get("transactions_per_day") and drivers.inference_events_per_day < int(provided["transactions_per_day"]):
            scale_applied = False
            reasons.append("Transactions/day scale from the prompt was not applied to inference_events_per_day.")
        if provided.get("audit_retention_years") and drivers.cold_retention_months < int(provided["audit_retention_years"] * 12):
            scale_applied = False
            reasons.append("Audit retention years from the prompt were not applied to cold_retention_months.")
        if provided.get("operating_room_count") and drivers.operating_room_count < int(provided["operating_room_count"]):
            scale_applied = False
            reasons.append("Operating room count from the prompt was not applied to healthcare OR pricing drivers.")
        if provided.get("refresh_cadence_minutes") and drivers.refresh_cadence_minutes != int(provided["refresh_cadence_minutes"]):
            scale_applied = False
            reasons.append("Prediction refresh cadence from the prompt was not applied to recommendation_runs_per_day.")
    placeholder = drivers.asset_count == 1000 and bool(provided)
    if placeholder:
        scale_applied = False
        reasons.append("Pricing fell back to the 1,000-asset placeholder despite explicit scale metrics.")
    core_unknowns = _unknown_variables(profile)
    if drivers.source == "capital_markets_risk_extracted_metrics" and any(
        item in core_unknowns
        for item in ("risk_compute_jobs", "simulation_count", "hpc_compute_hours", "risk_grid_nodes", "shared_storage_throughput")
    ):
        status = "directional_only_missing_core_compute_drivers"
        reasons.append(
            "Capital-markets scale was extracted, but core compute/SKU variables such as simulation count, HPC node-hours, risk-grid size, and shared-storage throughput remain assumptions."
        )
    else:
        status = "directional_valid_with_extracted_scale" if scale_applied else "invalid_extracted_scale_not_applied"
    headline_safe = status not in {"invalid_extracted_scale_not_applied", "directional_only_missing_core_compute_drivers"}
    if drivers.source == "live_media_streaming_extracted_viewer_metrics":
        headline_safe = False
        reasons.append("Live-media pricing applies extracted viewer and latency scale, but bitrate, CDN cache hit ratio, regional egress mix, DRM license volume, and ad-decision profile remain core assumptions.")
    if drivers.source == "healthcare_or_extracted_operating_room_metrics":
        headline_safe = False
        reasons.append("Healthcare OR pricing uses POC-scoped directional assumptions until exact schedule volume, event payloads, SKU filters, and hospital integration traffic are validated.")
    reserved_findings = _reserved_healthcare_vocabulary_findings(profile, drivers)
    if reserved_findings:
        scale_applied = False
        status = "invalid_reserved_vocabulary_leakage"
        headline_safe = False
        reasons.extend(reserved_findings)
    return {
        "status": status,
        "scale_applied": scale_applied,
        "reason": "; ".join(reasons) if reasons else "Extracted workload scale was applied where available; still directional until AWS Pricing MCP/SKU filters are configured.",
        "extracted_scale_metrics": {key: value for key, value in provided.items()},
        "driver_source": drivers.source,
        "structured_metric_counts": {
            "asset_counts": len(assets),
            "business_targets": len(business),
        },
        "pricing_driver_family": drivers.pricing_driver_family,
        "pricing_can_be_displayed_as_headline": headline_safe,
        "reserved_vocabulary_findings": reserved_findings,
    }


def _known_dimension_names(profile: UseCaseProfile) -> set[str]:
    known = {"device_count", "region", "flink_kpu_hours", "inference_frequency", "workflow_execution_count", "state_transitions", "integration_api_calls"}
    if any(metric.kind == "asset_count" for metric in profile.metrics):
        known.add("asset_count")
    if _structured_metric(profile, "business_targets", "transactions_per_day") or _metric_value(profile, "transactions_per_day"):
        known.update({"transactions_per_day", "scoring_events_per_day"})
    if _structured_metric(profile, "business_targets", "latency_target_ms") or _metric_value(profile, "latency_target_ms"):
        known.update({"scoring_latency_target", "latency_target_ms"})
    if _structured_metric(profile, "business_targets", "audit_retention_years") or _metric_value(profile, "audit_retention_years"):
        known.update({"audit_retention", "data_retention"})
    if _structured_metric(profile, "business_targets", "false_positive_reduction_target_percent") or _metric_value(profile, "false_positive_reduction_target_percent"):
        known.add("false_positive_reduction_target")
    if profile.actions:
        known.update({"case_creation_rate", "block_rate"})
    if _structured_metric(profile, "asset_counts", "open_derivatives_positions"):
        known.add("open_positions")
    if _structured_metric(profile, "asset_counts", "exchanges"):
        known.add("exchange_count")
    if _structured_metric(profile, "business_targets", "greeks_frequency_seconds"):
        known.add("greeks_frequency_seconds")
    if _structured_metric(profile, "business_targets", "latency_target_seconds"):
        known.add("var_latency_target")
    if "healthcare_operations_scheduling" in profile.workload_families:
        known.update({
            "hospital_count",
            "operating_room_count",
            "active_or_count_poc",
            "scheduled_surgeries_per_day",
            "refresh_cadence_minutes",
            "recommendation_runs_per_day",
            "approval_workflow_executions_per_day",
            "ehr_writeback_attempts_per_day",
            "occupancy_readiness_events_per_day",
            "audit_retention_months",
            "active_coordinator_users",
            "or_schedule_events_per_day",
            "occupancy_metadata_events_per_day",
            "prediction_refresh_minutes",
            "approval_tasks_per_day",
            "audit_retention_years",
            "feature_snapshot_reads",
            "recommendations_per_day",
            "clinical_integration_api_calls",
            "phi_state_reads_writes",
            "metadata_payload_kb",
            "video_retention_boundary",
            "workflow_state_transitions",
            "approval_rate",
            "override_rate",
        })
    return known


def _profile_pricing_overrides(profile: UseCaseProfile) -> dict[str, Any]:
    payload = (profile.structured_metrics or {}).get("pricing_driver_overrides")
    return dict(payload) if isinstance(payload, dict) else {}


def _pricing_formula_trace(service: str, drivers: PricingDrivers, low: float, expected: float, high: float) -> dict:
    if drivers.source == "healthcare_or_extracted_operating_room_metrics":
        key = _catalog_key(service)
        formulas = {
            "sagemaker": f"{drivers.active_or_count_poc} active ORs * 12 operating hours/day * 60 / {drivers.refresh_cadence_minutes} minute refresh cadence",
            "bedrock": f"{drivers.recommendation_runs_per_day:,} recommendation runs/day with governed explanation volume",
            "eventbridge": f"{drivers.occupancy_readiness_events_per_day:,} OR readiness/status events/day",
            "kinesis": f"{drivers.occupancy_readiness_events_per_day:,} OR readiness/status events/day * 30 days",
            "step_functions": f"{drivers.approval_workflow_executions_per_day:,} approval workflows/day * 30 days",
            "lambda": f"{drivers.ehr_writeback_attempts_per_day:,} approved EHR writeback attempts/day plus policy checks",
            "dynamodb": f"{drivers.occupancy_readiness_events_per_day:,} OR state events/day plus idempotency and current status reads/writes",
        }
        return {
            "driver_formula": formulas.get(key, "Directional managed-service estimate from healthcare OR scheduling drivers."),
            "monthly_estimate_range": {"low": round(low, 2), "expected": round(expected, 2), "high": round(high, 2)},
            "confidence": "low",
            "why_large": "Cost is driven by active OR count, prediction refresh cadence, approval workflows, EHR writeback attempts, audit retention, and PHI-safe operational state.",
            "how_to_reduce": "Confirm POC OR count, operating hours, schedule/readiness event rate, payload size, approval rate, and EHR writeback volume before procurement.",
        }
    if drivers.source != "capital_markets_risk_extracted_metrics":
        return {}
    key = _catalog_key(service)
    formulas = {
        "batch": f"{drivers.risk_compute_jobs_per_day:,} risk jobs/day * 30 days * {drivers.risk_grid_nodes} nodes * 0.25 assumed node-hours/job-window",
        "fsx_lustre": f"{drivers.result_storage_gb_per_month:,.0f} GB/month risk scratch/result footprint * high-throughput scratch storage assumption",
        "s3": f"{drivers.result_storage_gb_per_month:,.0f} GB/month retained risk outputs * {drivers.cold_retention_months} months audit retention",
        "dynamodb": f"{drivers.positions_count:,} open positions refreshed across {drivers.risk_windows_per_day:,} risk windows/day for hot state access",
        "elasticache": f"{drivers.risk_grid_nodes} assumed cache/risk nodes * 720 hours/month",
        "msk": f"{drivers.exchange_count} exchanges * 50 GB/day assumed normalized market-data feed volume * 30 days",
        "kinesis": f"{drivers.exchange_count} exchanges * 50 GB/day assumed normalized market-data feed volume * 30 days",
        "athena": f"{drivers.reporting_query_tb_scanned_monthly:g} TB/month assumed regulatory and investigation query scans",
        "step_functions": f"{drivers.risk_compute_jobs_per_day:,} risk orchestration windows/day with exception and retry paths",
        "direct_connect": f"{drivers.exchange_count} exchange/feed integrations behind private connectivity boundary; carrier charges excluded",
    }
    confidence = "medium" if key in {"batch", "fsx_lustre", "s3", "dynamodb", "elasticache"} else "low"
    return {
        "driver_formula": formulas.get(key, "Directional managed-service estimate from workload-specific capital-markets drivers."),
        "monthly_estimate_range": {"low": round(low, 2), "expected": round(expected, 2), "high": round(high, 2)},
        "confidence": confidence,
        "why_large": "Cost is driven by risk compute windows, low-latency state, retained risk evidence, and regulated audit/reporting needs, not by generic raw event ingestion.",
        "how_to_reduce": "Confirm Monte Carlo path count, runtime, node type, cache size, compression/partitioning, retention tiering, and query scan controls during POC.",
    }


def _catalog_key(service: str) -> str:
    normalized = service.lower().replace("amazon ", "").replace("aws ", "").replace(" ", "_").replace("/", "_")
    if "bedrock" in normalized:
        return "bedrock"
    if "opensearch" in normalized or "knowledge" in normalized:
        return "opensearch_serverless"
    if "api_gateway" in normalized:
        return "api_gateway"
    if "iot_core" in normalized:
        return "iot_core"
    if "iot_sitewise" in normalized:
        return "iot_sitewise"
    if "kinesis_data_stream" in normalized:
        return "kinesis"
    if "msk" in normalized:
        return "msk"
    if "managed_service_for_apache_flink" in normalized or "kinesis_data_analytics" in normalized:
        return "kinesis_stream_analytics"
    if "batch" in normalized:
        return "batch"
    if "fsx" in normalized or "lustre" in normalized:
        return "fsx_lustre"
    if "elasticache" in normalized:
        return "elasticache"
    if "direct_connect" in normalized:
        return "direct_connect"
    if "medialive" in normalized:
        return "medialive"
    if "mediapackage" in normalized:
        return "mediapackage"
    if "mediatailor" in normalized:
        return "mediatailor"
    if "lambda_edge" in normalized or "lambda@edge" in normalized or "cloudfront_functions" in normalized or "cloudfront_function" in normalized:
        return "lambda_edge"
    if "cloudfront" in normalized:
        return "cloudfront"
    if "sagemaker" in normalized:
        return "sagemaker"
    if "timestream" in normalized or "time_series" in normalized:
        return "time_series_database"
    if "step_functions" in normalized:
        return "step_functions"
    if "eventbridge" in normalized:
        return "eventbridge"
    if "cloudwatch" in normalized:
        return "cloudwatch"
    if "cloudtrail" in normalized:
        return "cloudtrail"
    if "external_" in normalized or "workforce" in normalized or "depot" in normalized:
        return "external_actor"
    return normalized


def _reserved_healthcare_vocabulary_findings(profile: UseCaseProfile, drivers: PricingDrivers) -> list[str]:
    if drivers.source != "healthcare_or_extracted_operating_room_metrics":
        return []
    raw = _profile_source_text(profile).lower()
    allowed = {term for term in _HEALTHCARE_RESERVED_TERMS if term in raw}
    output_text = " ".join(_known_cost_drivers(profile, drivers) + [
        drivers.source,
        drivers.scoring_strategy,
        drivers.pricing_driver_family,
    ]).lower()
    findings = []
    for term in sorted(_HEALTHCARE_RESERVED_TERMS - allowed):
        if term in output_text:
            findings.append(f"Reserved non-healthcare vocabulary leaked into healthcare pricing output: {term}.")
    return findings


_HEALTHCARE_RESERVED_TERMS = {
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
}


def _profile_source_text(profile: UseCaseProfile) -> str:
    metric_text = " ".join(metric.raw for metric in profile.metrics)
    structured = profile.structured_metrics or {}
    source_text = []
    for section in ("asset_counts", "business_targets"):
        for payload in (structured.get(section) or {}).values():
            if isinstance(payload, dict) and payload.get("raw"):
                source_text.append(str(payload.get("raw")))
            if isinstance(payload, dict) and payload.get("source_text"):
                source_text.append(str(payload.get("source_text")))
    return " ".join([metric_text, *source_text])


def _advisory_pricing_driver_names(profile: UseCaseProfile) -> list[str]:
    plan = getattr(profile, "discovery_plan", {}) or {}
    drivers = plan.get("pricing_drivers") or []
    return [str(item) for item in drivers if item]


def _advisory_driver_values(profile: UseCaseProfile, drivers: PricingDrivers) -> list[str]:
    values = {
        "active_users": drivers.asset_count,
        "active_legal_users": drivers.asset_count,
        "active_coordinator_users": drivers.asset_count,
        "api_requests_per_day": drivers.daily_event_volume,
        "background_jobs_per_day": drivers.feature_windows_per_day,
        "workflow_execution_count": drivers.workflow_executions_per_day,
        "approval_workflow_executions_per_day": drivers.workflow_executions_per_day,
        "obligation_review_approvals_per_month": drivers.workflow_executions_per_day * 30,
        "rag_queries_per_day": drivers.inference_events_per_day,
        "database_storage_gb": round(drivers.result_storage_gb_per_month, 2),
        "documents_gb": round(drivers.result_storage_gb_per_month, 2),
        "audit_retention_duration": drivers.cold_retention_months,
        "audit_retention_months": drivers.cold_retention_months,
        "downstream_metadata_update_frequency": drivers.integration_api_calls_per_day,
    }
    items: list[str] = []
    for name in _advisory_pricing_driver_names(profile):
        if name in values:
            items.append(f"{name}={values[name]}")
        else:
            items.append(f"{name}=directional_assumption_required")
    return items or [
        f"active_users={drivers.asset_count}",
        f"daily_workload_units={drivers.daily_event_volume}",
        f"audit_retention_months={drivers.cold_retention_months}",
    ]


def _humanize_driver_name(name: str) -> str:
    return name.replace("_", " ")


def _asset_count(profile: UseCaseProfile) -> int:
    total = sum(int(metric.value) for metric in profile.metrics if metric.kind == "asset_count")
    return total


def _metric_max(profile: UseCaseProfile, tokens: tuple[str, ...]) -> float:
    values = [metric.value for metric in profile.metrics if any(token in metric.label.lower() for token in tokens)]
    return max(values) if values else 0.0


def _metric_value(profile: UseCaseProfile, label: str) -> float:
    for metric in profile.metrics:
        if metric.label == label:
            return metric.value
    return 0.0


def _structured_metric(profile: UseCaseProfile, section: str, key: str) -> float:
    value = ((profile.structured_metrics or {}).get(section) or {}).get(key) or {}
    try:
        return float(value.get("value") or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_streaming_ml_profile(profile: UseCaseProfile) -> bool:
    capabilities = set(profile.capabilities) | set(profile.capability_model)
    return bool({"device_telemetry", "stream_ingestion", "stream_processing", "ml_inference", "real_time_anomaly_detection"} & capabilities) and (
        "industrial_iot_streaming_ml" in profile.workload_families or "time_series_storage" in capabilities
    )


def _is_financial_fraud_profile(profile: UseCaseProfile) -> bool:
    families = set(profile.workload_families)
    return "financial_fraud_detection" in families
