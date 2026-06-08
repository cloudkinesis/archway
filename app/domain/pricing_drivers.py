from typing import Literal

from pydantic import BaseModel


class TelemetryPricingDrivers(BaseModel):
    asset_count: int
    smart_meter_count: int | None = None
    transformer_count: int | None = None
    telemetry_frequency_seconds: int
    payload_kb: float
    daily_raw_event_volume: int
    monthly_raw_event_volume: int
    hot_retention_days: int
    cold_retention_months: int


class StreamProcessingPricingDrivers(BaseModel):
    raw_events_per_day: int
    aggregation_window_seconds: int
    feature_windows_per_day: int
    estimated_flink_kpus_low: int
    estimated_flink_kpus_expected: int
    estimated_flink_kpus_high: int


class MLScoringPricingDrivers(BaseModel):
    raw_events_per_day: int
    scoring_strategy: Literal["score_every_event", "score_aggregated_windows", "score_candidate_anomalies_only"]
    scoring_events_per_day: int
    candidate_anomaly_rate_percent: float
    confirmed_incident_rate_percent: float


class WorkflowPricingDrivers(BaseModel):
    candidate_anomalies_per_day: int
    confirmed_incidents_per_day: int
    dispatch_workflow_executions_per_day: int
    external_workforce_api_calls_per_day: int
    depot_inventory_api_calls_per_day: int
    notification_events_per_day: int


class IndustrialIoTPricingModel(BaseModel):
    telemetry: TelemetryPricingDrivers
    stream_processing: StreamProcessingPricingDrivers
    ml_scoring: MLScoringPricingDrivers
    workflow: WorkflowPricingDrivers
    assumptions: list[str]
    unknowns: list[str]

