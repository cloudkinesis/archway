import re
from dataclasses import dataclass, field

from app.services.capability_extractor import explicit_negative_constraints, extract_capabilities
from app.services.metric_extractor import extract_metrics


@dataclass(frozen=True)
class ExtractedMetric:
    label: str
    value: float
    unit: str
    raw: str
    kind: str = "generic"


@dataclass
class UseCaseProfile:
    domain: str | None
    workload_families: list[str]
    excluded_families: list[str]
    capabilities: list[str]
    entities: list[str]
    signals: list[str]
    actions: list[str]
    metrics: list[ExtractedMetric] = field(default_factory=list)
    capability_model: list[str] = field(default_factory=list)
    excluded_patterns: list[str] = field(default_factory=list)
    deployment_posture: list[str] = field(default_factory=list)
    latency_class: str | None = None
    structured_metrics: dict = field(default_factory=dict)
    latency_target: str | None = None
    business_targets: list[str] = field(default_factory=list)
    confidence: str = "medium"
    discovery_plan: dict = field(default_factory=dict)
    capability_decision: dict = field(default_factory=dict)
    profile_source: str = "deterministic"
    open_world_understanding: dict = field(default_factory=dict)

    @property
    def primary_family(self) -> str:
        return self.workload_families[0] if self.workload_families else "general_cloud_application"


_EXCLUDED_FAMILY_CAPABILITY_BLOCKS = {
    "rag_assistant": {"document_retrieval", "rag_retrieval", "document_ingestion", "document_rag_assistant"},
    "document_intelligence": {"document_retrieval", "rag_retrieval", "document_ingestion", "document_rag_assistant"},
    "field_service_automation": {"field_service_dispatch", "dispatch_optimization", "inventory_optimization"},
    "supply_chain_optimization": {"inventory_optimization", "route_optimization"},
}


def reconcile_profile_constraints(profile: UseCaseProfile) -> UseCaseProfile:
    """Apply generic profile invariants after deterministic or model-derived extraction."""
    excluded = set(profile.excluded_families or []) | set(profile.excluded_patterns or [])
    removed_families = [family for family in profile.workload_families if family in excluded]
    profile.workload_families = [family for family in profile.workload_families if family not in excluded] or ["web_api_application"]

    blocked_capabilities: set[str] = set()
    for family in excluded:
        blocked_capabilities.update(_EXCLUDED_FAMILY_CAPABILITY_BLOCKS.get(family, set()))
    if blocked_capabilities:
        profile.capabilities = [item for item in profile.capabilities if item not in blocked_capabilities]
        profile.capability_model = [item for item in profile.capability_model if item not in blocked_capabilities]

    if removed_families or blocked_capabilities:
        plan = dict(profile.discovery_plan or {})
        plan["profile_reconciliation"] = {
            "rule": "exclusion_wins",
            "removed_workload_families": removed_families,
            "removed_capabilities": sorted(blocked_capabilities),
        }
        profile.discovery_plan = plan
    return profile


def profile_use_case(text: str) -> UseCaseProfile:
    lower = text.lower()
    structured_metrics = extract_metrics(text)
    metrics = _extract_metrics(structured_metrics)
    capability_result = extract_capabilities(text)
    negated = explicit_negative_constraints(lower)
    domain = _detect_domain(lower)
    capabilities = _detect_capabilities(lower)
    capabilities = list(dict.fromkeys(capabilities + [item.value for item in capability_result.capabilities]))
    capabilities = [item for item in capabilities if item not in set(negated["capabilities"])]
    workload_families = _rank_workload_families(lower, capabilities)
    workload_families = [family for family in workload_families if family not in set(negated["families"])] or ["web_api_application"]
    excluded = _excluded_families(lower, workload_families)
    excluded = list(dict.fromkeys(excluded + capability_result.excluded_patterns + negated["families"]))
    capability_model = [item.value for item in capability_result.capabilities if item.value not in set(negated["capabilities"])]
    excluded_patterns = list(dict.fromkeys(capability_result.excluded_patterns + negated["patterns"]))
    profile = UseCaseProfile(
        domain=domain,
        workload_families=workload_families,
        excluded_families=excluded,
        capabilities=capabilities,
        entities=_detect_entities(lower),
        signals=_detect_signals(lower),
        actions=_detect_actions(lower),
        metrics=metrics,
        capability_model=capability_model,
        excluded_patterns=excluded_patterns,
        deployment_posture=[item.value for item in capability_result.deployment_posture],
        latency_class=capability_result.latency_class.value if capability_result.latency_class else None,
        structured_metrics=structured_metrics.model_dump(),
        latency_target=_detect_latency_target(text),
        business_targets=_detect_business_targets(text),
        confidence="high" if workload_families and domain and capability_result.confidence == "high" else "medium",
    )
    return reconcile_profile_constraints(refine_profile_with_context(profile, text))


def profile_to_metadata(profile: UseCaseProfile) -> dict:
    return {
        "domain": profile.domain,
        "workload_families": profile.workload_families,
        "excluded_families": profile.excluded_families,
        "capabilities": profile.capabilities,
        "entities": profile.entities,
        "signals": profile.signals,
        "actions": profile.actions,
        "metrics": [metric.__dict__ for metric in profile.metrics],
        "capability_model": profile.capability_model,
        "excluded_patterns": profile.excluded_patterns,
        "deployment_posture": profile.deployment_posture,
        "latency_class": profile.latency_class,
        "structured_metrics": profile.structured_metrics,
        "latency_target": profile.latency_target,
        "business_targets": profile.business_targets,
        "confidence": profile.confidence,
        "discovery_plan": profile.discovery_plan,
        "capability_decision": profile.capability_decision,
        "profile_source": profile.profile_source,
        "open_world_understanding": profile.open_world_understanding,
    }


def profile_from_metadata(metadata: dict | None, raw_use_case: str) -> UseCaseProfile:
    if not metadata:
        return profile_use_case(raw_use_case)
    values = dict(metadata)
    metrics = [ExtractedMetric(**item) for item in values.get("metrics", []) if isinstance(item, dict)]
    profile = UseCaseProfile(
        domain=values.get("domain"),
        workload_families=list(values.get("workload_families") or []),
        excluded_families=list(values.get("excluded_families") or []),
        capabilities=list(values.get("capabilities") or []),
        entities=list(values.get("entities") or []),
        signals=list(values.get("signals") or []),
        actions=list(values.get("actions") or []),
        metrics=metrics,
        capability_model=list(values.get("capability_model") or []),
        excluded_patterns=list(values.get("excluded_patterns") or []),
        deployment_posture=list(values.get("deployment_posture") or []),
        latency_class=values.get("latency_class"),
        structured_metrics=dict(values.get("structured_metrics") or {}),
        latency_target=values.get("latency_target"),
        business_targets=list(values.get("business_targets") or []),
        confidence=values.get("confidence") or "medium",
        discovery_plan=dict(values.get("discovery_plan") or {}),
        capability_decision=dict(values.get("capability_decision") or {}),
        profile_source=values.get("profile_source") or "deterministic",
        open_world_understanding=dict(values.get("open_world_understanding") or {}),
    )
    return reconcile_profile_constraints(refine_profile_with_context(profile, raw_use_case))


def refine_profile_with_context(profile: UseCaseProfile, context_text: str) -> UseCaseProfile:
    lower = context_text.lower()
    capability_result = extract_capabilities(context_text)
    context_capabilities = _detect_capabilities(lower) + [item.value for item in capability_result.capabilities]
    context_metrics = extract_metrics(context_text)
    profile.capabilities = list(dict.fromkeys(profile.capabilities + context_capabilities))
    profile.capability_model = list(dict.fromkeys(profile.capability_model + [item.value for item in capability_result.capabilities]))
    profile.deployment_posture = list(dict.fromkeys(profile.deployment_posture + [item.value for item in capability_result.deployment_posture]))
    profile.entities = list(dict.fromkeys(profile.entities + _detect_entities(lower)))
    profile.signals = list(dict.fromkeys(profile.signals + _detect_signals(lower) + context_metrics.telemetry_signals))
    profile.actions = list(dict.fromkeys(profile.actions + _detect_actions(lower) + context_metrics.operational_actions))
    profile.structured_metrics = _merge_structured_metrics(profile.structured_metrics, context_metrics.model_dump())
    profile.metrics = _dedupe_metrics(profile.metrics + _extract_metrics(context_metrics))
    profile.business_targets = list(dict.fromkeys(profile.business_targets + _detect_business_targets(context_text)))
    latency_target = _detect_latency_target(context_text)
    if latency_target:
        profile.latency_target = latency_target
    if not profile.latency_class and capability_result.latency_class:
        profile.latency_class = capability_result.latency_class.value
    return reconcile_profile_constraints(_apply_explicit_negative_constraints(profile, lower))


def _merge_structured_metrics(existing: dict | None, incoming: dict) -> dict:
    merged = dict(existing or {})
    for section in ("asset_counts", "business_targets"):
        values = dict(merged.get(section) or {})
        for key, payload in (incoming.get(section) or {}).items():
            if not isinstance(payload, dict):
                continue
            current = values.get(key)
            if current is None or (isinstance(current, dict) and current.get("derived") and not payload.get("derived")):
                values[key] = dict(payload)
        merged[section] = values
    for section in ("telemetry_signals", "detection_targets", "operational_actions", "assumptions"):
        merged[section] = list(dict.fromkeys(list(merged.get(section) or []) + list(incoming.get(section) or [])))
    return merged


def _detect_domain(lower: str) -> str | None:
    domain_markers = [
        ("aquaculture", ("aquaculture", "fish farm", "fish farms", "sea cage", "sea cages", "dissolved oxygen")),
        ("wildfire_public_safety", ("wildfire", "smoke plume", "evacuation", "lookout tower", "camera towers")),
        ("aviation_operations", ("airport", "airline", "baggage", "bag scan", "bag scans", "flight schedule", "baggage belt", "airport terminal")),
        ("semiconductor_manufacturing", ("semiconductor", "fab", "fabs", "wafer", "metrology", "tool", "tools")),
        ("investment_banking", ("derivatives", "portfolio greeks", "capital markets", "margin rules", "monte carlo var")),
        ("telecommunications", ("telecom", "cell tower", "subscriber", "5g", "cdr", "trai", "oss/bss", "oss bss")),
        ("energy_utility", ("utility", "grid", "smart meter", "transformer", "feeder", "substation", "distribution")),
        ("manufacturing", ("manufacturing", "manufacturer", "factory", "plant", "plants", "production line", "machine", "equipment", "downtime", "quality inspection", "batch", "reactor", "historian", "mes", "lims", "off-spec")),
        ("healthcare", ("patient", "clinical", "hospital", "health", "medical", "phi", "protected health information")),
        ("legal", ("legal", "contract", "contracts", "clause", "obligation", "obligations", "agreement", "agreements")),
        ("financial_services", ("bank", "fraud", "payment", "trading", "loan", "financial", "pci")),
        ("retail", ("retail", "customer order", "online order", "order fulfillment", "delivery order", "refund", "store", "commerce")),
        ("retail_banking", ("aml", "financial crime", "sar", "bsa")),
        ("insurance", ("catastrophe", "reinsurance", "policies", "solvency")),
        ("government", ("national identity", "citizen", "biometric", "sovereign")),
        ("public_sector", ("agency", "permit", "public sector", "government")),
        ("supply_chain", ("supply chain", "plants", "distribution centers", "sku-location", "sap")),
        ("pharmaceutical", ("pharmaceutical", "compound", "drug", "faers", "gxp")),
        ("autonomous_vehicle", ("autonomous vehicle", "ota", "vehicles", "asil")),
        ("energy_trading", ("intraday", "bidding", "wind/solar", "mifid")),
        ("financial_markets", ("high-frequency", "market making", "microsecond", "exchange data centers")),
        ("media", ("media company", "live sports", "4k hdr", "streaming video", "concurrent viewers", "ad inventory", "subscriber churn")),
        ("education", ("student", "learning", "campus", "course")),
        ("logistics", ("fleet", "route", "warehouse", "shipment", "last mile")),
    ]
    normalized = lower.replace("-", " ")
    for domain, markers in domain_markers:
        if any(_contains_marker(lower, marker) and not _is_marker_negated(normalized, marker) for marker in markers):
            return domain
    return None


def _detect_capabilities(lower: str) -> list[str]:
    capability_markers = [
        ("real_time_ingestion", ("real-time", "realtime", "stream", "sensor", "telemetry", "iot", "smart meter", "camera feeds", "camera streams", "imagery refresh")),
        ("time_series_analytics", ("time-series", "voltage", "temperature", "load imbalance", "trend", "historical pattern")),
        ("anomaly_detection", ("anomaly", "failure detection", "pre-fault", "oscillation", "fraud", "thermal runaway", "imbalance")),
        ("predictive_ml", ("predictive", "prediction", "forecast", "model training", "inference", "failure pattern")),
        ("event_driven_workflow", ("dispatch", "workflow", "ticket", "notify", "alert", "pre-position", "approval", "public alert", "evacuation")),
        ("enterprise_integration", ("existing", "erp", "crm", "workforce", "inventory", "depot", "system integration")),
        ("document_retrieval", ("document", "knowledge base", "policy manual", "manual", "rag", "retrieve", "citation", "contract", "contracts", "clause", "obligation")),
        ("generative_ai", ("assistant", "chatbot", "summarize", "generate", "llm", "foundation model", "agent")),
        ("computer_vision", ("image", "imagery", "video", "camera", "vision", "defect", "ocr", "smoke plume", "fish behavior")),
        ("video_metadata_processing", ("occupancy signal", "occupancy signals", "occupancy metadata", "ephemeral occupancy metadata", "video-derived", "ceiling camera", "camera metadata")),
        ("clinical_workflow_decision_support", ("or utilization", "surgical delay", "surgery delay", "operating room", "charge nurse", "clinical workflow")),
        ("ehr_integration", ("epic", "ehr", "patient check-in", "patient/surgery schedule")),
        ("approval_gated_workflow", ("approval required", "requires approval", "human approval", "approval-gated", "approval gated", "approved before", "approval from")),
        ("intermittent_connectivity", ("intermittent connectivity", "remote connectivity", "unreliable connectivity", "offline site", "offline sites", "store-and-forward", "edge buffering")),
        ("batch_analytics", ("data lake", "warehouse", "etl", "reporting", "dashboard", "analytics")),
        ("api_application", ("api", "mobile app", "web app", "portal")),
    ]
    found = []
    for capability, markers in capability_markers:
        if any(_contains_marker(lower, marker) for marker in markers):
            found.append(capability)
    return found or ["api_application"]


def _rank_workload_families(lower: str, capabilities: list[str]) -> list[str]:
    scores = {
        "operational_event_prediction_workflow": 0,
        "industrial_iot_streaming_ml": 0,
        "real_time_anomaly_detection": 0,
        "field_service_automation": 0,
        "rag_assistant": 0,
        "agentic_workflow": 0,
        "document_intelligence": 0,
        "computer_vision_quality_inspection": 0,
        "financial_fraud_detection": 0,
        "data_platform_analytics": 0,
        "web_api_application": 0,
        "hpc_simulation": 0,
        "federated_ml": 0,
        "graph_analytics": 0,
        "live_streaming": 0,
        "low_latency_trading": 0,
        "telecom_network_analytics": 0,
        "cdr_congestion_prediction": 0,
        "capital_markets_risk_engine": 0,
        "monte_carlo_risk_grid": 0,
        "pre_trade_compliance": 0,
        "healthcare_operations_scheduling": 0,
        "surgical_scheduling_prediction": 0,
        "clinical_workflow_decision_support": 0,
        "computer_vision_metadata_processing": 0,
        "approval_gated_workflow_automation": 0,
    }
    weights = {
        "real_time_ingestion": ("industrial_iot_streaming_ml", "real_time_anomaly_detection", "data_platform_analytics"),
        "time_series_analytics": ("industrial_iot_streaming_ml", "real_time_anomaly_detection", "data_platform_analytics"),
        "anomaly_detection": ("real_time_anomaly_detection", "industrial_iot_streaming_ml"),
        "predictive_ml": ("industrial_iot_streaming_ml", "real_time_anomaly_detection", "data_platform_analytics"),
        "event_driven_workflow": ("operational_event_prediction_workflow", "field_service_automation"),
        "enterprise_integration": ("field_service_automation", "web_api_application"),
        "document_retrieval": ("rag_assistant", "document_intelligence"),
        "generative_ai": ("rag_assistant", "agentic_workflow"),
        "computer_vision": ("computer_vision_quality_inspection", "document_intelligence"),
        "batch_analytics": ("data_platform_analytics",),
        "api_application": ("web_api_application",),
        "hpc_simulation": ("hpc_simulation", "data_platform_analytics"),
        "federated_learning": ("federated_ml",),
        "graph_analytics": ("graph_analytics",),
        "video_streaming": ("live_streaming",),
        "microsecond_latency": ("low_latency_trading",),
        "cdr_ingestion": ("telecom_network_analytics", "cdr_congestion_prediction", "data_platform_analytics"),
        "telecom_regulatory_compliance": ("telecom_network_analytics", "data_platform_analytics"),
        "sla_monitoring": ("telecom_network_analytics", "real_time_anomaly_detection"),
        "market_data_ingestion": ("capital_markets_risk_engine", "data_platform_analytics"),
        "monte_carlo_simulation": ("monte_carlo_risk_grid", "hpc_simulation", "capital_markets_risk_engine"),
        "risk_optimization": ("capital_markets_risk_engine", "monte_carlo_risk_grid"),
        "financial_market_compliance": ("pre_trade_compliance", "capital_markets_risk_engine"),
        "video_metadata_processing": ("computer_vision_metadata_processing", "healthcare_operations_scheduling"),
        "clinical_workflow_decision_support": ("healthcare_operations_scheduling", "surgical_scheduling_prediction", "clinical_workflow_decision_support"),
        "ehr_integration": ("healthcare_operations_scheduling", "clinical_workflow_decision_support", "web_api_application"),
    }
    for capability in capabilities:
        for index, family in enumerate(weights.get(capability, ())):
            scores[family] += 3 - min(index, 2)
    financial_fraud_terms = (
        "fraud",
        "fraudulent",
        "payment fraud",
        "payment transaction",
        "payment transactions",
        "card transaction",
        "card transactions",
        "card payment",
        "chargeback",
        "aml",
        "suspicious financial",
        "suspicious payment",
        "suspicious transaction",
        "account takeover",
        "claim fraud",
    )
    industrial_terms = ("sensor", "telemetry", "smart meter", "transformer", "industrial", "equipment", "fab", "semiconductor", "camera feeds", "camera streams", "imagery refresh", "manufacturer", "factory", "plant", "production line", "batch", "reactor", "historian", "mes", "lims", "spectroscopy", "off-spec")
    explicit_financial_fraud = any(term in lower for term in financial_fraud_terms)
    if explicit_financial_fraud:
        scores["financial_fraud_detection"] += 10
        scores["real_time_anomaly_detection"] += 2
    if any(term in lower for term in industrial_terms):
        scores["industrial_iot_streaming_ml"] += 5
    elif scores["financial_fraud_detection"] > 0:
        scores["industrial_iot_streaming_ml"] = 0
    if any(term in lower for term in ("dispatch", "field crew", "workforce", "depot", "inventory")):
        scores["field_service_automation"] += 4
    elif scores["financial_fraud_detection"] > 0:
        scores["field_service_automation"] = 0
    if any(term in lower for term in ("monte carlo", "simulation", "hpc")):
        scores["hpc_simulation"] += 5
        scores["monte_carlo_risk_grid"] += 6
    if any(term in lower for term in ("derivatives", "portfolio greeks", "margin rules", "var")):
        scores["capital_markets_risk_engine"] += 8
        scores["pre_trade_compliance"] += 4
        scores["data_platform_analytics"] = max(0, scores["data_platform_analytics"] - 2)
        scores["web_api_application"] = 0
    if any(_contains_marker(lower, term) for term in ("cdr", "cell tower", "trai", "qos", "congestion")):
        scores["telecom_network_analytics"] += 8
        scores["cdr_congestion_prediction"] += 7
    if any(term in lower for term in ("contract", "contracts", "clause", "obligation", "obligation tracking", "legal review", "rag q&a", "rag qa")):
        scores["document_intelligence"] += 10
        scores["rag_assistant"] += 8
        scores["agentic_workflow"] += 3
        scores["telecom_network_analytics"] = 0
        scores["cdr_congestion_prediction"] = 0
        scores["industrial_iot_streaming_ml"] = 0
        scores["real_time_anomaly_detection"] = 0
        if not any(term in lower for term in ("dispatch", "field crew", "workforce", "depot", "inventory")):
            scores["field_service_automation"] = 0
    if any(term in lower for term in ("aquaculture", "fish farm", "sea cage", "dissolved oxygen", "underwater camera", "feeding behavior")):
        scores["industrial_iot_streaming_ml"] += 8
        scores["real_time_anomaly_detection"] += 7
        scores["computer_vision_quality_inspection"] += 6
        scores["data_platform_analytics"] += 2
        scores["rag_assistant"] = 0
        scores["document_intelligence"] = 0
        scores["field_service_automation"] = 0
    if any(term in lower for term in ("wildfire", "smoke plume", "lookout tower", "camera towers", "satellite imagery", "evacuation zone")):
        scores["industrial_iot_streaming_ml"] += 7
        scores["real_time_anomaly_detection"] += 8
        scores["computer_vision_quality_inspection"] += 6
        scores["data_platform_analytics"] += 3
        scores["rag_assistant"] = 0
        scores["document_intelligence"] = 0
        scores["field_service_automation"] = 0
    if _is_airport_operations(lower):
        scores["operational_event_prediction_workflow"] += 9
        scores["real_time_anomaly_detection"] += 7
        scores["data_platform_analytics"] += 4
        scores["agentic_workflow"] += 3
        scores["industrial_iot_streaming_ml"] = 0
        scores["rag_assistant"] = 0
        scores["document_intelligence"] = 0
        scores["field_service_automation"] = 0
    if "telecom" in lower and any(term in lower for term in ("hbase", "hdfs", "spark", "oss/bss", "oss bss")):
        scores["telecom_network_analytics"] += 8
        scores["data_platform_analytics"] += 5
        scores["industrial_iot_streaming_ml"] = max(0, scores["industrial_iot_streaming_ml"] - 3)
    if "federated" in lower:
        scores["federated_ml"] += 6
        scores["web_api_application"] = 0
    if any(term in lower for term in ("graph", "nodes", "edges", "gnn")):
        scores["graph_analytics"] += 5
    if any(term in lower for term in ("compound", "drug interaction", "faers", "molecular")):
        scores["graph_analytics"] += 6
        scores["industrial_iot_streaming_ml"] = 0
    if any(term in lower for term in ("live streams", "live sports", "4k hdr", "concurrent viewers", "drm", "cdn")):
        scores["live_streaming"] += 9
        scores["web_api_application"] = 0
        scores["computer_vision_quality_inspection"] = 0
        scores["document_intelligence"] = 0
        scores["rag_assistant"] = 0
        scores["agentic_workflow"] = 0
        scores["industrial_iot_streaming_ml"] = 0
        scores["real_time_anomaly_detection"] = 0
        scores["field_service_automation"] = 0
    if _is_healthcare_operations_scheduling(lower):
        scores["healthcare_operations_scheduling"] += 12
        scores["surgical_scheduling_prediction"] += 10
        scores["clinical_workflow_decision_support"] += 9
        scores["computer_vision_metadata_processing"] += 6
        scores["approval_gated_workflow_automation"] += 6
        scores["industrial_iot_streaming_ml"] = 0
        scores["field_service_automation"] = 0
        scores["computer_vision_quality_inspection"] = 0
        scores["real_time_anomaly_detection"] = max(0, scores["real_time_anomaly_detection"] - 4)
    if any(term in lower for term in ("microsecond", "fpga", "co-located")):
        scores["low_latency_trading"] += 7
        scores["telecom_network_analytics"] = 0
        scores["cdr_congestion_prediction"] = 0
    if any(term in lower for term in ("national identity", "biometric", "enrolled citizens", "verification requests")):
        scores["web_api_application"] = 0
        scores["real_time_anomaly_detection"] = max(0, scores["real_time_anomaly_detection"] - 2)
    if any(term in lower for term in ("drone", "utm", "part 135", "minimum separation", "ground stop")):
        scores["financial_fraud_detection"] = 0
        scores["real_time_anomaly_detection"] = max(0, scores["real_time_anomaly_detection"] - 1)
    if not explicit_financial_fraud:
        scores["financial_fraud_detection"] = 0
    ranked = [family for family, score in sorted(scores.items(), key=lambda item: item[1], reverse=True) if score > 0]
    return ranked[:3] or ["web_api_application"]


def _excluded_families(lower: str, selected: list[str]) -> list[str]:
    excluded = []
    if any(term in lower for term in ("aquaculture", "fish farm", "sea cage", "underwater camera", "wildfire", "smoke plume", "camera towers", "satellite imagery")):
        excluded.extend(["rag_assistant", "document_intelligence"])
    if any(term in lower for term in ("wildfire", "smoke plume", "evacuation", "camera towers")):
        excluded.extend(["field_service_automation", "supply_chain_optimization"])
    if _is_airport_operations(lower):
        excluded.extend(["industrial_iot_streaming_ml", "rag_assistant", "document_intelligence", "field_service_automation", "supply_chain_optimization"])
    if _is_healthcare_operations_scheduling(lower):
        excluded.extend(["industrial_iot_streaming_ml", "field_service_automation", "computer_vision_quality_inspection"])
    if "rag_assistant" not in selected[:2] and any(term in lower for term in ("sensor", "telemetry", "real-time", "dispatch", "predictive")):
        excluded.append("rag_assistant")
    if "computer_vision_quality_inspection" not in selected and not any(term in lower for term in ("image", "video", "camera", "vision")):
        excluded.append("computer_vision_quality_inspection")
    return excluded


def _is_healthcare_operations_scheduling(lower: str) -> bool:
    healthcare = any(_contains_marker(lower, marker) for marker in ("hospital", "patient", "clinical", "hipaa", "phi", "ehr", "epic"))
    surgical_ops = any(_contains_marker(lower, marker) for marker in ("operating room", " or ", "or schedule", "surgery", "surgical", "anesthesia", "charge nurse"))
    workflow = any(_contains_marker(lower, marker) for marker in ("schedule", "utilization", "room turnover", "sterile processing", "instrument tray", "occupancy", "delay prediction", "reassignment"))
    return healthcare and surgical_ops and workflow


def _is_airport_operations(lower: str) -> bool:
    aviation = any(_contains_marker(lower, marker) for marker in ("airport", "airline", "aviation", "terminal", "flight schedule"))
    baggage_ops = any(_contains_marker(lower, marker) for marker in ("baggage", "bag scan", "bag scans", "belt telemetry", "transfer window", "misconnect"))
    return aviation and baggage_ops


def _apply_explicit_negative_constraints(profile: UseCaseProfile, lower: str) -> UseCaseProfile:
    negated = explicit_negative_constraints(lower)
    if not any(negated.values()):
        return profile
    labels = set(negated["labels"])
    blocked_families = set(negated["families"])
    blocked_capabilities = set(negated["capabilities"])
    profile.workload_families = [family for family in profile.workload_families if family not in blocked_families] or ["web_api_application"]
    profile.excluded_families = list(dict.fromkeys(profile.excluded_families + negated["families"]))
    profile.excluded_patterns = list(dict.fromkeys(profile.excluded_patterns + negated["patterns"]))
    profile.capabilities = [capability for capability in profile.capabilities if capability not in blocked_capabilities]
    profile.capability_model = [capability for capability in profile.capability_model if capability not in blocked_capabilities]
    if "document_rag" in labels:
        profile.entities = [item for item in profile.entities if item not in {"document", "contract", "contracts"}]
    if "field_service" in labels:
        profile.entities = [item for item in profile.entities if item not in {"field_crew"}]
        profile.actions = [item for item in profile.actions if item not in {"dispatch", "dispatches_field_crews", "dispatch_field_crews"}]
    if "depot_inventory" in labels:
        profile.entities = [item for item in profile.entities if item not in {"depot", "inventory"}]
    return profile


def _detect_entities(lower: str) -> list[str]:
    markers = (
        "smart meter", "transformer", "feeder", "sensor", "customer", "patient", "transaction", "order",
        "document", "pdf", "docx", "note", "image", "photo", "video", "object", "record", "case",
        "vehicle", "machine", "asset", "site", "field crew", "depot", "airport", "terminal", "baggage",
        "flight schedule",
    )
    return [marker.replace(" ", "_") for marker in markers if marker in lower]


def _detect_signals(lower: str) -> list[str]:
    markers = (
        "voltage", "load imbalance", "ambient temperature", "temperature", "oscillation", "current",
        "vibration", "pressure", "humidity", "location", "payment velocity", "clickstream", "image",
        "imagery", "photo", "video", "multispectral", "sensor reading", "readings", "document", "pdf",
        "docx",
    )
    return [marker.replace(" ", "_") for marker in markers if marker in lower]


def _detect_actions(lower: str) -> list[str]:
    markers = (
        "dispatch", "pre-position", "notify", "alert", "create ticket", "block transaction",
        "block high-confidence", "block high confidence", "queue suspicious", "analyst review", "approve",
        "human approval", "recommend", "triage", "review", "escalate", "schedule", "route",
    )
    return [marker.replace("-", "_").replace(" ", "_") for marker in markers if marker in lower]


_BUSINESS_TARGET_KINDS = {
    "cdrs_per_day": "event_volume",
    "prediction_horizon_minutes": "latency",
    "retention_years": "retention",
    "transactions_per_day": "event_volume",
    "latency_target_ms": "latency",
    "audit_retention_years": "retention",
    "false_positive_reduction_target_percent": "target_percent",
    "greeks_frequency_seconds": "frequency",
    "sensor_channels_per_tool": "telemetry",
    "streaming_sample_rate_khz": "telemetry",
    "prediction_horizon_hours": "latency",
    "false_positive_target_percent": "target_percent",
    "false_alarm_cost_usd": "cost",
    "catastrophic_alert_latency_seconds": "latency",
    "concurrent_viewers": "audience",
    "glass_to_glass_latency_seconds": "latency",
    "refresh_cadence_minutes": "frequency",
    "scheduled_surgeries_per_day": "event_volume",
    "events_per_day": "event_volume",
    "latency_target_minutes": "latency",
    "retention_days": "retention",
    "country_count": "coverage",
    "outage_reduction_target_percent": "target_percent",
    "current_mttr_hours": "current_duration",
    "target_mttr_minutes": "target_duration",
    "target_timeline_months": "timeline",
}

# Profile-level public labels for structured-extractor business-target keys.
# The structured extractor key stays unchanged (consumed directly by
# tests/golden_scenarios and any structured callers); the profile view keeps
# the historical public label that synthesis exposes (see also the
# outage_reduction_target_percent dedupe rule in _dedupe_metrics).
_PROFILE_BUSINESS_TARGET_ALIASES = {
    "unplanned_outage_reduction_percent": "outage_reduction_target_percent",
}


def _extract_metrics(structured_metrics) -> list[ExtractedMetric]:
    """Keep profile.metrics as a compatibility view over the shared extractor.

    The structured extractor in metric_extractor.py is the source of truth. This
    adapter avoids maintaining a second regex table while preserving the older
    list-shaped profile metrics consumed by synthesis, pricing, and diagrams.
    Derived metrics are intentionally omitted to avoid double-counting asset
    totals in callers that sum profile.metrics directly.
    """
    metrics: list[ExtractedMetric] = []
    for label, value in structured_metrics.asset_counts.items():
        if value.derived:
            continue
        metrics.append(ExtractedMetric(label=label, value=value.value, unit=value.unit, raw=value.raw, kind="asset_count"))
    for label, value in structured_metrics.business_targets.items():
        if value.derived:
            continue
        label = _PROFILE_BUSINESS_TARGET_ALIASES.get(label, label)
        metrics.append(
            ExtractedMetric(
                label=label,
                value=value.value,
                unit=value.unit,
                raw=value.raw,
                kind=_BUSINESS_TARGET_KINDS.get(label, "business_target"),
            )
        )
    return _dedupe_metrics(metrics)


def _detect_latency_target(text: str) -> str | None:
    media_match = re.search(r"\b(?P<value>\d+(?:\.\d+)?)\s*[- ]?second\s+glass[- ]to[- ]glass latency", text, flags=re.I)
    if media_match:
        return media_match.group(0)
    sub_match = re.search(r"sub[- ](?P<value>\d+(?:\.\d+)?)\s*[- ]?(?P<unit>second|seconds|minute|minutes|ms|millisecond|milliseconds)", text, flags=re.I)
    if sub_match:
        return sub_match.group(0)
    match = re.search(r"(?:under|within|less than|below)\s+(\d+\s*(?:ms|milliseconds|seconds|minutes|hours|hrs|min))", text, flags=re.I)
    return match.group(0) if match else None


def _contains_marker(lower: str, marker: str) -> bool:
    if len(marker) <= 4 and marker.replace(" ", "").isalnum():
        return re.search(rf"\b{re.escape(marker)}\b", lower) is not None
    return marker in lower


def _is_marker_negated(normalized_lower: str, marker: str) -> bool:
    marker_pattern = re.escape(marker.replace("-", " ")).replace(r"\ ", r"\s+")
    prefix = r"(?:not|no|without|exclude|excluding|avoid|avoiding|not\s+a|not\s+an|not\s+the)"
    return re.search(rf"\b{prefix}\b(?:\W+\w+){{0,6}}\W+{marker_pattern}\b", normalized_lower) is not None


def _detect_business_targets(text: str) -> list[str]:
    targets = []
    fraud_reduction = re.search(r"(?:reduce|reducing|cut)\s+false[- ]positives?\s+by\s+(?P<value>\d+(?:\.\d+)?)\s*(?:percent|%)", text, flags=re.I)
    if fraud_reduction:
        targets.append(f"Reduce false positives by {_format_number(_number(fraud_reduction.group('value')))}%.")
    outage = re.search(r"reduc(?:e|es|ing)\s+unplanned outages by (?P<value>\d+(?:\.\d+)?)%", text, flags=re.I)
    if outage:
        targets.append(f"Reduce unplanned outages by {_format_number(_number(outage.group('value')))}%.")
    mttr = re.search(r"cutting? mean[- ]time[- ]to[- ]restore from (?P<current>\d+(?:\.\d+)?)\s+hours? to under (?P<target>\d+(?:\.\d+)?)\s+minutes?", text, flags=re.I)
    if mttr:
        targets.append(f"Cut MTTR from {_format_number(_number(mttr.group('current')))} hours to under {_format_number(_number(mttr.group('target')))} minutes.")
    timeline = re.search(r"within the first (?P<value>\d+(?:\.\d+)?)\s+months?", text, flags=re.I)
    if timeline:
        targets.append(f"Achieve measurable improvement within {_format_number(_number(timeline.group('value')))} months.")
    if targets:
        return targets
    for pattern in (r"improv(?:e|ing) [^.]{0,80}",):
        targets.extend(match.group(0).strip().rstrip(".") + "." for match in re.finditer(pattern, text, flags=re.I))
    return targets[:6]


def _number(value: str) -> float:
    return float(value.replace(",", ""))


def _format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:g}"



def _dedupe_metrics(metrics: list[ExtractedMetric]) -> list[ExtractedMetric]:
    by_label = {}
    for metric in metrics:
        by_label.setdefault(metric.label, metric)
    if "distribution_transformers" in by_label and "transformers" in by_label:
        by_label.pop("transformers")
    if "outage_reduction_target_percent" in by_label and "reduction_target_percent" in by_label:
        by_label.pop("reduction_target_percent")
    transactions = by_label.get("transactions_per_day")
    if transactions and "average_tps" not in by_label:
        by_label["average_tps"] = ExtractedMetric(
            label="average_tps",
            value=round(transactions.value / 86400, 2),
            unit="transactions_per_second",
            raw="transactions_per_day / 86400",
            kind="derived",
        )
    return list(by_label.values())
