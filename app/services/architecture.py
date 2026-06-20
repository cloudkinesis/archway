import re
from typing import Any

from app.models.domain import AWSServiceRecommendation, ArchitectureComponent, ArchitectureFlow, ArchitectureSpec, ResearchReport
from app.services.canonical_intent import canonical_intent_for_profile
from app.services.pattern_catalog import (
    expected_views,
    observability_controls,
    pattern_components,
    pattern_flows,
    security_controls,
    semantic_views,
)
from app.services.use_case_profile import profile_from_metadata, profile_to_metadata
from app.services.view_planner import diagram_view_mappings, semantic_to_compiler_mapping


class ArchitecturePlanner:
    def generate(self, report: ResearchReport) -> list[ArchitectureSpec]:
        return [self._build(report, production=False), self._build(report, production=True)]

    def _build(self, report: ResearchReport, production: bool) -> ArchitectureSpec:
        profile_metadata = (report.metadata or {}).get("use_case_profile")
        profile = profile_from_metadata(profile_metadata, report.use_case_interpretation)
        intent = canonical_intent_for_profile(profile, report.use_case_interpretation)
        components = pattern_components(profile, production=production)
        components = _open_world_components(profile, components, raw_requirement_text=report.use_case_interpretation, intent=intent)
        flows = pattern_flows(profile, production=production, components=components)
        flows = _open_world_flows(profile, components, flows, intent=intent)
        mode = "production" if production else "poc"
        workload = _workload_title(profile)
        semantic = semantic_views(profile, production=production)
        compiler = expected_views(profile, production=production)
        view_mappings = diagram_view_mappings(semantic, workload)
        workload_context = _workload_specific_context(profile, (report.metadata or {}).get("canonical_fact_snapshot"), raw_requirement_text=report.use_case_interpretation)
        return ArchitectureSpec(
            session_id=report.session_id,
            mode=mode,
            title=f"{mode.upper()} {workload} Architecture",
            summary=_architecture_summary(
                report.recommended_production_direction if production else report.recommended_poc,
                context=workload_context,
                production=production,
            ),
            selected_services=_augment_selected_services(report.aws_service_recommendations, components, intent=intent),
            components=components,
            flows=flows,
            security_controls=security_controls(profile, production=production),
            observability_controls=observability_controls(profile, production=production),
            scaling_strategy=_scaling_strategy(profile, production=production),
            resilience_strategy=_resilience_strategy(profile, production=production),
            cost_optimization_strategy=_cost_strategy(profile, production=production),
            assumptions=report.assumptions,
            risks=report.risks,
            metadata={
                "use_case_profile": profile_to_metadata(profile),
                "workload_families": profile.workload_families,
                "excluded_families": profile.excluded_families,
                "semantic_views": semantic,
                "expected_views": compiler,
                "requested_views": compiler,
                "compiler_view_title_overrides": _compiler_view_title_overrides(workload),
                "semantic_to_compiler_view_mapping": semantic_to_compiler_mapping(semantic),
                "diagram_view_mappings": [mapping.model_dump() for mapping in view_mappings],
                "compiler_view_contract": "Semantic workload views are mapped into the existing Archway D2 compiler's supported view IDs; unsupported dedicated views must be added in the compiler before they can be rendered as separate diagrams.",
                "deployment_target": "aws_only",
                "deployment_target_note": "Archway recommendations and generated diagrams target AWS-native platform services. External enterprise systems may appear only as integration actors or existing customer systems.",
                "network_view_reason": _network_view_reason(profile, production),
                "network_private_connectivity_view_status": _network_view_status(semantic, compiler),
                "requirement_coverage": _requirement_coverage(profile, components, flows, production=production, snapshot=(report.metadata or {}).get("canonical_fact_snapshot")),
                "workload_specific_context": workload_context,
                "canonical_intent": {
                    "streaming_evidence": intent.streaming_evidence,
                    "document_evidence": intent.document_evidence,
                    "approval_evidence": intent.approval_evidence,
                    "notification_evidence": intent.notification_evidence,
                    "external_integration_evidence": intent.external_integration_evidence,
                    "audit_evidence": intent.audit_evidence,
                    "geospatial_evidence": intent.geospatial_evidence,
                    "reasons": list(intent.reasons),
                },
                "architecture_generation": "pattern_catalog",
            },
        )


def _workload_title(profile) -> str:
    entity = _workload_entity_label(profile)
    action = _workload_action_label(profile)
    if entity != "Workload" and action != "Workload Decision":
        return f"{entity} {action}"
    if entity != "Workload":
        return f"{entity} Platform"
    if action != "Workload Decision":
        return f"{action} Platform"
    return " + ".join(family.replace("_", " ").title() for family in profile.workload_families[:3])


def _compiler_view_title_overrides(workload: str) -> dict[str, str]:
    return {
        "production_logical_service_flow": f"{workload} production service flow",
        "network_private_connectivity": f"{workload} private connectivity and integration paths",
        "data_access_view": f"{workload} data, feature, and model dependencies",
        "async_flow_view": f"{workload} event and workflow choreography",
        "ai_security_governance_view": f"{workload} model governance and control flow",
        "security_observability_controls": f"{workload} security, audit, and observability controls",
    }


def _scaling_strategy(profile, production: bool) -> str:
    if "real_time_ingestion" in profile.capabilities:
        base = "Scale ingestion by device/message volume, stream shard or partition demand, streaming analytics capacity, inference throughput, and hot/cold telemetry retention."
    elif "rag_assistant" in profile.workload_families:
        base = "Scale by authenticated request volume, token consumption, retrieval capacity, index size, and document ingestion throughput."
    else:
        base = "Scale by the extracted workload dimensions, API/event volume, storage growth, and downstream integration throughput."
    if production:
        return base + " Use autoscaling, backpressure, quotas, and measured capacity targets before rollout."
    return base + " Keep the POC bounded to representative traffic and explicit quotas."


def _resilience_strategy(profile, production: bool) -> str:
    if production:
        return "Use managed multi-AZ services where available, durable queues/events, replayable streams, idempotent adapters, backups, alarms, and documented degradation paths."
    if profile.actions:
        return "Run action paths in shadow or approval-gated mode with retries, idempotency, and audit records."
    return "Single-region managed services are acceptable for POC validation, with retries and observable failure paths."


def _cost_strategy(profile, production: bool) -> str:
    terms = []
    if "real_time_ingestion" in profile.capabilities:
        terms.extend(["message frequency", "stream retention", "analytics capacity", "inference frequency"])
    if "predictive_ml" in profile.capabilities:
        terms.extend(["training schedule", "endpoint utilization", "model monitoring volume"])
    if "document_retrieval" in profile.capabilities:
        terms.extend(["token volume", "index capacity", "document retention"])
    if profile.actions:
        terms.extend(["workflow transitions", "integration retries", "approval rate"])
    terms = list(dict.fromkeys(terms)) or ["request volume", "storage retention", "observability retention"]
    prefix = "Set production budgets and operational usage alerts for" if production else "Track POC assumptions for"
    return f"{prefix} {', '.join(terms)}."


def _architecture_summary(base: str, *, context: dict | None, production: bool) -> str:
    """Turn the generated architecture note into a stakeholder-readable brief.

    The additions are derived from extracted fact shapes, not from named
    scenarios. They make latency, retention, and workload drivers visible in the
    primary architecture surface so live-model critique has deterministic text
    to reconcile against.
    """
    context = context if isinstance(context, dict) else {}
    quantities = _clean_architecture_fact_list(context.get("quantities") or [], limit=4)
    latency = []
    for item in context.get("latency_slos") or []:
        if isinstance(item, dict):
            value = item.get("target") or item.get("source_text") or item.get("name")
            if value:
                latency.append(str(value).strip())
        elif item:
            latency.append(str(item).strip())
    latency = _clean_architecture_fact_list(latency, limit=3)
    base_summary = _clean_base_architecture_summary(base, context).strip().rstrip(".")
    if _summary_is_generic_or_misaligned(base_summary, context):
        base_summary = _evidence_derived_architecture_summary(context, production=production)
    pieces = [base_summary]
    if latency:
        pieces.append(f"Must carry extracted latency targets such as {', '.join(latency)}")
    if quantities:
        pieces.append(f"Must preserve workload facts for sizing, storage, and review: {'; '.join(quantities)}")
    if production:
        pieces.append("Production design keeps per-data-class retention, audit evidence, and approval boundaries explicit before procurement or rollout")
    else:
        pieces.append("POC design keeps measurable success criteria, pricing drivers, and governance assumptions visible for review")
    return ". ".join(piece for piece in pieces if piece) + "."


def _summary_is_generic_or_misaligned(summary: str, context: dict | None) -> bool:
    text = str(summary or "").lower()
    if not text:
        return True
    generic_markers = (
        "validate answer quality",
        "safe retrieval",
        "curated corpus",
        "tool policy",
        "write actions",
        "generic",
    )
    if any(marker in text for marker in generic_markers):
        return True
    actions = _clean_architecture_fact_list((context or {}).get("actions") or [], limit=3)
    signals = _clean_architecture_fact_list((context or {}).get("signals") or [], limit=3)
    if actions and not any(action.lower() in text for action in actions):
        return True
    if signals and not any(signal.lower() in text for signal in signals):
        return True
    return False


def _evidence_derived_architecture_summary(context: dict | None, *, production: bool) -> str:
    context = context if isinstance(context, dict) else {}
    entity = _context_title_fragment(context, "entities") or "the workload"
    signals = _compact_fact_phrase(context.get("signals") or [], limit=3, fallback="customer-submitted records")
    actions = _compact_fact_phrase(context.get("actions") or [], limit=3, fallback="policy checks, workflow decisions, and status updates")
    actors = _compact_fact_phrase(context.get("actors") or [], limit=2, fallback="business users and operators")
    if production:
        return (
            f"For {entity.lower()} operations, the production design ingests {signals}, "
            f"applies {actions}, keeps human approval and exception handling explicit for {actors}, "
            "and preserves audit, retention, encryption, observability, and integration boundaries for rollout review"
        )
    return (
        f"For {entity.lower()} operations, the POC validates ingestion of {signals}, "
        f"controlled execution of {actions}, and a reviewed path for {actors} before any automated action is trusted"
    )


def _compact_fact_phrase(values: list[Any], *, limit: int, fallback: str) -> str:
    cleaned = _clean_architecture_fact_list(values, limit=limit)
    if not cleaned:
        return fallback
    if len(cleaned) == 1:
        return cleaned[0].lower()
    return ", ".join(item.lower() for item in cleaned[:-1]) + f", and {cleaned[-1].lower()}"


def _clean_base_architecture_summary(base: str, context: dict | None) -> str:
    text = " ".join(str(base or "").split()).strip()
    profile_text = str((context or {}).get("profile_text") or "").lower()
    if "fraud" in profile_text:
        return text
    replacements = {
        "false positives, false negatives, and alert latency": "decision quality, operator workflow accuracy, and alert latency",
        "scored anomaly events": "validated workload events",
        "anomaly event": "workload event",
        "anomaly producers": "event producers",
        "incident state": "operational state",
        "case state": "operational state",
        "dedupe": "idempotency",
    }
    for source, target in replacements.items():
        text = re.sub(re.escape(source), target, text, flags=re.IGNORECASE)
    entity = _context_title_fragment(context, "entities")
    action = _context_title_fragment(context, "actions")
    if entity and action and not text.lower().startswith(entity.lower()):
        text = f"For {entity.lower()} operations, {text[0].lower() + text[1:] if text else text}"
    if action and action.lower() not in text.lower():
        text = f"{text.rstrip('.')}. Keep the {action.lower()} path explicit for review"
    return text


def _context_title_fragment(context: dict | None, key: str) -> str:
    values = (context or {}).get(key) if isinstance(context, dict) else None
    if not isinstance(values, list):
        return ""
    candidates = _clean_architecture_fact_list(values, limit=1)
    return _title_fragment(candidates[0]) if candidates else ""


def _clean_architecture_fact_list(values: list[Any], *, limit: int) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    low_signal = {
        "unknown", "second", "seconds", "minute", "minutes", "hour", "hours",
        "day", "days", "week", "weeks", "month", "months", "year", "years",
    }
    for raw in values:
        text = " ".join(str(raw or "").replace("_", " ").split()).strip(" ,.;")
        if not text:
            continue
        parts = [
            part.strip(" ,.;")
            for part in re.split(r"(?<!\d)\s*[,;]\s*(?!\d)", text)
            if part.strip(" ,.;")
        ]
        for part in parts or [text]:
            lowered = part.lower()
            if lowered in low_signal:
                continue
            if lowered.endswith(" unknown"):
                part = part[: -len(" unknown")].strip(" ,.;")
                lowered = part.lower()
            if " unknown" in lowered:
                part = re.sub(r"\bunknown\b", "", part, flags=re.IGNORECASE).strip(" ,.;")
                lowered = part.lower()
            if not part or lowered in low_signal:
                continue
            if not re.search(r"\d|[a-z]{4,}", lowered):
                continue
            key = re.sub(r"\W+", " ", lowered).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            output.append(part)
            if len(output) >= limit:
                return output
    return output


def _network_view_reason(profile, production: bool) -> str:
    if any(capability in set(profile.capability_model + profile.capabilities) for capability in ("private_connectivity", "external_system_integration", "external_workflow_integration", "inventory_or_depot_integration")):
        return "Network/private connectivity view requested because the workload integrates with external enterprise or operational systems."
    if production:
        return "Network/private connectivity view requested for production posture and managed-service/private integration review."
    return "Network view omitted unless private enterprise connectivity or VPC-resident integration is identified."


def _network_view_status(semantic: list[str], compiler: list[str]) -> dict[str, str | bool]:
    requested = "network_private_connectivity_view" in semantic
    rendered = "network_private_connectivity" in compiler
    if requested and rendered:
        return {
            "requested": True,
            "rendered_as": "network_private_connectivity",
            "reason": "Network/private connectivity view is included in the compiler request.",
        }
    if requested:
        return {
            "requested": True,
            "rendered_as": "",
            "reason": "Requested semantically but not mapped to a supported compiler view.",
        }
    return {
        "requested": False,
        "rendered_as": "",
        "reason": "No private connectivity or external integration signal required a dedicated network view.",
    }


def _augment_selected_services(
    recommendations: list[AWSServiceRecommendation],
    components: list[ArchitectureComponent],
    *,
    intent,
) -> list[AWSServiceRecommendation]:
    output = [
        item for item in recommendations
        if _service_supported_by_canonical_intent(item.service, intent)
    ]
    seen = {item.service.lower() for item in output}
    roles = {str((component.metadata or {}).get("role") or ""): component for component in components}

    def add(service: str, purpose: str, rationale: str, alternatives: list[str] | None = None) -> None:
        if service.lower() in seen:
            return
        output.append(AWSServiceRecommendation(
            service=service,
            purpose=purpose,
            rationale=rationale,
            alternatives_considered=alternatives or [],
            evidence_ids=[],
        ))
        seen.add(service.lower())

    if intent.document_evidence or "document_text_processing" in roles:
        add(
            "Amazon Textract",
            "Document OCR, text, and form extraction",
            "Selected because the canonical workload intent includes documents, PDFs, forms, or OCR-style extraction before human review.",
            ["Amazon Bedrock Data Automation", "Amazon Comprehend", "Custom OCR"],
        )
        add(
            "Amazon S3",
            "Document packet, evidence, and audit artifact storage",
            "Selected because document payloads and appeal-ready evidence need durable lifecycle-managed storage.",
            ["Amazon EFS", "Amazon Aurora"],
        )
    if intent.notification_evidence or "notification_service" in roles:
        add(
            "Amazon SNS / Amazon SES",
            "SMS/email notification fan-out",
            "Selected because the canonical workload intent requires outbound rider, caregiver, operator, or stakeholder notifications.",
            ["Amazon Pinpoint", "EventBridge API Destinations"],
        )
    if intent.external_integration_evidence or "enterprise_integration_adapter" in roles:
        add(
            "Amazon API Gateway",
            "External system integration boundary",
            "Selected because the workload must integrate with existing systems through governed API or adapter boundaries.",
            ["Amazon EventBridge API Destinations", "AWS PrivateLink", "AWS AppSync"],
        )
    if "integration_authorizer" in roles:
        add(
            "Amazon Cognito",
            "Authenticated access for integration and partner-facing APIs",
            "Selected because the architecture exposes an API integration boundary that needs a visible authentication or authorizer control.",
            ["IAM Identity Center", "Customer IdP via SAML/OIDC"],
        )
    if "low_latency_read_model" in roles:
        add(
            "Amazon ElastiCache",
            "Low-latency status and read-model cache",
            "Selected because the workload includes interactive read or status queries with a strict low-second latency target.",
            ["Amazon DynamoDB Accelerator", "Amazon DynamoDB materialized read model"],
        )
    if intent.audit_evidence or "evidence_archive" in roles:
        add(
            "Amazon S3 Object Lock",
            "Immutable evidence archive option",
            "Selected because the workload requires appeal-ready, traceable, or tamper-resistant audit evidence.",
            ["Amazon QLDB", "Amazon Aurora PostgreSQL"],
        )
    return output


def _service_supported_by_canonical_intent(service_name: str, intent) -> bool:
    service = service_name.lower()
    if "location" in service and not getattr(intent, "geospatial_evidence", False):
        return False
    if any(term in service for term in ("kinesis", "flink", "iot core", "managed service for apache flink")) and not getattr(intent, "streaming_evidence", False):
        return False
    return True


def _open_world_components(profile, components: list[ArchitectureComponent], *, raw_requirement_text: str = "", intent=None) -> list[ArchitectureComponent]:
    """Add generic modality components for model-understood use cases.

    This deliberately keys off modality/capability signals instead of named
    domains. Deterministic validation still decides whether the additions cover
    the requirement, and pricing/readiness remain separately gated.
    """
    output = list(components)
    seen = {component.id for component in output}
    profile_text = f"{_profile_requirement_text(profile)} {raw_requirement_text or ''}".lower()
    intent = intent or canonical_intent_for_profile(profile, raw_requirement_text)
    workload_action = _workload_action_label(profile)
    workload_entity = _workload_entity_label(profile)

    def add(component: ArchitectureComponent) -> None:
        if component.id not in seen:
            output.append(component)
            seen.add(component.id)

    if _requires_imagery(profile, profile_text):
        add(ArchitectureComponent(
            id="image_ingest",
            name=f"{workload_entity} Image and Video Evidence Ingestion",
            service="amazon_s3",
            scope="regional_managed_data",
            logical_group="Open-world evidence ingestion",
            metadata={"role": "image_video_ingestion", "source": "open_world_requirement"},
        ))
        add(ArchitectureComponent(
            id="vision_inference",
            name=f"{workload_action} Inference Path",
            service="amazon_sagemaker",
            scope="regional_managed_ai",
            logical_group="Open-world inference",
            metadata={"role": "image_video_inference", "source": "open_world_requirement", "alternatives": ["Amazon Rekognition", "Amazon Bedrock multimodal model"]},
        ))
    if _requires_file_payload_ingestion(profile, profile_text):
        add(ArchitectureComponent(
            id="file_payload_ingest",
            name=f"{workload_entity} File and Batch Payload Ingestion",
            service="amazon_s3",
            scope="regional_managed_data",
            logical_group="Open-world payload ingestion",
            metadata={"role": "file_payload_ingestion", "source": "open_world_requirement"},
        ))
    if _requires_documents(profile, profile_text) and (intent.document_evidence or not _excludes_document_processing(profile)):
        add(ArchitectureComponent(
            id="text_document_processing",
            name=f"{workload_entity} Document and Notes Processing Path",
            service="amazon_textract_bedrock",
            scope="regional_managed_ai",
            logical_group="Open-world evidence processing",
            metadata={"role": "document_text_processing", "source": "open_world_requirement", "alternatives": ["Amazon Textract", "Amazon Bedrock", "Amazon Comprehend"]},
        ))
    if _requires_intermitent_connectivity(profile, profile_text):
        add(ArchitectureComponent(
            id="edge_offline_sync",
            name="Offline Edge Capture and Sync",
            service="aws_iot_greengrass",
            scope="regional_managed_data",
            logical_group="Open-world edge and sync",
            metadata={"role": "offline_store_and_forward", "source": "open_world_requirement", "deployment_posture": "edge_store_and_forward"},
        ))
    if _requires_real_time_stream(profile, profile_text, intent=intent):
        add(ArchitectureComponent(
            id="stream_ingest",
            name=f"{workload_entity} Streaming Ingestion",
            service="kinesis",
            scope="regional_integration",
            logical_group="Real-time ingestion and buffering",
            metadata={"role": "stream_ingestion", "source": "open_world_requirement", "alternatives": ["AWS IoT Core", "Amazon MSK", "Amazon Data Firehose"]},
        ))
        add(ArchitectureComponent(
            id="stream_rule_processor",
            name=f"{workload_action} Stream Processing",
            service="lambda",
            scope="regional_compute",
            logical_group="Hot-path evaluation and enrichment",
            metadata={"role": "stream_rule_processor", "source": "open_world_requirement", "alternatives": ["Amazon Managed Service for Apache Flink", "AWS Step Functions Express"]},
        ))
    if _requires_sensitive_boundary(profile, profile_text):
        add(ArchitectureComponent(
            id="privacy_boundary",
            name="Sensitive Data Boundary and Prompt Filter",
            service="lambda",
            scope="regional_compute",
            logical_group="Privacy and model-safety boundary",
            metadata={"role": "privacy_boundary", "source": "open_world_requirement", "alternatives": ["Amazon Bedrock Guardrails", "Amazon Comprehend PII detection"]},
        ))
    if _requires_external_integration(profile, profile_text):
        add(ArchitectureComponent(
            id="enterprise_integration_adapter",
            name="External System Integration Adapter",
            service="api_gateway",
            scope="regional_entry",
            logical_group="Enterprise integration boundary",
            metadata={"role": "enterprise_integration_adapter", "source": "open_world_requirement", "alternatives": ["Amazon EventBridge API Destinations", "AWS PrivateLink"]},
        ))
        add(ArchitectureComponent(
            id="integration_authorizer",
            name="Integration API Authorizer",
            service="cognito",
            scope="regional_identity",
            logical_group="Enterprise integration boundary",
            metadata={"role": "integration_authorizer", "source": "open_world_requirement", "alternatives": ["Amazon Cognito", "IAM Identity Center", "Customer IdP via SAML/OIDC"]},
        ))
    if _requires_low_latency_read_path(profile, profile_text):
        add(ArchitectureComponent(
            id="low_latency_read_model",
            name=f"{workload_entity} Low-Latency Status and Read Model",
            service="elasticache",
            scope="vpc_resident",
            logical_group="Low-latency read path",
            metadata={"role": "low_latency_read_model", "source": "open_world_requirement", "alternatives": ["Amazon ElastiCache", "Amazon DynamoDB Accelerator", "Amazon DynamoDB materialized read model"]},
        ))
    if intent.notification_evidence:
        add(ArchitectureComponent(
            id="notification_service",
            name="Applicant and Caregiver Notification Service",
            service="sns_ses",
            scope="regional_managed_data",
            logical_group="Notification and outreach",
            metadata={"role": "notification_service", "source": "open_world_requirement", "alternatives": ["Amazon SNS", "Amazon SES", "Amazon Pinpoint"]},
        ))
    if profile.actions and "workflow" not in seen and "policy" not in seen:
        add(ArchitectureComponent(
            id="human_review_workflow",
            name=f"{workload_action} Review and Disposition Workflow",
            service="aws_step_functions",
            scope="regional_orchestration",
            logical_group="Governed action path",
            metadata={"role": "human_approval_workflow", "source": "open_world_requirement"},
        ))
    if _requires_audit_evidence(profile, profile_text):
        add(ArchitectureComponent(
            id="evidence_archive",
            name="Immutable Evidence Archive",
            service="s3",
            scope="regional_managed_data",
            logical_group="Audit and compliance evidence",
            metadata={"role": "immutable_evidence_archive", "source": "open_world_requirement", "storage_mode": "object_lock"},
        ))
        add(ArchitectureComponent(
            id="audit_event_ledger",
            name="Audit Event Ledger",
            service="dynamodb",
            scope="regional_managed_data",
            logical_group="Tamper-evident operational audit",
            metadata={"role": "audit_event_ledger", "source": "open_world_requirement", "alternatives": ["Amazon QLDB migration pattern", "Amazon Aurora PostgreSQL"]},
        ))
    if _requires_dashboard(profile, profile_text):
        add(ArchitectureComponent(
            id="operational_dashboard",
            name="Operations Dashboard and SLA View",
            service="cloudwatch",
            scope="regional_observability",
            logical_group="Operational visibility",
            metadata={"role": "operational_dashboard", "source": "open_world_requirement", "alternatives": ["Amazon QuickSight", "Amazon Managed Grafana"]},
        ))
    return output


def _open_world_flows(profile, components: list[ArchitectureComponent], flows: list[ArchitectureFlow], *, intent=None) -> list[ArchitectureFlow]:
    output = list(flows)
    ids = {component.id for component in components}
    index = len(output) + 1
    workload_action = _workload_action_label(profile).lower()
    workload_entity = _workload_entity_label(profile).lower()
    profile_text = _profile_requirement_text(profile).lower()
    intent = intent or canonical_intent_for_profile(profile)

    def add(source: str, target: str, label: str, protocol: str = "managed AWS service integration") -> None:
        nonlocal index
        if source in ids and target in ids:
            output.append(ArchitectureFlow(
                id=f"ow{index}",
                source=source,
                target=target,
                label=label,
                protocol=protocol,
                metadata={"classification": "open_world_requirement_flow"},
            ))
            index += 1

    source_id = "edge_offline_sync" if "edge_offline_sync" in ids else "devices" if "devices" in ids else "user" if "user" in ids else ""
    if source_id:
        if intent.streaming_evidence:
            add(source_id, "stream_ingest", f"Publish {workload_entity} source events into the hot path", "HTTPS/MQTT/TLS")
        add(source_id, "image_ingest", f"Capture and persist {workload_entity} image/video evidence with workload metadata", "HTTPS/MQTT/TLS")
        add(source_id, "file_payload_ingest", f"Capture {workload_entity} file payloads with lifecycle policy and audit tags", "HTTPS/MQTT/TLS")
        if "privacy_boundary" not in ids:
            add(source_id, "text_document_processing", f"Submit {workload_entity} notes, documents, or OCR text for extraction", "HTTPS/TLS")
    if intent.streaming_evidence:
        add("enterprise_integration_adapter", "stream_ingest", "Normalize external system events into the streaming ingestion contract", "HTTPS/TLS")
        add("stream_ingest", "privacy_boundary", "Filter sensitive fields before model prompts, dashboards, or external notifications")
    add("privacy_boundary", "stream_rule_processor", f"Forward privacy-safe events for {workload_action} evaluation")
    add("file_payload_ingest", "privacy_boundary", "Apply sensitive-data separation before extraction and model prompts")
    add("privacy_boundary", "text_document_processing", f"Forward privacy-safe {workload_entity} documents for extraction")
    add("stream_ingest", "stream_rule_processor", f"Evaluate {workload_action} rules, windows, and thresholds on the hot path")
    add("stream_rule_processor", "events", "Provide validated workload events for workflow and notification consumers")
    add("stream_rule_processor", "audit_event_ledger", "Record event state, idempotency keys, and evaluation outcomes")
    add("audit_event_ledger", "evidence_archive", "Archive immutable audit evidence and retention snapshots")
    add("stream_rule_processor", "operational_dashboard", "Feed operational status, latency, and SLA signals")
    add("events", "operational_dashboard", "Refresh operator view from routed workflow events")
    add("image_ingest", "vision_inference", f"Run preprocessing and model inference for {workload_action}")
    add("file_payload_ingest", "evidence_archive", "Persist file payloads under per-data-class retention controls")
    add("text_document_processing", "vision_inference", "Join extracted text with visual and event features")
    add("text_document_processing", "human_review_workflow", _document_to_review_label(profile, profile_text, workload_action))
    workflow_target = "human_review_workflow" if "human_review_workflow" in ids else "workflow" if "workflow" in ids else ""
    if workflow_target:
        add("integration_authorizer", "enterprise_integration_adapter", "Authorize partner and external-system API requests before integration access")
        add("enterprise_integration_adapter", workflow_target, "Read governed external system records into the review workflow", "HTTPS/TLS")
        add(workflow_target, "low_latency_read_model", "Publish approved status and summary facts into the low-latency read path")
        add(workflow_target, "notification_service", "Send approved status, follow-up, and scheduling notifications")
        add(workflow_target, "operational_dashboard", "Display workflow status, SLA, and exception metrics")
    add("low_latency_read_model", "operational_dashboard", "Serve low-latency status, queue, and SLA views for operators")
    add("notification_service", "audit_event_ledger", "Record notification delivery evidence and exceptions")
    if "vision_inference" in ids:
        target = workflow_target
        if target:
            add("vision_inference", target, f"Route {workload_action} recommendations to governed human review")
    if "human_review_workflow" in ids:
        add("human_review_workflow", "evidence_archive", "Write approved decision, evidence bundle, and audit trail")
    elif "evidence_archive" in ids and "vision_inference" in ids:
        add("vision_inference", "evidence_archive", "Store inference evidence and trace records")
    if "human_review_workflow" in ids:
        add("stream_rule_processor", "human_review_workflow", f"Route {workload_action} exceptions to governed human review")
    return output


def _profile_requirement_text(profile) -> str:
    return " ".join(
        str(item)
        for item in [
            getattr(profile, "domain", None),
            *list(getattr(profile, "capabilities", []) or []),
            *list(getattr(profile, "capability_model", []) or []),
            *list(getattr(profile, "entities", []) or []),
            *list(getattr(profile, "signals", []) or []),
            *list(getattr(profile, "actions", []) or []),
            *list(getattr(profile, "business_targets", []) or []),
        ]
        if item
    ).lower()


def _workload_action_label(profile) -> str:
    candidates = _clean_architecture_fact_list(
        list(getattr(profile, "actions", []) or [])
        + list(getattr(profile, "signals", []) or [])
        + list(getattr(profile, "capabilities", []) or []),
        limit=1,
    )
    return _title_fragment(candidates[0]) if candidates else "Workload Decision"


def _workload_entity_label(profile) -> str:
    candidates = _clean_architecture_fact_list(
        list(getattr(profile, "entities", []) or [])
        + list(getattr(profile, "signals", []) or []),
        limit=1,
    )
    return _title_fragment(candidates[0]) if candidates else "Workload"


def _title_fragment(value: str) -> str:
    text = re.sub(r"[_/]+", " ", str(value or "")).strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return "Workload"
    return " ".join(word.capitalize() for word in text.split()[:5])


def _requires_imagery(profile, profile_text: str) -> bool:
    if any(term in profile_text for term in ("image", "imagery", "photo", "video", "camera", "vision", "multispectral")):
        return True
    return "computer_vision" in set(profile.capabilities or []) and not _requires_documents(profile, profile_text)


def _requires_documents(profile, profile_text: str) -> bool:
    return "document_retrieval" in set(profile.capabilities or []) or any(
        term in profile_text for term in ("document", "pdf", "docx", "note", "contract", "text", "ocr", "form", "forms", "packet", "packets", "approval letter", "approval letters")
    )


def _requires_file_payload_ingestion(profile, profile_text: str) -> bool:
    return any(
        term in profile_text
        for term in ("file", "files", "payload", "upload", "uploads", "mb", "gb", "result", "evidence", "attachment")
    )


def _excludes_document_processing(profile) -> bool:
    excluded = set(getattr(profile, "excluded_families", []) or []) | set(getattr(profile, "excluded_patterns", []) or [])
    return bool({
        "document_intelligence",
        "ocr_document_pipeline",
        "contract_review",
    } & excluded)


def _requires_intermitent_connectivity(profile, profile_text: str) -> bool:
    return "intermittent_connectivity" in set(profile.capabilities or []) or any(
        term in profile_text for term in ("intermittent", "offline", "store and forward", "store-and-forward", "sync later", "edge")
    )


def _requires_real_time_stream(profile, profile_text: str, *, intent=None) -> bool:
    if intent is not None:
        return bool(intent.streaming_evidence)
    capabilities = set(getattr(profile, "capabilities", []) or []) | set(getattr(profile, "capability_model", []) or [])
    if not bool({"real_time_ingestion", "device_telemetry", "stream_processing"} & capabilities):
        return False
    return canonical_intent_for_profile(profile, profile_text).streaming_evidence


def _requires_sensitive_boundary(profile, profile_text: str) -> bool:
    capabilities = set(getattr(profile, "capability_model", []) or []) | set(getattr(profile, "capabilities", []) or [])
    return bool({"phi_data", "pii_data", "sensitive_data", "privacy_guardrails"} & capabilities) or any(
        term in profile_text
        for term in ("phi", "pii", "sensitive", "prompt", "model prompt", "redact", "tokenize", "guardrail", "privacy")
    )


def _requires_external_integration(profile, profile_text: str) -> bool:
    capabilities = set(getattr(profile, "capability_model", []) or []) | set(getattr(profile, "capabilities", []) or [])
    return bool({"external_system_integration", "external_workflow_integration", "private_connectivity"} & capabilities) or any(
        term in profile_text
        for term in ("external", "integration", "erp", "crm", "lab", "partner", "vendor", "third-party", "existing")
    )


def _requires_low_latency_read_path(profile, profile_text: str) -> bool:
    """Require an explicit read model/cache for interactive low-second reads.

    Low latency alone can describe batch generation or alerts. Read/query
    language alone can use ordinary storage. The combination is the topology
    signal a senior architecture review expects.
    """
    read_terms = (
        "status", "query", "queries", "lookup", "look up", "read", "retrieve",
        "answer", "dashboard", "browse", "search", "check", "checking",
    )
    if not any(term in profile_text for term in read_terms):
        return False
    latency_text = " ".join(str(item) for item in list(getattr(profile, "business_targets", []) or []))
    latency_text = f"{latency_text} {profile_text}".lower()
    if re.search(r"\b(?:sub[- ]?second|under\s+[1-5]\s*seconds?|within\s+[1-5]\s*seconds?|<\s*[1-5]\s*s)\b", latency_text):
        return True
    return bool(re.search(r"\b[1-5]\s*seconds?\b", latency_text))


def _document_to_review_label(profile, profile_text: str, workload_action: str) -> str:
    if any(term in profile_text for term in ("briefing packet", "briefing", "summary", "summaries", "generate", "generated")):
        return f"Generate briefing-ready document facts and route them into {workload_action} review"
    return f"Route extracted document facts into {workload_action} review"


def _requires_audit_evidence(profile, profile_text: str) -> bool:
    capabilities = set(getattr(profile, "capability_model", []) or []) | set(getattr(profile, "capabilities", []) or [])
    return bool({"auditability", "compliance_audit", "immutable_audit", "data_retention"} & capabilities) or any(
        term in profile_text
        for term in ("evidence", "audit", "regulator", "compliance", "retention", "retain", "chain-of-custody", "chain of custody", "custody")
    )


def _requires_dashboard(profile, profile_text: str) -> bool:
    capabilities = set(getattr(profile, "capability_model", []) or []) | set(getattr(profile, "capabilities", []) or [])
    return bool({"observability", "sla_monitoring"} & capabilities) or any(
        term in profile_text
        for term in ("dashboard", "operator", "manager", "operations", "monitor", "sla", "slo", "breach", "status")
    )


def _requirement_coverage(profile, components, flows, production: bool, snapshot: dict | None = None) -> dict[str, list[dict[str, str]]]:
    """Audit how hard profile requirements map into the generated pattern.

    This is intentionally deterministic and advisory. It gives validators and
    export readers a concrete place to see whether important extracted facts were
    carried into the architecture, without letting model-proposed claims alter
    compiler truth.
    """
    capabilities = set(profile.capabilities or [])
    posture = set(profile.deployment_posture or [])
    profile_text = _profile_requirement_text(profile)
    snapshot_text = _snapshot_requirement_text(snapshot)
    requirement_text = f"{profile_text} {snapshot_text}".lower()
    component_text = " ".join([
        *(getattr(component, "name", "") for component in components),
        *(getattr(component, "service", "") for component in components),
        *(getattr(component, "purpose", "") for component in components),
        *(getattr(component, "logical_group", "") or "" for component in components),
    ]).lower()
    component_roles = {
        str((getattr(component, "metadata", {}) or {}).get("role") or "")
        for component in components
    }
    flow_text = " ".join([*(getattr(flow, "label", "") or "" for flow in flows), *(" ".join(str(value) for value in getattr(flow, "metadata", {}).values()) for flow in flows)]).lower()
    body = f"{component_text} {flow_text}"
    requirements: list[dict[str, str]] = []

    def add(requirement_id: str, label: str, status: str, message: str) -> None:
        requirements.append({
            "id": requirement_id,
            "label": label,
            "status": status,
            "message": message,
        })

    intent = canonical_intent_for_profile(profile, requirement_text)
    image_or_video_required = (
        ("computer_vision" in capabilities and not intent.document_evidence)
        or any(
        term in requirement_text
        for term in ("image", "imagery", "photo", "video", "camera", "vision", "multispectral")
        )
    )
    if image_or_video_required:
        covered = any(term in body for term in ("video", "image", "imagery", "photo", "camera", "vision", "multispectral", "rekognition"))
        add(
            "computer_vision_hot_path",
            "Computer vision / imagery processing",
            "covered" if covered else "unmet",
            "Architecture carries an imagery/video inference path." if covered else "Computer-vision requirement was extracted but no imagery/video inference path is explicit.",
        )
    file_payload_required = "file_payload_ingestion" in component_roles or any(term in requirement_text for term in ("file", "files", "payload", "upload", "uploads", "mb", "gb", "attachment"))
    if file_payload_required:
        covered = any(term in body for term in ("file", "payload", "upload", "s3", "object", "archive", "evidence"))
        add(
            "file_payload_ingestion",
            "File / payload ingestion",
            "covered" if covered else "unmet",
            "Architecture carries a file/payload ingestion and storage path." if covered else "File or payload upload requirements were extracted but no ingestion/storage path is explicit.",
        )
    document_required = not _excludes_document_processing(profile) and (
        "document_text_processing" in component_roles
        or "document_retrieval" in capabilities
        or any(term in requirement_text for term in ("document", "pdf", "docx", "note", "contract", "text", "ocr", "form", "forms", "packet", "packets", "approval letter", "approval letters"))
    )
    if document_required:
        covered = any(term in body for term in ("document", "pdf", "docx", "text", "ocr", "textract", "knowledge base", "opensearch", "bedrock"))
        add(
            "document_processing_path",
            "Document / text processing",
            "covered" if covered else "unmet",
            "Architecture carries a document/text processing path." if covered else "Document/text requirement was extracted but no document processing path is explicit.",
        )
    if "real_time_ingestion" in capabilities:
        covered = any(term in body for term in ("stream", "kinesis", "iot", "telemetry", "event"))
        add(
            "real_time_ingestion",
            "Real-time ingestion",
            "covered" if covered else "unmet",
            "Architecture carries a streaming/event ingestion path." if covered else "Real-time ingestion was extracted but no streaming/event path is explicit.",
        )
    if "intermittent_connectivity" in capabilities or {"edge_processing", "hybrid_edge"} & posture or _requires_intermitent_connectivity(profile, requirement_text):
        covered = any(term in body for term in ("edge", "buffer", "offline", "store-and-forward", "iot greengrass"))
        add(
            "intermittent_connectivity",
            "Intermittent connectivity / edge buffering",
            "covered" if covered else "unmet",
            "Architecture carries an edge/buffering path for intermittent sites." if covered else "Intermittent connectivity was extracted but edge buffering is not explicit.",
        )
    if profile.actions:
        covered = any(term in body for term in ("approval", "human", "step functions", "workflow", "notification", "sns"))
        add(
            "governed_action_path",
            "Governed action path",
            "covered" if covered else "unmet",
            "Architecture carries approval/workflow controls for actions." if covered else "Actions were extracted but approval/workflow controls are not explicit.",
        )
    if any(term in requirement_text for term in ("minute", "second", "latency", "sla", "slo", "within", "real-time", "real time")):
        covered = any(term in body for term in ("latency", "within", "hot path", "stream", "real-time", "real time", "slo", "sla", "minute", "second"))
        add(
            "latency_slo",
            "Latency / SLO target",
            "covered" if covered else "unmet",
            "Architecture explicitly carries latency or hot-path processing targets." if covered else "Latency/SLO targets were extracted but not explicit in architecture text.",
        )
    if any(term in requirement_text for term in ("retain", "retention", "archive", "years", "months", "days", "audit")):
        covered = any(term in body for term in ("retention", "lifecycle", "archive", "object lock", "audit", "backup", "evidence"))
        add(
            "retention_policy",
            "Retention / lifecycle policy",
            "covered" if covered else "unmet",
            "Architecture carries retention, archive, or lifecycle controls." if covered else "Retention requirements were extracted but not explicit in architecture text.",
        )
    if any(term in requirement_text for term in ("every", "per ", "kb", "mb", "gb", "frequency", "payload", "times per", "requests", "events")):
        covered = any(term in body for term in ("pricing", "driver", "volume", "frequency", "payload", "sizing", "capacity", "quota", "event"))
        add(
            "pricing_driver_visibility",
            "Pricing driver visibility",
            "covered" if covered else "unmet",
            "Architecture text keeps workload sizing and pricing drivers visible for review." if covered else "Extracted workload drivers were not visible in architecture text.",
        )
    if any(term in requirement_text for term in ("residency", "sovereign", "eu", "europe", "regional", "country")):
        covered = any(term in body for term in ("region", "residency", "multi-region", "cross-region", "kms", "backup", "replication"))
        add(
            "data_residency_boundary",
            "Data residency / regional boundary",
            "covered" if covered else "unmet",
            "Architecture names regional/residency controls." if covered else "Data residency or regional constraints were extracted but no boundary/control is explicit.",
        )
    return {
        "schema": "architecture_requirement_coverage_v1",
        "mode": "production" if production else "poc",
        "requirements": requirements,
    }


def _snapshot_requirement_text(snapshot: dict | None) -> str:
    if not isinstance(snapshot, dict):
        return ""
    values: list[str] = []
    for key in ("quantities", "latency_slos", "connectivity_constraints", "compliance_security_hints"):
        for item in snapshot.get(key) or []:
            if isinstance(item, dict):
                values.extend(str(value) for value in item.values() if value)
            elif item:
                values.append(str(item))
    return " ".join(values)


def _workload_specific_context(profile, snapshot: dict | None, *, raw_requirement_text: str = "") -> dict:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    quantities = []
    for item in snapshot.get("quantities") or []:
        if not isinstance(item, dict):
            continue
        if item.get("name") == "total_monitored_assets":
            continue
        source = item.get("source_text")
        if str(source or "").lower().startswith("sum of "):
            continue
        if source and source not in quantities:
            quantities.append(source)
    quantities = _prefer_specific_quantity_sources(quantities)
    profile_text = f"{_profile_requirement_text(profile)} {raw_requirement_text or ''}".lower()
    support_text = f"{raw_requirement_text or ''} {_snapshot_requirement_text(snapshot)}".lower()
    actions = [
        item for item in list(dict.fromkeys(profile.actions or []))[:12]
        if _context_term_supported(item, support_text)
    ]
    signals = [
        item for item in list(dict.fromkeys(profile.signals or []))[:12]
        if _context_term_supported(item, support_text)
    ]
    entities = [
        item for item in list(dict.fromkeys(profile.entities or []))[:12]
        if _context_term_supported(item, support_text)
    ]
    return {
        "domain": profile.domain,
        "profile_text": profile_text,
        "signals": signals,
        "actions": actions,
        "entities": entities,
        "quantities": quantities[:16],
        "latency_slos": list(snapshot.get("latency_slos") or [])[:8],
        "connectivity_constraints": list(snapshot.get("connectivity_constraints") or [])[:8],
        "compliance_security_hints": list(snapshot.get("compliance_security_hints") or [])[:8],
    }


def _context_term_supported(value: str, profile_text: str) -> bool:
    normalized = str(value or "").replace("_", " ").lower().strip()
    if not normalized:
        return False
    if normalized == "dispatch":
        return bool(re.search(r"\bdispatch\s+(?:crew|crews|vehicle|vehicles|technician|technicians|driver|drivers|courier|couriers|team|teams|work|job|response|responder|responders)\b", profile_text))
    if normalized == "recommend operational recovery action":
        return "recovery" in profile_text and "recommend" in profile_text
    tokens = [token for token in re.findall(r"[a-z0-9]+", normalized) if len(token) > 3]
    return not tokens or any(token in profile_text for token in tokens)


def _prefer_specific_quantity_sources(values: list[str]) -> list[str]:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    lowered = [value.lower() for value in cleaned]
    specific: list[str] = []
    for index, value in enumerate(cleaned):
        prefix = lowered[index] + " "
        if any(other.startswith(prefix) for other_index, other in enumerate(lowered) if other_index != index):
            continue
        specific.append(value)
    return specific
