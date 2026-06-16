from app.models.domain import ArchitectureSpec, ResearchReport
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
        flows = pattern_flows(profile, production=production, components=components)
        mode = "production" if production else "poc"
        workload = _workload_title(profile)
        semantic = semantic_views(profile, production=production)
        compiler = expected_views(profile, production=production)
        view_mappings = diagram_view_mappings(semantic, workload)
        return ArchitectureSpec(
            session_id=report.session_id,
            mode=mode,
            title=f"{mode.upper()} {workload} Architecture",
            summary=report.recommended_production_direction if production else report.recommended_poc,
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
                "requirement_coverage": _requirement_coverage(profile, components, flows, production=production),
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


def _requirement_coverage(profile, components, flows, production: bool) -> dict[str, list[dict[str, str]]]:
    """Audit how hard profile requirements map into the generated pattern.

    This is intentionally deterministic and advisory. It gives validators and
    export readers a concrete place to see whether important extracted facts were
    carried into the architecture, without letting model-proposed claims alter
    compiler truth.
    """
    capabilities = set(profile.capabilities or [])
    posture = set(profile.deployment_posture or [])
    component_text = " ".join([*(getattr(component, "name", "") for component in components), *(getattr(component, "purpose", "") for component in components)]).lower()
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

    if "computer_vision" in capabilities:
        covered = any(term in body for term in ("video", "image", "vision", "sagemaker", "rekognition", "inference"))
        add(
            "computer_vision_hot_path",
            "Computer vision / imagery processing",
            "covered" if covered else "unmet",
            "Architecture carries an imagery/video inference path." if covered else "Computer-vision requirement was extracted but no imagery/video inference path is explicit.",
        )
    if "real_time_ingestion" in capabilities:
        covered = any(term in body for term in ("stream", "kinesis", "iot", "telemetry", "event"))
        add(
            "real_time_ingestion",
            "Real-time ingestion",
            "covered" if covered else "unmet",
            "Architecture carries a streaming/event ingestion path." if covered else "Real-time ingestion was extracted but no streaming/event path is explicit.",
        )
    if "intermittent_connectivity" in capabilities or {"edge_processing", "hybrid_edge"} & posture:
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
    return {
        "schema": "architecture_requirement_coverage_v1",
        "mode": "production" if production else "poc",
        "requirements": requirements,
    }
