from app.services.pattern_catalog import expected_views, pricing_dimensions, service_recommendations
from app.services.use_case_profile import profile_use_case
from tests.golden_scenarios.scenarios import GOLDEN_SCENARIOS, UTILITY_GRID


def test_golden_scenario_matrix_produces_distinct_workload_plans():
    plans = []
    for name, use_case in {"utility_grid": UTILITY_GRID, **GOLDEN_SCENARIOS}.items():
        profile = profile_use_case(use_case)
        services = service_recommendations(profile, evidence_ids=["ev_test"])
        dimensions = pricing_dimensions(profile)
        views = expected_views(profile, production=True)
        plans.append((name, tuple(profile.workload_families), tuple(profile.capability_model), tuple(item.service for item in services)))

        assert profile.workload_families, name
        assert profile.capability_model, name
        assert services, name
        assert dimensions, name
        assert "production_logical_service_flow" in views

    unique_capability_sets = {item[2] for item in plans}
    unique_service_sets = {item[3] for item in plans}

    assert len(unique_capability_sets) >= 10
    assert len(unique_service_sets) >= 8


def test_golden_scenarios_do_not_default_to_rag_without_rag_signals():
    for name, use_case in {"utility_grid": UTILITY_GRID, **GOLDEN_SCENARIOS}.items():
        profile = profile_use_case(use_case)
        text = use_case.lower()
        has_rag_signal = any(term in text for term in ("rag", "knowledge base", "document", "manual", "citation"))

        if not has_rag_signal:
            assert "rag_assistant" not in profile.workload_families, name
            assert "rag_retrieval" not in profile.capability_model, name


def test_extreme_or_restricted_scenarios_preserve_operational_constraints():
    national_identity = profile_use_case(GOLDEN_SCENARIOS["national_identity"])
    market_making = profile_use_case(GOLDEN_SCENARIOS["market_making"])

    assert {"air_gapped_on_prem", "customer_dc_with_aws_services", "sovereign_cloud"} <= set(national_identity.deployment_posture)
    assert "private_connectivity" in national_identity.capability_model
    assert "security_governance" in national_identity.capability_model

    assert market_making.latency_class == "microsecond"
    assert "external_system_integration" in market_making.capability_model
    assert "full_audit_trail" in market_making.capability_model


def test_semiconductor_twin_is_not_polluted_by_healthcare_or_media_capabilities():
    profile = profile_use_case(GOLDEN_SCENARIOS["semiconductor_twin"])

    assert profile.domain == "semiconductor_manufacturing"
    assert profile.latency_class == "seconds"
    assert profile.latency_target == "sub-5-second"
    assert "industrial_iot_streaming_ml" in profile.workload_families
    assert "digital_twin" in profile.capability_model
    assert "signal_processing" in profile.capability_model
    assert "phi_data" not in profile.capability_model
    assert "hipaa_compliance" not in profile.capability_model
    assert "financial_market_compliance" not in profile.capability_model
    assert "video_streaming" not in profile.capability_model


def test_telecom_and_investment_profiles_use_specific_workload_families():
    telecom = profile_use_case(GOLDEN_SCENARIOS["telecom_congestion"])
    investment = profile_use_case(GOLDEN_SCENARIOS["investment_risk"])

    assert telecom.domain == "telecommunications"
    assert telecom.workload_families[:2] == ["telecom_network_analytics", "cdr_congestion_prediction"]
    assert "cdr_ingestion" in telecom.capability_model
    assert "telecom_regulatory_compliance" in telecom.capability_model

    assert investment.domain == "investment_banking"
    assert "capital_markets_risk_engine" in investment.workload_families[:3]
    assert "monte_carlo_risk_grid" in investment.workload_families[:3]
    assert "monte_carlo_simulation" in investment.capability_model
    assert "financial_market_compliance" in investment.capability_model


def test_telecom_classification_guards_avoid_weak_signal_false_positives():
    open_source_observability = profile_use_case(
        "A software company runs an open-source software observability platform for Kubernetes app telemetry, logs, metrics, events, and alerting."
    )
    kubernetes_telemetry = profile_use_case(
        "A SaaS company monitors Kubernetes application telemetry, service events, real-time alerts, and deployment health for web APIs."
    )
    factory_iot = profile_use_case(
        "A factory ingests machine telemetry, vibration readings, production-line events, and alerts to predict equipment downtime."
    )

    assert open_source_observability.domain != "telecommunications"
    assert "telecom_network_analytics" not in open_source_observability.workload_families
    assert kubernetes_telemetry.domain != "telecommunications"
    assert "telecom_network_analytics" not in kubernetes_telemetry.workload_families
    assert factory_iot.domain == "manufacturing"
    assert "industrial_iot_streaming_ml" in factory_iot.workload_families
    assert "telecom_network_analytics" not in factory_iot.workload_families


def test_telecom_pack_recognizes_strong_network_and_hbase_migration_signals():
    gnmi_network = profile_use_case(
        "A telecom operator collects network element counters through gNMI from 5G cell sites, predicts congestion, and feeds OSS/BSS assurance workflows."
    )
    hbase_migration = profile_use_case(
        "A telecom operator migrates HBase, HDFS, and Spark CDR analytics with OSS/BSS integration, TRAI QoS reporting, and parallel-run cutover validation."
    )

    assert gnmi_network.domain == "telecommunications"
    assert "telecom_network_analytics" in gnmi_network.workload_families
    assert hbase_migration.domain == "telecommunications"
    assert "telecom_network_analytics" in hbase_migration.workload_families


def test_payment_fraud_profile_uses_fraud_pattern_not_iot_or_rag():
    use_case = (
        "A regional bank wants an AWS platform to detect real-time payment fraud across 12 million card transactions per day, "
        "score events in under 250 milliseconds, queue suspicious payments for analyst review, block high-confidence fraudulent "
        "transactions after policy approval, retain audit evidence for seven years, and reduce false positives by 30 percent in the first year."
    )

    profile = profile_use_case(use_case)
    services = service_recommendations(profile, evidence_ids=["ev_test"])
    service_names = {item.service for item in services}

    assert profile.domain == "financial_services"
    assert profile.workload_families[0] == "financial_fraud_detection"
    assert "rag_assistant" not in profile.workload_families
    assert "industrial_iot_streaming_ml" not in profile.workload_families
    assert "AWS IoT Core" not in service_names
    assert "AWS IoT SiteWise / time-series storage decision" not in service_names
    assert {"Amazon Kinesis Data Streams", "Amazon SageMaker", "Amazon DynamoDB", "Amazon SQS", "AWS Step Functions", "Amazon S3"} <= service_names
