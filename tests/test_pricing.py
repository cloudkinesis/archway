import pytest

from app.models.domain import AWSServiceSelection
from app.services.pricing import PricingEngine
from app.services.pricing_driver_selector import PricingDriverFamily, select_pricing_driver_family
from app.services.synthesis import SynthesisEngine
from app.services.use_case_profile import profile_use_case
from tests.golden_scenarios.scenarios import GOLDEN_SCENARIOS


@pytest.mark.asyncio
async def test_pricing_is_deterministic_and_cited():
    brief = SynthesisEngine().create_initial_brief("Retail order assistant for delivery questions.")
    services = [
        AWSServiceSelection(service="Amazon Bedrock", purpose="model", rationale="managed"),
        AWSServiceSelection(service="Amazon S3", purpose="documents", rationale="durable"),
    ]

    estimate = await PricingEngine().estimate(brief, services)

    assert estimate.low_monthly_usd < estimate.expected_monthly_usd < estimate.high_monthly_usd
    assert estimate.evidence_items
    assert all(item.evidence_ids for item in estimate.line_items)


@pytest.mark.asyncio
async def test_telecom_pricing_applies_cdr_volume():
    brief = SynthesisEngine().create_initial_brief(GOLDEN_SCENARIOS["telecom_congestion"])

    estimate = await PricingEngine().estimate(brief, [AWSServiceSelection(service="Amazon Kinesis Data Streams", purpose="stream", rationale="managed")])

    assert estimate.metadata["status"] == "directional_valid_with_extracted_scale"
    assert estimate.metadata["scale_applied"] is True
    assert "cdrs_per_day" in estimate.metadata["extracted_scale_metrics"]
    assert "8,000,000,000 monthly events" not in estimate.line_items[0].unit_basis
    assert "240,000,000,000 monthly events" in estimate.line_items[0].unit_basis


@pytest.mark.asyncio
async def test_investment_pricing_applies_position_and_greeks_frequency():
    brief = SynthesisEngine().create_initial_brief(GOLDEN_SCENARIOS["investment_risk"])

    estimate = await PricingEngine().estimate(brief, [AWSServiceSelection(service="AWS Batch", purpose="risk", rationale="managed")])

    assert estimate.metadata["status"] == "directional_only_missing_core_compute_drivers"
    assert estimate.metadata["scale_applied"] is True
    assert estimate.metadata["extracted_scale_metrics"]["open_derivatives_positions"] == 2_400_000
    assert "risk jobs/day" in estimate.line_items[0].unit_basis
    assert "risk jobs/day" in estimate.line_items[0].pricing_trace["driver_formula"]
    assert "6,912,000,000 scoring events/day" not in estimate.line_items[0].unit_basis
    assert "risk_compute_jobs" in estimate.unknown_variables


@pytest.mark.asyncio
async def test_payment_fraud_pricing_applies_transactions_latency_and_audit_retention():
    use_case = (
        "A regional bank wants an AWS platform to detect real-time payment fraud across 12 million card transactions per day, "
        "score events in under 250 milliseconds, queue suspicious payments for analyst review, block high-confidence fraudulent "
        "transactions after policy approval, retain audit evidence for seven years, and reduce false positives by 30 percent in the first year."
    )
    brief = SynthesisEngine().create_initial_brief(use_case)

    estimate = await PricingEngine().estimate(
        brief,
        [
            AWSServiceSelection(service="Amazon Kinesis Data Streams", purpose="stream", rationale="managed"),
            AWSServiceSelection(service="Amazon SageMaker", purpose="ml", rationale="managed"),
            AWSServiceSelection(service="Amazon S3", purpose="audit", rationale="durable"),
        ],
    )

    assert estimate.metadata["status"] == "directional_valid_with_extracted_scale"
    assert estimate.metadata["scale_applied"] is True
    assert estimate.metadata["driver_source"] == "financial_fraud_extracted_transaction_metrics"
    assert estimate.metadata["extracted_scale_metrics"]["transactions_per_day"] == 12_000_000
    assert estimate.metadata["extracted_scale_metrics"]["audit_retention_years"] == 7
    assert "360,000,000 monthly events" in estimate.line_items[0].unit_basis
    assert "12,000,000 scoring events/day" in estimate.line_items[1].unit_basis
    assert "84mo cold retention" in estimate.line_items[2].unit_basis
    assert "transactions_per_day" not in estimate.unknown_variables
    assert "audit_retention" not in estimate.unknown_variables


@pytest.mark.asyncio
async def test_energy_iot_anomaly_detection_does_not_drift_to_payment_fraud_pricing():
    use_case = (
        "An energy utility IoT telemetry platform ingests device reporting from smart meters and transformer sensors, "
        "runs anomaly detection on voltage and temperature signals, and alerts grid operators."
    )
    profile = profile_use_case(use_case)
    brief = SynthesisEngine().create_initial_brief(use_case)

    estimate = await PricingEngine().estimate(
        brief,
        [
            AWSServiceSelection(service="AWS IoT Core", purpose="device telemetry ingestion", rationale="managed IoT ingress"),
            AWSServiceSelection(service="Amazon Kinesis Data Streams", purpose="telemetry stream", rationale="managed stream"),
            AWSServiceSelection(service="Amazon SageMaker", purpose="anomaly detection", rationale="managed ML"),
        ],
    )

    assert profile.domain == "energy_utility"
    assert "industrial_iot_streaming_ml" in profile.workload_families
    assert "financial_fraud_detection" not in profile.workload_families
    assert select_pricing_driver_family(profile) == PricingDriverFamily.INDUSTRIAL_IOT_STREAMING
    assert estimate.metadata["pricing_driver_family"] == PricingDriverFamily.INDUSTRIAL_IOT_STREAMING.value
    assert estimate.metadata["driver_source"] == "industrial_iot_assumption_profile_plus_extracted_metrics"
    assert "payment_fraud_scoring" not in str(estimate.metadata)
    assert any("asset_count=" in item for item in estimate.main_cost_drivers)
    assert any("telemetry_frequency_seconds=" in item for item in estimate.main_cost_drivers)


@pytest.mark.asyncio
async def test_payment_transaction_fraud_still_selects_payment_fraud_pricing():
    use_case = (
        "A bank needs payment transaction fraud detection across card transactions, suspicious payment review, "
        "chargeback investigation, and policy-approved blocking."
    )
    profile = profile_use_case(use_case)
    brief = SynthesisEngine().create_initial_brief(use_case)

    estimate = await PricingEngine().estimate(
        brief,
        [
            AWSServiceSelection(service="Amazon Kinesis Data Streams", purpose="payment stream", rationale="managed stream"),
            AWSServiceSelection(service="Amazon SageMaker", purpose="fraud scoring", rationale="managed ML"),
        ],
    )

    assert "financial_fraud_detection" in profile.workload_families
    assert select_pricing_driver_family(profile) == PricingDriverFamily.PAYMENT_FRAUD_SCORING
    assert estimate.metadata["pricing_driver_family"] == PricingDriverFamily.PAYMENT_FRAUD_SCORING.value
    assert estimate.metadata["driver_source"] == "financial_fraud_extracted_transaction_metrics"


@pytest.mark.asyncio
async def test_generic_web_pricing_uses_discovery_drivers_not_telemetry_fallback():
    brief = SynthesisEngine().create_initial_brief(
        "We need a public web application with API, database, async jobs, observability, and CI/CD."
    )

    estimate = await PricingEngine().estimate(
        brief,
        [
            AWSServiceSelection(service="Amazon API Gateway", purpose="public api", rationale="managed"),
            AWSServiceSelection(service="AWS Lambda", purpose="async jobs", rationale="managed"),
            AWSServiceSelection(service="Amazon DynamoDB", purpose="application state", rationale="managed"),
        ],
    )

    assumptions_text = " ".join(
        assumption
        for item in estimate.line_items
        for assumption in item.assumptions
    ).lower()
    driver_text = " ".join(estimate.main_cost_drivers).lower()
    recommendation_text = " ".join(estimate.cost_optimization_recommendations).lower()

    assert estimate.metadata["driver_source"] == "advisory_discovery_directional_model"
    assert "active_users=" in driver_text
    assert "api_requests_per_day=" in driver_text
    assert "telemetry_frequency_seconds" not in driver_text
    assert "payload_kb" not in driver_text
    assert "telemetry defaults" in assumptions_text
    assert "telemetry frequency" not in assumptions_text
    assert "payload size" not in assumptions_text
    assert "generic telemetry assumptions" not in recommendation_text
