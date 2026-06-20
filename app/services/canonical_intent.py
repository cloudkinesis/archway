from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


STREAMING_FAMILIES = {
    "industrial_iot_streaming_ml",
    "real_time_anomaly_detection",
    "telecom_network_analytics",
    "cdr_congestion_prediction",
    "financial_fraud_detection",
    "capital_markets_risk_engine",
    "low_latency_trading",
}

STREAMING_CAPABILITIES = {
    "device_telemetry",
    "high_volume_event_ingestion",
    "stream_ingestion",
    "stream_processing",
    "time_series_analytics",
    "time_series_storage",
    "cdr_ingestion",
    "market_data_ingestion",
    "pos_data_ingestion",
    "weather_data_ingestion",
}

STREAM_SOURCE_TERMS = (
    "telemetry",
    "sensor",
    "sensors",
    "iot",
    "gps",
    "market data",
    "cdr",
    "call detail record",
    "pos transaction",
    "card transaction",
    "payment transaction",
    "courier update",
    "device update",
    "vehicle update",
    "meter reading",
    "camera feed",
    "video stream",
    "live feed",
)

STREAM_TRANSPORT_TERMS = (
    "kinesis",
    "flink",
    "msk",
    "data stream",
    "event stream",
    "stream processing",
    "streaming analytics",
    "pub/sub",
    "mqtt",
)

GEOSPATIAL_TERMS = (
    "gps",
    "geospatial",
    "geofence",
    "geofencing",
    "map",
    "maps",
    "mapping",
    "route optimization",
    "vehicle routing",
    "delivery routing",
    "field routing",
    "courier",
    "driver",
    "vehicle",
    "fleet",
    "shipment location",
    "track location",
    "location tracking",
)

DOCUMENT_TERMS = (
    "document",
    "documents",
    "pdf",
    "pdfs",
    "form",
    "forms",
    "page",
    "pages",
    "ocr",
    "textract",
    "contract",
    "contracts",
    "medical form",
    "packet",
    "packets",
)

LATENCY_TERMS = (
    "latency",
    "response",
    "respond",
    "status",
    "sla",
    "slo",
    "under",
    "within",
    "target",
    "turnaround",
    "generate",
    "summary",
)

ASSET_UNITS_BLOCKLIST = {
    "page",
    "pages",
    "document",
    "documents",
    "pdf",
    "pdfs",
    "form",
    "forms",
    "packet",
    "packets",
    "reviewer",
    "reviewers",
    "user",
    "users",
    "person",
    "people",
    "customer",
    "customers",
    "patient",
    "patients",
    "rider",
    "riders",
    "caregiver",
    "caregivers",
}


@dataclass(frozen=True)
class CanonicalIntent:
    streaming_evidence: bool
    document_evidence: bool
    approval_evidence: bool
    notification_evidence: bool
    external_integration_evidence: bool
    audit_evidence: bool
    geospatial_evidence: bool
    reasons: tuple[str, ...]


def canonical_intent_for_profile(profile: Any, raw_text: str = "") -> CanonicalIntent:
    text = _combined_text(profile, raw_text)
    capabilities = set(getattr(profile, "capabilities", []) or []) | set(getattr(profile, "capability_model", []) or [])
    families = set(getattr(profile, "workload_families", []) or [])
    signals = " ".join(str(item) for item in getattr(profile, "signals", []) or []).lower()
    reasons: list[str] = []

    stream_by_family = bool(families & STREAMING_FAMILIES)
    stream_by_capability = bool(capabilities & STREAMING_CAPABILITIES)
    stream_by_transport = any(_contains_term(text, term) for term in STREAM_TRANSPORT_TERMS)
    stream_by_source = any(_contains_term(text, term) for term in STREAM_SOURCE_TERMS)
    stream_by_frequency = _has_source_frequency(text) or _has_source_frequency(signals)
    streaming = bool(stream_by_transport or (stream_by_source and (stream_by_frequency or stream_by_capability or stream_by_family)))
    if stream_by_transport:
        reasons.append("stream_transport_term")
    if stream_by_source and stream_by_frequency:
        reasons.append("source_frequency")
    if stream_by_source and stream_by_capability:
        reasons.append("source_capability")
    if stream_by_source and stream_by_family:
        reasons.append("source_family")

    document = any(_contains_term(text, term) for term in DOCUMENT_TERMS) or bool({"document_retrieval", "document_ingestion", "rag_retrieval"} & capabilities)
    approval = any(_contains_term(text, term) for term in ("approval", "approve", "human review", "reviewer", "reviewers", "deny", "denial", "human approval"))
    notification = any(term in text for term in ("notify", "notification", "sms", "email", "alert"))
    integration = bool({"external_system_integration", "external_workflow_integration"} & capabilities) or any(term in text for term in ("crm", "scheduling system", "existing system", "integration", "external system"))
    audit = bool({"audit_trail", "full_audit_trail", "audit_store"} & capabilities) or any(term in text for term in ("audit", "appeal", "evidence", "traceability", "retention"))
    geospatial = any(_contains_term(text, term) for term in GEOSPATIAL_TERMS)
    return CanonicalIntent(
        streaming_evidence=streaming,
        document_evidence=document,
        approval_evidence=approval,
        notification_evidence=notification,
        external_integration_evidence=integration,
        audit_evidence=audit,
        geospatial_evidence=geospatial,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def is_latency_seconds(name: str, unit: str, source: str) -> bool:
    text = f"{name} {unit} {source}".lower()
    return "second" in text and any(term in text for term in LATENCY_TERMS)


def is_document_size_or_count(name: str, unit: str, source: str) -> bool:
    text = f"{name} {unit} {source}".lower()
    tokens = set(re.findall(r"[a-z]+", f"{name} {unit}".lower()))
    return bool(tokens & ASSET_UNITS_BLOCKLIST) or any(_contains_term(text, term) for term in DOCUMENT_TERMS)


def _combined_text(profile: Any, raw_text: str = "") -> str:
    parts: list[str] = [raw_text or ""]
    for attr in (
        "domain",
        "workload_families",
        "capabilities",
        "capability_model",
        "entities",
        "signals",
        "actions",
        "business_targets",
    ):
        value = getattr(profile, attr, None)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif value:
            parts.append(str(value))
    return " ".join(parts).replace("_", " ").lower()


def _has_source_frequency(text: str) -> bool:
    if not text:
        return False
    frequency = bool(
        re.search(r"\bevery\s+\d+(?:\.\d+)?\s*(?:ms|milliseconds?|seconds?|minutes?|hours?)\b", text)
        or re.search(r"\b\d+(?:\.\d+)?\s*(?:events?|updates?|messages?|readings?|transactions?)\s+per\s+(?:second|minute|hour|day)\b", text)
        or re.search(r"\bper\s+(?:second|minute|hour)\b", text)
    )
    return frequency and any(_contains_term(text, term) for term in STREAM_SOURCE_TERMS + STREAM_TRANSPORT_TERMS)


def _contains_term(text: str, term: str) -> bool:
    normalized = term.lower().replace("_", " ").strip()
    if not normalized:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", text) is not None
