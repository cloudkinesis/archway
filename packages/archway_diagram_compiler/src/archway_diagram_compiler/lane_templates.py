"""Declarative lane templates used by the view planner and LayoutModel builder."""

LANE_TEMPLATES = {
    "web_api": {
        "Ingress and identity": ["edge_identity_controls", "request_path"],
        "Backend": ["private_backend", "service_dependencies", "managed_data", "outputs"],
    },
    "rag": {
        "Ingress and identity": ["edge_identity_controls", "request_path"],
        "Backend and RAG": ["private_backend", "agent_orchestration", "model_invocation", "rag_retrieval", "vector_search", "data_sources"],
    },
    "ai_logical": {
        "Ingress and identity": ["edge_identity_controls", "request_path"],
        "AI application": ["private_backend", "agent_orchestration", "tool_execution", "model_invocation", "rag_retrieval"],
        "Knowledge and controls": ["vector_search", "data_sources", "memory", "ai_governance"],
    },
    "rag_retrieval": {
        "Retrieval runtime": ["agent_orchestration", "rag_retrieval", "vector_search", "data_sources", "model_invocation"],
    },
    "rag_ingestion": {
        "Knowledge ingestion": ["data_sources", "document_ingestion", "document_processing", "embedding_generation", "vector_search"],
    },
    "agent_tool_execution": {
        "Agent execution": ["agent_orchestration", "tool_registry", "tool_execution", "outputs"],
    },
    "agent_memory": {
        "Agent memory": ["agent_orchestration", "prompt_templates", "memory", "managed_data"],
    },
    "ai_governance": {
        "AI security and governance": ["ai_governance", "edge_identity_controls", "controls", "observability"],
    },
    "retail_fulfillment": {
        "Ingress and identity": ["edge_identity_controls", "request_path"],
        "Backend and fulfillment": ["private_backend", "service_dependencies", "fulfillment_flow", "outputs"],
    },
    "event_driven": {
        "Ingress": ["application"],
        "Event processing": ["service_dependencies", "fulfillment_flow", "outputs"],
    },
    "data_pipeline": {
        "Data pipeline": ["application", "service_dependencies", "managed_data", "observability"],
    },
    "data_access": {
        "Application": ["private_backend", "application"],
        "Data services": ["service_dependencies", "managed_data", "outputs"],
    },
    "controls": {
        "Controls": ["edge_identity_controls", "controls"],
        "Observed services": ["request_path", "private_backend", "service_dependencies", "managed_data"],
    },
    "network_private_connectivity": {
        "Regional entry services": ["request_path"],
        "APP-VPC": ["private_backend"],
        "Managed services": ["managed_data", "integration_orchestration", "controls"],
    },
    "semantic_archway": {
        "Archway semantic lanes": [
            "sources_and_edge",
            "telemetry_ingestion",
            "streaming_analytics",
            "prediction_and_scoring",
            "workflow_and_integrations",
            "data_and_model_lifecycle",
            "observability_and_audit",
            "notifications",
            "security",
            "external",
        ],
    },
}


def lane_ids_for_template(template_name: str) -> list:
    template = LANE_TEMPLATES.get(template_name, LANE_TEMPLATES["web_api"])
    lane_ids = []
    for lanes in template.values():
        lane_ids.extend(lanes)
    return lane_ids
