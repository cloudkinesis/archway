from app.services.metric_extractor import extract_metrics
from tests.golden_scenarios.scenarios import GOLDEN_SCENARIOS, UTILITY_GRID


def test_utility_metric_extractor_preserves_business_meaning():
    metrics = extract_metrics(UTILITY_GRID)

    assert metrics.asset_counts["smart_meters"].value == 200000
    assert metrics.asset_counts["distribution_transformers"].value == 15000
    assert metrics.asset_counts["total_monitored_assets"].value == 215000
    assert metrics.asset_counts["total_monitored_assets"].derived is True
    assert metrics.business_targets["unplanned_outage_reduction_percent"].value == 45
    assert metrics.business_targets["current_mttr_hours"].value == 4
    assert metrics.business_targets["target_mttr_minutes"].value == 90
    assert metrics.business_targets["target_timeline_months"].value == 18
    assert {"voltage_fluctuations", "load_imbalances", "ambient_temperature"} <= set(metrics.telemetry_signals)
    assert {"transformer_thermal_runaway", "feeder_prefault_oscillation"} <= set(metrics.detection_targets)
    assert {"dispatch_field_crews", "preposition_replacement_equipment"} <= set(metrics.operational_actions)


def test_semiconductor_metric_extractor_preserves_high_frequency_scale():
    metrics = extract_metrics(GOLDEN_SCENARIOS["semiconductor_twin"])

    assert metrics.asset_counts["fabs"].value == 3
    assert metrics.asset_counts["manufacturing_tools"].value == 2800
    assert metrics.asset_counts["total_monitored_assets"].value == 2800
    assert metrics.business_targets["sensor_channels_per_tool"].value == 500
    assert metrics.business_targets["streaming_sample_rate_khz"].value == 1
    assert metrics.business_targets["raw_sensor_samples_per_second"].value == 1_400_000_000
    assert metrics.business_targets["prediction_horizon_hours"].value == 72
    assert metrics.business_targets["false_positive_target_percent"].value == 0.1
    assert metrics.business_targets["false_alarm_cost_usd"].value == 2_000_000
    assert metrics.business_targets["catastrophic_alert_latency_seconds"].value == 5
    assert {"sensor_channels", "high_frequency_sampling"} <= set(metrics.telemetry_signals)
    assert {"tool_failure_prediction", "catastrophic_failure_alerting"} <= set(metrics.detection_targets)


def test_telecom_metric_extractor_preserves_cdr_scale():
    metrics = extract_metrics(GOLDEN_SCENARIOS["telecom_congestion"])

    assert metrics.business_targets["cdrs_per_day"].value == 8_000_000_000
    assert metrics.asset_counts["cell_towers"].value == 120_000
    assert metrics.business_targets["prediction_horizon_minutes"].value == 15
    assert metrics.business_targets["retention_years"].value == 2
    assert "call_detail_records" in metrics.telemetry_signals
    assert "network_congestion_prediction" in metrics.detection_targets


def test_investment_metric_extractor_preserves_risk_engine_scale():
    metrics = extract_metrics(GOLDEN_SCENARIOS["investment_risk"])

    assert metrics.asset_counts["open_derivatives_positions"].value == 2_400_000
    assert metrics.asset_counts["exchanges"].value == 14
    assert metrics.business_targets["greeks_frequency_seconds"].value == 30
    assert metrics.business_targets["sub_second_var_latency"].value == 1
    assert "market_data_or_positions" in metrics.telemetry_signals
    assert "portfolio_risk_var" in metrics.detection_targets


def test_payment_fraud_metric_extractor_preserves_transaction_scale():
    use_case = (
        "A regional bank wants an AWS platform to detect real-time payment fraud across 12 million card transactions per day, "
        "score events in under 250 milliseconds, queue suspicious payments for analyst review, block high-confidence fraudulent "
        "transactions after policy approval, retain audit evidence for seven years, and reduce false positives by 30 percent in the first year."
    )

    metrics = extract_metrics(use_case)

    assert metrics.business_targets["transactions_per_day"].value == 12_000_000
    assert metrics.business_targets["average_tps"].value == 138.89
    assert metrics.business_targets["latency_target_ms"].value == 250
    assert metrics.business_targets["audit_retention_years"].value == 7
    assert metrics.business_targets["false_positive_reduction_target_percent"].value == 30
    assert "payment_authorization_events" in metrics.telemetry_signals
    assert "payment_fraud_scoring" in metrics.detection_targets
    assert "queue_suspicious_payments_for_analyst_review" in metrics.operational_actions
    assert "block_high_confidence_fraud_after_policy_approval" in metrics.operational_actions
