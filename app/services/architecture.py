import re
from typing import Any

from app.models.domain import ArchitectureComponent, ArchitectureFlow, ArchitectureSpec, ResearchReport
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
        components = pattern_components(profile, production=production)
        components = _open_world_components(profile, components)
        flows = pattern_flows(profile, production=production, components=components)
        flows = _open_world_flows(profile, components, flows)
        mode = "production" if production else "poc"
        workload = _workload_title(profile)
        semantic = semantic_views(profile, production=production)
        compiler = expected_views(profile, production=production)
        view_mappings = diagram_view_mappings(semantic, workload)
        workload_context = _workload_specific_context(profile, (report.metadata or {}).get("canonical_fact_snapshot"))
        return ArchitectureSpec(
            session_id=report.session_id,
            mode=mode,
            title=f"{mode.upper()} {workload} Architecture",
            summary=_architecture_summary(
                report.recommended_production_direction if production else report.recommended_poc,
                context=workload_context,
                production=production,
            ),
            selected_services=report.aws_service_recommendations,
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
                "architecture_generation": "pattern_catalog",
            },
        )


def _workload_title(profile) -> str:
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
    prefix = "Set production budgets and anomaly alerts for" if production else "Track POC assumptions for"
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
    pieces = [str(base).strip().rstrip(".")]
    if latency:
        pieces.append(f"Must carry extracted latency targets such as {', '.join(latency)}")
    if quantities:
        pieces.append(f"Must preserve workload facts for sizing, storage, and review: {'; '.join(quantities)}")
    if production:
        pieces.append("Production design keeps per-data-class retention, audit evidence, and approval boundaries explicit before procurement or rollout")
    else:
        pieces.append("POC design keeps measurable success criteria, pricing drivers, and governance assumptions visible for review")
    return ". ".join(piece for piece in pieces if piece) + "."


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
            for part in re.split(r"(?<!\d)\s*,\s*(?!\d)", text)
            if part.strip(" ,.;")
        ]
        for part in parts or [text]:
            lowered = part.lower()
            if lowered in low_signal:
                continue
            if lowered.endswith(" unknown"):
                part = part[: -len(" unknown")].strip(" ,.;")
                lowered = part.lower()
            if not part or lowered in low_signal:
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


def _open_world_components(profile, components: list[ArchitectureComponent]) -> list[ArchitectureComponent]:
    """Add generic modality components for model-understood use cases.

    This deliberately keys off modality/capability signals instead of named
    domains. Deterministic validation still decides whether the additions cover
    the requirement, and pricing/readiness remain separately gated.
    """
    output = list(components)
    seen = {component.id for component in output}
    profile_text = _profile_requirement_text(profile)

    def add(component: ArchitectureComponent) -> None:
        if component.id not in seen:
            output.append(component)
            seen.add(component.id)

    if _requires_imagery(profile, profile_text):
        add(ArchitectureComponent(
            id="image_ingest",
            name="Image and Video Evidence Ingestion",
            service="amazon_s3",
            scope="regional_managed_data",
            logical_group="Open-world evidence ingestion",
            metadata={"role": "image_video_ingestion", "source": "open_world_requirement"},
        ))
        add(ArchitectureComponent(
            id="vision_inference",
            name="Computer Vision Inference Path",
            service="amazon_sagemaker",
            scope="regional_managed_ai",
            logical_group="Open-world inference",
            metadata={"role": "image_video_inference", "source": "open_world_requirement", "alternatives": ["Amazon Rekognition", "Amazon Bedrock multimodal model"]},
        ))
    if _requires_file_payload_ingestion(profile, profile_text):
        add(ArchitectureComponent(
            id="file_payload_ingest",
            name="File and Batch Payload Ingestion",
            service="amazon_s3",
            scope="regional_managed_data",
            logical_group="Open-world payload ingestion",
            metadata={"role": "file_payload_ingestion", "source": "open_world_requirement"},
        ))
    if _requires_documents(profile, profile_text) and not _excludes_document_processing(profile):
        add(ArchitectureComponent(
            id="text_document_processing",
            name="Document and Notes Processing Path",
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
    if profile.actions and "workflow" not in seen and "policy" not in seen:
        add(ArchitectureComponent(
            id="human_review_workflow",
            name="Human Review and Disposition Workflow",
            service="aws_step_functions",
            scope="regional_orchestration",
            logical_group="Governed action path",
            metadata={"role": "human_approval_workflow", "source": "open_world_requirement"},
        ))
    if any(term in profile_text for term in ("evidence", "audit", "regulator", "compliance", "retention")):
        add(ArchitectureComponent(
            id="evidence_archive",
            name="Immutable Evidence Archive",
            service="amazon_s3_object_lock",
            scope="regional_managed_data",
            logical_group="Audit and compliance evidence",
            metadata={"role": "immutable_evidence_archive", "source": "open_world_requirement"},
        ))
    return output


def _open_world_flows(profile, components: list[ArchitectureComponent], flows: list[ArchitectureFlow]) -> list[ArchitectureFlow]:
    output = list(flows)
    ids = {component.id for component in components}
    index = len(output) + 1

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
        add(source_id, "image_ingest", "Capture and persist image/video evidence with workload metadata", "HTTPS/MQTT/TLS")
        add(source_id, "file_payload_ingest", "Capture file payloads with workload metadata, lifecycle policy, and audit tags", "HTTPS/MQTT/TLS")
        add(source_id, "text_document_processing", "Submit notes, documents, or OCR text for extraction", "HTTPS/TLS")
    add("image_ingest", "vision_inference", "Run image/video preprocessing and model inference")
    add("file_payload_ingest", "evidence_archive", "Persist file payloads under per-data-class retention controls")
    add("text_document_processing", "vision_inference", "Join extracted text with visual and event features")
    if "vision_inference" in ids:
        target = "human_review_workflow" if "human_review_workflow" in ids else "workflow" if "workflow" in ids else ""
        if target:
            add("vision_inference", target, "Route recommendations to governed human review")
    if "human_review_workflow" in ids:
        add("human_review_workflow", "evidence_archive", "Write approved decision, evidence bundle, and audit trail")
    elif "evidence_archive" in ids and "vision_inference" in ids:
        add("vision_inference", "evidence_archive", "Store inference evidence and trace records")
    return output


def _profile_requirement_text(profile) -> str:
    return " ".join(
        str(item)
        for item in [
            profile.domain,
            *list(profile.capabilities or []),
            *list(profile.capability_model or []),
            *list(profile.entities or []),
            *list(profile.signals or []),
            *list(profile.actions or []),
            *list(profile.business_targets or []),
        ]
        if item
    ).lower()


def _requires_imagery(profile, profile_text: str) -> bool:
    return "computer_vision" in set(profile.capabilities or []) or any(
        term in profile_text
        for term in ("image", "imagery", "photo", "video", "camera", "vision", "multispectral", "ocr", "scan")
    )


def _requires_documents(profile, profile_text: str) -> bool:
    return "document_retrieval" in set(profile.capabilities or []) or any(
        term in profile_text for term in ("document", "pdf", "docx", "note", "contract", "text", "ocr")
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

    image_or_video_required = "computer_vision" in capabilities or any(
        term in requirement_text
        for term in ("image", "imagery", "photo", "video", "camera", "vision", "multispectral", "ocr", "scan")
    )
    if image_or_video_required:
        covered = any(term in body for term in ("video", "image", "imagery", "photo", "camera", "vision", "multispectral", "ocr", "rekognition", "textract"))
        add(
            "computer_vision_hot_path",
            "Computer vision / imagery processing",
            "covered" if covered else "unmet",
            "Architecture carries an imagery/video inference path." if covered else "Computer-vision requirement was extracted but no imagery/video inference path is explicit.",
        )
    file_payload_required = any(term in requirement_text for term in ("file", "files", "payload", "upload", "uploads", "mb", "gb", "attachment"))
    if file_payload_required:
        covered = any(term in body for term in ("file", "payload", "upload", "s3", "object", "archive", "evidence"))
        add(
            "file_payload_ingestion",
            "File / payload ingestion",
            "covered" if covered else "unmet",
            "Architecture carries a file/payload ingestion and storage path." if covered else "File or payload upload requirements were extracted but no ingestion/storage path is explicit.",
        )
    document_required = not _excludes_document_processing(profile) and (
        "document_retrieval" in capabilities or any(term in requirement_text for term in ("document", "pdf", "docx", "note", "contract", "text", "ocr"))
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


def _workload_specific_context(profile, snapshot: dict | None) -> dict:
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
    return {
        "domain": profile.domain,
        "signals": list(dict.fromkeys(profile.signals or []))[:12],
        "actions": list(dict.fromkeys(profile.actions or []))[:12],
        "entities": list(dict.fromkeys(profile.entities or []))[:12],
        "quantities": quantities[:16],
        "latency_slos": list(snapshot.get("latency_slos") or [])[:8],
        "connectivity_constraints": list(snapshot.get("connectivity_constraints") or [])[:8],
        "compliance_security_hints": list(snapshot.get("compliance_security_hints") or [])[:8],
    }


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
