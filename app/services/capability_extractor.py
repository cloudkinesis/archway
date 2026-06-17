import re

from app.domain.capabilities import ArchitectureCapability, CapabilityExtractionResult, DeploymentPosture, LatencyClass


NEGATED_PATTERN_CONSTRAINTS: dict[str, dict[str, tuple[str, ...]]] = {
    "document_rag": {
        "markers": (
            "rag",
            "document rag",
            "document retrieval",
            "document assistant",
            "document intelligence",
            "document qa",
            "document search",
            "knowledge base",
            "contract review",
            "ocr",
            "embedding",
            "vector search",
        ),
        "families": ("rag_assistant", "document_intelligence"),
        "patterns": ("rag_assistant", "document_qa_chatbot", "document_intelligence", "contract_review", "ocr_document_pipeline"),
        "capabilities": ("rag_retrieval", "document_ingestion", "document_retrieval"),
    },
    "field_service": {
        "markers": ("field service", "field-service", "field crew", "workforce dispatch", "dispatch"),
        "families": ("field_service_automation",),
        "patterns": ("field_service_automation", "generic_field_service_dispatch"),
        "capabilities": ("external_workflow_integration",),
    },
    "depot_inventory": {
        "markers": ("depot", "depot inventory", "inventory management", "inventory"),
        "families": ("supply_chain_optimization",),
        "patterns": ("depot_inventory", "inventory_or_depot_integration", "supply_chain_optimization"),
        "capabilities": ("inventory_or_depot_integration", "inventory_optimization"),
    },
}


CAPABILITY_MARKERS: list[tuple[ArchitectureCapability, tuple[str, ...]]] = [
    (ArchitectureCapability.DEVICE_TELEMETRY, ("smart meter", "sensor", "telemetry", "iot", "cell tower", "base station", "vehicle", "drone")),
    (ArchitectureCapability.HIGH_VOLUME_EVENT_INGESTION, ("billion", "million", "high-volume", "concurrent", "transactions/day", "cdr")),
    (ArchitectureCapability.STREAM_INGESTION, ("real-time", "realtime", "stream", "telemetry", "cdr", "market data", "pos transactions", "card transactions", "payment transactions")),
    (ArchitectureCapability.STREAM_PROCESSING, ("stream processing", "streaming", "window", "real-time", "kinesis", "flink")),
    (ArchitectureCapability.REAL_TIME_ANALYTICS, ("real-time analytics", "sub-second", "milliseconds", "seconds", "15-minute", "sla monitoring")),
    (ArchitectureCapability.REAL_TIME_ANOMALY_DETECTION, ("failure detection", "thermal runaway", "pre-fault", "oscillation", "anomaly", "false positive")),
    (ArchitectureCapability.ANOMALY_DETECTION, ("anomaly", "fraud", "failure detection", "risk score", "ground stop")),
    (ArchitectureCapability.TIME_SERIES_ANALYTICS, ("time-series", "voltage", "temperature", "load imbalance", "trend", "sensor channels")),
    (ArchitectureCapability.TIME_SERIES_STORAGE, ("time-series", "telemetry", "sensor data", "historical failure")),
    (ArchitectureCapability.DATA_LAKE, ("data lake", "historical", "raw telemetry", "curated", "retention", "faers")),
    (ArchitectureCapability.FEATURE_ENGINEERING, ("feature", "correlating", "window", "greeks", "signal processing")),
    (ArchitectureCapability.ML_TRAINING, ("training", "model calibration", "known clinical interactions", "historical failure patterns")),
    (ArchitectureCapability.ML_INFERENCE, ("inference", "prediction", "predictive", "scoring", "match/no-match", "risk")),
    (ArchitectureCapability.MODEL_MONITORING, ("model monitoring", "drift", "false positive", "rollback")),
    (ArchitectureCapability.MODEL_REGISTRY, ("model registry", "model artifact", "rollback")),
    (ArchitectureCapability.EVENT_DRIVEN_ORCHESTRATION, ("dispatch", "workflow", "orchestration", "submission", "rollout", "ground stop")),
    (ArchitectureCapability.HUMAN_APPROVAL, ("approval", "human", "field crew", "high-impact")),
    (ArchitectureCapability.EXTERNAL_WORKFLOW_INTEGRATION, ("workforce management", "field crew", "case management", "sap", "rfc", "bapi")),
    (ArchitectureCapability.INVENTORY_OR_DEPOT_INTEGRATION, ("depot", "inventory", "replacement equipment")),
    (ArchitectureCapability.EXTERNAL_SYSTEM_INTEGRATION, ("existing", "integration", "erp", "sap", "3gpp", "exchange", "faa", "epic", "cerner", "meditech")),
    (ArchitectureCapability.ALERTING_NOTIFICATION, ("alert", "notify", "notification")),
    (ArchitectureCapability.OPERATIONAL_STATE, ("state", "dedupe", "case", "portfolio", "operational", "analyst review")),
    (ArchitectureCapability.OBSERVABILITY, ("observability", "monitoring", "sla", "dashboard", "cloudwatch")),
    (ArchitectureCapability.AUDIT_TRAIL, ("audit", "cloudtrail", "traceability")),
    (ArchitectureCapability.FULL_AUDIT_TRAIL, ("audit trail", "tick-level audit", "part 11", "regulatory", "sec", "mifid", "mas", "trai", "faa")),
    (ArchitectureCapability.SECURITY_GOVERNANCE, ("kms", "iam", "governance", "encryption", "security", "kill switch", "policy")),
    (ArchitectureCapability.PRIVATE_CONNECTIVITY, ("vpn", "direct connect", "private", "no public cloud egress", "air-gapped", "co-located", "enterprise")),
    (ArchitectureCapability.RAG_RETRIEVAL, ("rag", "retrieve", "knowledge base", "source documents", "citations")),
    (ArchitectureCapability.DOCUMENT_INGESTION, ("document ingestion", "ocr", "textract", "documents", "contract", "contracts", "clause extraction", "legal contract")),
    (ArchitectureCapability.AGENT_TOOL_EXECUTION, ("agent", "tool execution", "tool call")),
    (ArchitectureCapability.CDR_INGESTION, ("cdr", "call detail record")),
    (ArchitectureCapability.MARKET_DATA_INGESTION, ("market data", "exchange", "instruments", "bid", "order flow")),
    (ArchitectureCapability.BIOMETRIC_REQUEST_PROCESSING, ("verification requests", "biometric", "citizens")),
    (ArchitectureCapability.VIDEO_STREAMING, ("4k", "hdr", "live streams", "video streaming", "concurrent viewers")),
    (ArchitectureCapability.POS_DATA_INGESTION, ("pos transactions", "retail endpoints")),
    (ArchitectureCapability.WEATHER_DATA_INGESTION, ("weather", "storm", "wind/solar")),
    (ArchitectureCapability.BATCH_PROCESSING, ("nightly", "batch", "within 4 hours", "8-hour", "rerun")),
    (ArchitectureCapability.HPC_SIMULATION, ("monte carlo", "simulation", "hpc", "storm tracks")),
    (ArchitectureCapability.MONTE_CARLO_SIMULATION, ("monte carlo", "var")),
    (ArchitectureCapability.GRAPH_ANALYTICS, ("graph", "nodes", "edges")),
    (ArchitectureCapability.GRAPH_ML_INFERENCE, ("graph model", "graph networks")),
    (ArchitectureCapability.GNN_INFERENCE, ("gnn", "graph neural")),
    (ArchitectureCapability.SIGNAL_PROCESSING, ("1 khz", "sensor channels", "signal", "oscillation")),
    (ArchitectureCapability.FEDERATED_LEARNING, ("federated", "aggregated gradients", "no centralized phi")),
    (ArchitectureCapability.DIGITAL_TWIN, ("digital twin",)),
    (ArchitectureCapability.BIOMETRIC_MATCHING, ("biometric", "match/no-match")),
    (ArchitectureCapability.MOLECULAR_GRAPH_MODELING, ("molecular graph", "compound pairs")),
    (ArchitectureCapability.PERSONALIZATION, ("personalization", "personalized")),
    (ArchitectureCapability.EDGE_PROCESSING, ("edge", "hospital-local", "vehicle", "offline", "factory", "ot/it", "intermittent connectivity", "remote connectivity", "unreliable connectivity", "store-and-forward", "edge buffering")),
    (ArchitectureCapability.AIR_GAPPED_DEPLOYMENT, ("air-gapped", "no public cloud egress")),
    (ArchitectureCapability.SOVEREIGN_DEPLOYMENT, ("sovereign", "data sovereignty", "data residency")),
    (ArchitectureCapability.HYBRID_CLOUD, ("hybrid", "on-prem", "hospital", "co-location", "edge")),
    (ArchitectureCapability.EXCHANGE_COLOCATION, ("co-located", "exchange data centers", "colocation")),
    (ArchitectureCapability.FPGA_ACCELERATION, ("fpga",)),
    (ArchitectureCapability.VEHICLE_EDGE_RUNTIME, ("vehicle", "ota", "offline")),
    (ArchitectureCapability.POLICY_AUTOMATION, ("policy", "traffic shaping", "pre-trade", "slice lifecycle")),
    (ArchitectureCapability.OTA_ROLLOUT_ORCHESTRATION, ("ota", "rollout")),
    (ArchitectureCapability.CANARY_DEPLOYMENT, ("1% → 10%", "canary", "rollout")),
    (ArchitectureCapability.AUTOMATED_ROLLBACK, ("rollback",)),
    (ArchitectureCapability.KILL_SWITCH, ("kill switch", "ground stop")),
    (ArchitectureCapability.REGULATORY_REPORT_GENERATION, ("regulatory report", "sar", "reporting", "submission")),
    (ArchitectureCapability.GRAPH_STORE, ("graph edges", "entity nodes", "graph store")),
    (ArchitectureCapability.LOW_LATENCY_CACHE, ("cache", "sub-second", "microsecond", "concurrent")),
    (ArchitectureCapability.AUDIT_STORE, ("audit store", "audit trail")),
    (ArchitectureCapability.FEATURE_STORE, ("feature store", "curated feature", "feature lookup", "feature enrichment")),
    (ArchitectureCapability.OBJECT_STORAGE, ("object storage", "s3", "policies", "compounds")),
    (ArchitectureCapability.PII_DATA, ("pii", "citizens", "patient", "gdpr")),
    (ArchitectureCapability.PHI_DATA, ("phi", "hipaa", "ehr", "hospital", "protected health information")),
    (ArchitectureCapability.PCI_OR_FINANCIAL_DATA, ("pci", "financial", "transactions", "banking")),
    (ArchitectureCapability.BIOMETRIC_DATA, ("biometric", "citizens")),
    (ArchitectureCapability.DATA_RESIDENCY, ("data residency", "sovereignty", "sovereign")),
    (ArchitectureCapability.GDPR_COMPLIANCE, ("gdpr",)),
    (ArchitectureCapability.HIPAA_COMPLIANCE, ("hipaa",)),
    (ArchitectureCapability.GXP_VALIDATION, ("gxp", "21 cfr part 11")),
    (ArchitectureCapability.FUNCTIONAL_SAFETY, ("iso 26262", "asil", "functional safety", "faa")),
    (ArchitectureCapability.FINANCIAL_MARKET_COMPLIANCE, ("mifid", "sec", "mas", "finra", "solvency")),
    (ArchitectureCapability.TELECOM_REGULATORY_COMPLIANCE, ("trai", "3gpp")),
    (ArchitectureCapability.LOW_LATENCY_MEDIA_DELIVERY, ("glass-to-glass", "cdn", "live streaming")),
    (ArchitectureCapability.DRM_ENFORCEMENT, ("widevine", "drm")),
    (ArchitectureCapability.GEO_RIGHTS_ENFORCEMENT, ("geo-rights", "blackout")),
    (ArchitectureCapability.TARGETED_AD_DECISIONING, ("ad decision", "ad-consent")),
    (ArchitectureCapability.INVENTORY_OPTIMIZATION, ("inventory optimization", "sku-location", "service level")),
    (ArchitectureCapability.ROUTE_OPTIMIZATION, ("route optimization", "deconfliction", "separation")),
    (ArchitectureCapability.BID_OPTIMIZATION, ("bid optimization", "bidding cycle")),
    (ArchitectureCapability.RISK_OPTIMIZATION, ("risk optimization", "var", "greeks", "margin")),
    (ArchitectureCapability.PRE_TRADE_POLICY_BLOCKING, ("pre-trade",)),
    (ArchitectureCapability.HIGH_AVAILABILITY, ("99.999", "high availability", "zero downtime")),
    (ArchitectureCapability.LOW_LATENCY_CONTROL, ("urllc", "1ms", "1 ms")),
    (ArchitectureCapability.SLA_MONITORING, ("sla", "qos")),
    (ArchitectureCapability.MICROSECOND_LATENCY, ("microsecond", "microseconds", "nanosecond")),
]


def extract_capabilities(text: str) -> CapabilityExtractionResult:
    lower = text.lower()
    capabilities: list[ArchitectureCapability] = []
    for capability, markers in CAPABILITY_MARKERS:
        if any(_contains_marker(lower, marker) for marker in markers):
            capabilities.append(capability)
    if ArchitectureCapability.DEVICE_TELEMETRY in capabilities and ArchitectureCapability.STREAM_INGESTION not in capabilities:
        capabilities.append(ArchitectureCapability.STREAM_INGESTION)
    if ArchitectureCapability.ML_INFERENCE in capabilities and ArchitectureCapability.ML_TRAINING not in capabilities and "historical" in lower:
        capabilities.append(ArchitectureCapability.ML_TRAINING)
    if ArchitectureCapability.SECURITY_GOVERNANCE not in capabilities:
        capabilities.append(ArchitectureCapability.SECURITY_GOVERNANCE)
    if ArchitectureCapability.OBSERVABILITY not in capabilities:
        capabilities.append(ArchitectureCapability.OBSERVABILITY)
    if ArchitectureCapability.AUDIT_TRAIL not in capabilities:
        capabilities.append(ArchitectureCapability.AUDIT_TRAIL)
    capabilities = _remove_explicitly_negated_capabilities(list(dict.fromkeys(capabilities)), lower)
    excluded = _excluded_patterns(lower, capabilities)
    posture = infer_deployment_posture(lower, capabilities)
    latency = infer_latency_class(lower)
    return CapabilityExtractionResult(
        capabilities=capabilities,
        confidence="high" if len(capabilities) >= 5 else "medium",
        extracted_facts={"deployment_posture": [item.value for item in posture], "latency_class": latency.value if latency else None},
        excluded_patterns=excluded,
        reasoning_summary="Capabilities were selected from workload verbs, data types, latency/deployment constraints, compliance terms, and operational actions.",
        deployment_posture=posture,
        latency_class=latency,
    )


def infer_deployment_posture(lower: str, capabilities: list[ArchitectureCapability]) -> list[DeploymentPosture]:
    posture: list[DeploymentPosture] = []
    if any(term in lower for term in ("air-gapped", "no public cloud egress")):
        posture.extend([DeploymentPosture.AIR_GAPPED_ON_PREM, DeploymentPosture.CUSTOMER_DC_WITH_AWS_SERVICES])
    if any(term in lower for term in ("sovereign", "data sovereignty", "data residency")):
        posture.append(DeploymentPosture.SOVEREIGN_CLOUD)
    if any(term in lower for term in ("microsecond", "co-located", "exchange data centers")) or ArchitectureCapability.EXCHANGE_COLOCATION in capabilities:
        posture.extend([DeploymentPosture.EXCHANGE_COLOCATED, DeploymentPosture.HYBRID])
    if any(term in lower for term in ("edge", "offline", "hospital", "vehicle", "factory", "urllc", "1ms", "1 ms", "intermittent connectivity", "remote connectivity", "unreliable connectivity", "store-and-forward", "edge buffering")):
        posture.extend([DeploymentPosture.EDGE_AND_CLOUD, DeploymentPosture.HYBRID])
    operational_integration = {
        ArchitectureCapability.EXTERNAL_SYSTEM_INTEGRATION,
        ArchitectureCapability.EXTERNAL_WORKFLOW_INTEGRATION,
        ArchitectureCapability.INVENTORY_OR_DEPOT_INTEGRATION,
        ArchitectureCapability.PRIVATE_CONNECTIVITY,
    }
    critical_infrastructure_terms = ("utility", "grid", "smart meter", "transformer", "feeder", "substation", "field crew")
    if (
        ArchitectureCapability.DEVICE_TELEMETRY in capabilities
        and (operational_integration & set(capabilities) or any(term in lower for term in critical_infrastructure_terms))
    ):
        posture.extend([DeploymentPosture.EDGE_AND_CLOUD, DeploymentPosture.HYBRID])
    if not posture:
        posture.append(DeploymentPosture.PUBLIC_CLOUD)
    return list(dict.fromkeys(posture))


def infer_latency_class(lower: str) -> LatencyClass | None:
    if re.search(r"\d+\s*microsecond", lower) or "nanosecond" in lower:
        return LatencyClass.MICROSECOND
    ms_match = re.search(r"\b(?P<value>\d+)\s*(?:ms|milliseconds?)\b", lower)
    if ms_match:
        return LatencyClass.SINGLE_DIGIT_MILLISECOND if int(ms_match.group("value")) <= 10 else LatencyClass.SUB_SECOND
    if "urllc" in lower:
        return LatencyClass.SINGLE_DIGIT_MILLISECOND
    if "sub-second" in lower:
        return LatencyClass.SUB_SECOND
    if re.search(r"\b\d+\s*seconds?\b", lower) or re.search(r"sub[- ]\d+(?:\.\d+)?[- ]seconds?", lower):
        return LatencyClass.SECONDS
    if re.search(r"\b\d+\s*minutes?\b", lower) or "15-minute" in lower:
        return LatencyClass.MINUTES
    if re.search(r"\b\d+\s*hours?\b", lower):
        return LatencyClass.HOURS
    if "nightly" in lower or "batch" in lower:
        return LatencyClass.BATCH_WINDOW
    return None


def _contains_marker(lower: str, marker: str) -> bool:
    if len(marker) <= 4 and marker.replace(" ", "").isalnum():
        return re.search(rf"\b{re.escape(marker)}\b", lower) is not None
    return marker in lower


def _excluded_patterns(lower: str, capabilities: list[ArchitectureCapability]) -> list[str]:
    excluded = []
    if ArchitectureCapability.RAG_RETRIEVAL not in capabilities and ArchitectureCapability.DOCUMENT_INGESTION not in capabilities:
        excluded.extend(["rag_assistant", "document_qa_chatbot", "generic_ai_assistant"])
    if "chatbot" not in lower and "assistant" not in lower:
        excluded.append("generic_chatbot")
    negated = explicit_negative_constraints(lower)
    excluded.extend(negated["families"])
    excluded.extend(negated["patterns"])
    return list(dict.fromkeys(excluded))


def explicit_negative_constraints(lower: str) -> dict[str, list[str]]:
    normalized = lower.replace("-", " ")
    families: list[str] = []
    patterns: list[str] = []
    capabilities: list[str] = []
    labels: list[str] = []
    for label, rule in NEGATED_PATTERN_CONSTRAINTS.items():
        if not any(_is_marker_negated(normalized, marker) for marker in rule["markers"]):
            continue
        labels.append(label)
        families.extend(rule["families"])
        patterns.extend(rule["patterns"])
        capabilities.extend(rule["capabilities"])
    return {
        "labels": list(dict.fromkeys(labels)),
        "families": list(dict.fromkeys(families)),
        "patterns": list(dict.fromkeys(patterns)),
        "capabilities": list(dict.fromkeys(capabilities)),
    }


def _remove_explicitly_negated_capabilities(capabilities: list[ArchitectureCapability], lower: str) -> list[ArchitectureCapability]:
    blocked = set(explicit_negative_constraints(lower)["capabilities"])
    if not blocked:
        return capabilities
    return [capability for capability in capabilities if capability.value not in blocked]


def _is_marker_negated(normalized_lower: str, marker: str) -> bool:
    marker = marker.replace("-", " ")
    marker_pattern = re.escape(marker).replace(r"\ ", r"\s+")
    prefix = r"(?:not|no|without|exclude|excluding|avoid|avoiding|not\s+a|not\s+an|not\s+the)"
    return re.search(rf"\b{prefix}\b(?:\W+\w+){{0,6}}\W+{marker_pattern}\b", normalized_lower) is not None
