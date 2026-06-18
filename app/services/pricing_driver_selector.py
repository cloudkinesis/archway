import re
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
    excluded = set(profile.excluded_families or []) | set(profile.excluded_patterns or [])
    if {"healthcare_operations_scheduling", "surgical_scheduling_prediction", "clinical_workflow_decision_support"} & families:
        return PricingDriverFamily.HEALTHCARE_OPERATIONS_SCHEDULING
    if "financial_fraud_detection" in families:
        return PricingDriverFamily.PAYMENT_FRAUD_SCORING
    if {"telecom_network_analytics", "cdr_congestion_prediction"} & families:
        return PricingDriverFamily.TELECOM_CDR_ANALYTICS
    if {"capital_markets_risk_engine", "monte_carlo_risk_grid", "pre_trade_compliance"} & families:
        return PricingDriverFamily.CAPITAL_MARKETS_RISK_ENGINE
    if "live_streaming" in families or (
        "video_streaming" in capabilities and _has_live_media_distribution_intent(profile)
    ):
        return PricingDriverFamily.LIVE_MEDIA_STREAMING
    if "hpc_simulation" in families or "hpc_simulation" in capabilities:
        return PricingDriverFamily.HPC_SIMULATION
    if "federated_ml" in families or "federated_learning" in capabilities:
        return PricingDriverFamily.FEDERATED_ML
    if "graph_analytics" in families:
        return PricingDriverFamily.GRAPH_ANALYTICS
    if not ({"document_intelligence", "rag_assistant"} & excluded) and (
        {"document_intelligence", "rag_assistant"} & families
        or {"document_retrieval", "rag_retrieval", "document_ingestion"} & capabilities
    ):
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


def _profile_text(profile: UseCaseProfile) -> str:
    fields: list[object] = [
        getattr(profile, "business_goal", None),
        profile.domain,
        profile.workload_families,
        profile.capabilities,
        profile.capability_model,
        getattr(profile, "data_classes", None),
        profile.signals,
        profile.entities,
        profile.actions,
        profile.business_targets,
        profile.metrics,
    ]
    return " ".join(str(field).lower() for field in fields if field)


def _has_live_media_distribution_intent(profile: UseCaseProfile) -> bool:
    text = _profile_text(profile)
    media_delivery_terms = (
        "live stream",
        "live streams",
        "live streaming",
        "video streaming",
        "streaming video",
        "ott",
        "content delivery",
        "cdn",
        "drm",
        "watch time",
        "playback",
        "stream delivery",
        "media delivery",
        "glass-to-glass",
        "glass to glass",
        "bitrate",
    )
    normalized = text.replace("-", " ")
    return any(
        _contains_marker(text, term) and not _is_marker_negated(normalized, term)
        for term in media_delivery_terms
    )


def _contains_marker(lower: str, marker: str) -> bool:
    if len(marker) <= 4 and marker.replace(" ", "").isalnum():
        return re.search(rf"\b{re.escape(marker)}\b", lower) is not None
    return marker in lower


def _is_marker_negated(normalized_lower: str, marker: str) -> bool:
    marker_pattern = re.escape(marker.replace("-", " ")).replace(r"\ ", r"\s+")
    prefix = r"(?:not|no|without|exclude|excluding|avoid|avoiding|not\s+a|not\s+an|not\s+the)"
    return re.search(rf"\b{prefix}\b(?:\W+\w+){{0,6}}\W+{marker_pattern}\b", normalized_lower) is not None
