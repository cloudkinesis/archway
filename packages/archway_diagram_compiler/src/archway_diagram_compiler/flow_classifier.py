"""Deterministic flow classification."""

from archway_diagram_compiler.models import Flow, FlowClassification, ServiceNode
from archway_diagram_compiler.provider_catalog import ProviderCatalog


def classify_flow(
    flow: Flow,
    source_node: ServiceNode,
    target_node: ServiceNode,
    provider_catalog: ProviderCatalog,
) -> FlowClassification:
    if flow.edge_type:
        return FlowClassification(flow_id=flow.id, edge_type=flow.edge_type, reason="edge_type supplied by input")

    metadata_type = flow.metadata.get("edge_type") or flow.metadata.get("classification")
    if metadata_type:
        mapped = _map_legacy_classification(str(metadata_type), flow, source_node, target_node)
        return FlowClassification(flow_id=flow.id, edge_type=mapped, reason="edge type inferred from flow metadata")

    source = source_node.service
    target = target_node.service
    label = (flow.label or "").lower()
    source_role = _role(source_node)
    target_role = _role(target_node)

    if flow.metadata.get("endpoint_access_path") and source == "vpc_endpoint":
        if "memory" in label:
            edge_type = "memory_write" if any(token in label for token in ("write", "store", "save", "persist")) else "memory_read"
        elif "model observability" in label:
            edge_type = "model_observability"
        elif target == "secrets_manager" or "secret" in label:
            edge_type = "secret_access"
        elif target == "kms" or "encrypt" in label or "decrypt" in label:
            edge_type = "encryption"
        elif target in {"bedrock", "bedrock_agent", "bedrock_agentcore", "sagemaker"}:
            edge_type = "model_invocation"
        elif target in {"bedrock_knowledge_base"}:
            edge_type = "rag_retrieval"
        elif target in {"opensearch_serverless", "opensearch_vector_index", "opensearch_hybrid_search", "generic_vector_store"}:
            edge_type = "hybrid_search" if target == "opensearch_hybrid_search" or "hybrid" in label else "vector_search"
        else:
            edge_type = "vpc_endpoint_access"
    elif flow.metadata.get("endpoint_access_path") or source == "vpc_endpoint" or target == "vpc_endpoint":
        edge_type = "vpc_endpoint_access"
    elif flow.metadata.get("integration") == "vpc_link" or target == "vpc_link":
        edge_type = "private_integration"
    elif target_role == "human_approval" or "human approval" in label or "approval" in label:
        edge_type = "human_approval"
    elif target in {"bedrock_guardrails"} or target_role == "guardrails" or "guardrail" in label:
        edge_type = "guardrail_check"
    elif target_role in {"evaluation_runner", "eval_runner"} or source_role in {"evaluation_runner", "eval_runner"} or "evaluation" in label or "evaluate" in label:
        edge_type = "evaluation"
    elif target_role in {"tool_registry", "tool_executor", "lambda_tool", "ecs_tool", "external_tool"} or "tool" in label:
        edge_type = "tool_invocation"
    elif source_role in {"agent_runtime", "agent_orchestrator", "planner_agent", "worker_agent", "reviewer_agent"} and target_role in {"agent_runtime", "agent_orchestrator", "planner_agent", "worker_agent", "reviewer_agent"}:
        edge_type = "agent_handoff" if source_role != target_role else "agent_orchestration"
    elif source_role in {"agent_runtime", "agent_orchestrator"} and target_role in {"planner_agent", "worker_agent", "reviewer_agent"}:
        edge_type = "agent_orchestration"
    elif target_role in {"conversation_memory", "short_term_memory", "long_term_memory"} or "memory" in label:
        edge_type = "memory_write" if any(token in label for token in ("write", "store", "save", "persist")) else "memory_read"
    elif target_role == "prompt_template_store" or "prompt" in label:
        edge_type = "prompt_lookup"
    elif target_role in {"chunking_job", "document_chunker"} or "chunk" in label:
        edge_type = "document_chunking"
    elif target_role in {"embedding_job", "embedding_model"} or "embedding" in label:
        edge_type = "document_embedding" if any(token in label for token in ("document", "index", "store")) else "embedding_generation"
    elif target_role in {"ingestion_pipeline", "document_ingestion", "document_store"} and any(token in label for token in ("ingest", "load", "document")):
        edge_type = "document_ingestion"
    elif target_role in {"opensearch_hybrid_search", "hybrid_search_index"} or target == "opensearch_hybrid_search" or "hybrid search" in label:
        edge_type = "hybrid_search"
    elif target_role in {"vector_index", "opensearch_vector_index", "opensearch_hybrid_search"} or target in {"opensearch_vector_index", "opensearch_hybrid_search", "generic_vector_store"} or "vector search" in label:
        edge_type = "vector_search"
    elif target_role in {"log_analytics_index", "audit_store"} or target == "opensearch_log_analytics_index" or "trace" in label:
        edge_type = "audit_trace"
    elif target_role in {"application_search_index"} or target == "opensearch_application_search_index":
        edge_type = "data_read"
    elif target_role in {"observability_sink"} or "model observability" in label:
        edge_type = "model_observability"
    elif "source reference" in label or "source references" in label:
        edge_type = "source_reference"
    elif target == "cognito" or source == "cognito" or "jwt" in label or "sign in" in label:
        edge_type = "auth"
    elif target == "secrets_manager" or "secret" in label:
        edge_type = "secret_access"
    elif target == "kms" or source == "kms" or "encrypt" in label or "decrypt" in label:
        edge_type = "encryption"
    elif metadata_type in {"media_delivery", "media_rights", "media_ad_decision", "media_qoe"}:
        edge_type = str(metadata_type)
    elif target in {"medialive", "mediapackage"} or source in {"medialive", "mediapackage"} and target == "cloudfront":
        edge_type = "media_delivery"
    elif target in {"lambda_edge", "cloudfront_functions"} or source in {"lambda_edge", "cloudfront_functions"}:
        edge_type = "media_rights"
    elif target == "mediatailor" or source == "mediatailor" or "ad decision" in label:
        edge_type = "media_ad_decision"
    elif "qoe" in label or "playback" in label or "rebuffer" in label or "startup" in label:
        edge_type = "media_qoe"
    elif target == "cloudwatch" or "logs" in label or "metrics" in label:
        edge_type = "observability"
    elif target == "cloudtrail" or source == "cloudtrail" or "audit" in label:
        edge_type = "audit"
    elif target in {"sqs", "step_functions"}:
        edge_type = "async"
    elif target == "eventbridge" or source == "eventbridge":
        edge_type = "event"
    elif target == "sns":
        edge_type = "notification"
    elif target == "bedrock_knowledge_base" or target_role in {"bedrock_knowledge_base", "retrieval_layer"} or "rag" in label or "retrieve" in label:
        edge_type = "rag_retrieval"
    elif target in {"bedrock", "bedrock_agent", "bedrock_agentcore", "sagemaker"} or target_role in {"model_endpoint", "foundation_model"}:
        edge_type = "model_invocation"
    elif target in {"dynamodb", "s3", "opensearch_serverless", "opensearch_vector_index", "opensearch_hybrid_search", "opensearch_domain", "generic_vector_store"}:
        edge_type = "data_write" if any(token in label for token in ("write", "store", "reserve", "put")) else "data_read"
    elif source in {"cloudfront", "api_gateway", "alb", "nlb", "load_balancer", "vpc_link"}:
        edge_type = "request"
    else:
        edge_type = "request"

    return FlowClassification(flow_id=flow.id, edge_type=edge_type, reason="edge type inferred from services and label")


def _role(node: ServiceNode) -> str:
    return str(node.metadata.get("role") or node.metadata.get("ai_role") or node.category or node.service)


def _map_legacy_classification(
    classification: str,
    flow: Flow,
    source_node: ServiceNode,
    target_node: ServiceNode,
) -> str:
    if classification == "data":
        label = (flow.label or "").lower()
        if target_node.service in {"dynamodb", "s3", "opensearch_serverless"}:
            return "data_write" if any(token in label for token in ("write", "store", "reserve", "put")) else "data_read"
        return "request"
    if classification == "auth":
        if target_node.service == "secrets_manager":
            return "secret_access"
        if target_node.service == "kms":
            return "encryption"
        return "auth"
    if classification == "audit":
        return "observability" if target_node.service == "cloudwatch" else "audit"
    if classification in {"async", "event", "notification", "control", "media_delivery", "media_rights", "media_ad_decision", "media_qoe"}:
        return classification
    return "request"
