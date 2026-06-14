from enum import Enum

from app.services.use_case_profile import UseCaseProfile


class PricingDriverFamily(str, Enum):
    HEALTHCARE_OPERATIONS_SCHEDULING = "healthcare_operations_scheduling"
    INDUSTRIAL_IOT_STREAMING = "industrial_iot_streaming"
    TELECOM_CDR_ANALYTICS = "telecom_cdr_analytics"
    PAYMENT_FRAUD_SCORING = "payment_fraud_scoring"
    CAPITAL_MARKETS_RISK_ENGINE = "capital_markets_risk_engine"
    HPC_SIMULATION = "hpc_simulation"
    LIVE_MEDIA_STREAMING = "live_media_streaming"
    FEDERATED_ML = "federated_ml"
    BIOMETRIC_IDENTITY = "biometric_identity"
    GRAPH_ANALYTICS = "graph_analytics"
    DOCUMENT_RAG_WORKFLOW = "document_rag_workflow"
    OTA_FLEET_ORCHESTRATION = "ota_fleet_orchestration"
    SUPPLY_CHAIN_OPTIMIZATION = "supply_chain_optimization"
    GENERIC_DIRECTIONAL = "generic_directional"


def select_pricing_driver_family(profile: UseCaseProfile) -> PricingDriverFamily:
    families = set(profile.workload_families)
    capabilities = set(profile.capabilities) | set(profile.capability_model)
    if {"healthcare_operations_scheduling", "surgical_scheduling_prediction", "clinical_workflow_decision_support"} & families:
        return PricingDriverFamily.HEALTHCARE_OPERATIONS_SCHEDULING
    if "financial_fraud_detection" in families:
        return PricingDriverFamily.PAYMENT_FRAUD_SCORING
    if {"telecom_network_analytics", "cdr_congestion_prediction"} & families:
        return PricingDriverFamily.TELECOM_CDR_ANALYTICS
    if {"capital_markets_risk_engine", "monte_carlo_risk_grid", "pre_trade_compliance"} & families:
        return PricingDriverFamily.CAPITAL_MARKETS_RISK_ENGINE
    if "live_streaming" in families or "video_streaming" in capabilities:
        return PricingDriverFamily.LIVE_MEDIA_STREAMING
    if "hpc_simulation" in families or "hpc_simulation" in capabilities:
        return PricingDriverFamily.HPC_SIMULATION
    if "federated_ml" in families or "federated_learning" in capabilities:
        return PricingDriverFamily.FEDERATED_ML
    if "graph_analytics" in families:
        return PricingDriverFamily.GRAPH_ANALYTICS
    if {"document_intelligence", "rag_assistant"} & families or {"document_retrieval", "rag_retrieval", "document_ingestion"} & capabilities:
        return PricingDriverFamily.DOCUMENT_RAG_WORKFLOW
    if "ota_rollout_orchestration" in capabilities:
        return PricingDriverFamily.OTA_FLEET_ORCHESTRATION
    if "inventory_optimization" in capabilities:
        return PricingDriverFamily.SUPPLY_CHAIN_OPTIMIZATION
    if "operational_event_prediction_workflow" in families:
        return PricingDriverFamily.GENERIC_DIRECTIONAL
    if {"industrial_iot_streaming_ml", "real_time_anomaly_detection"} & families:
        return PricingDriverFamily.INDUSTRIAL_IOT_STREAMING
    return PricingDriverFamily.GENERIC_DIRECTIONAL
