import os
from pathlib import Path

import pytest

from archway_diagram_compiler.compiler import compile_architecture
from archway_diagram_compiler.d2_backend import render_layout_model_to_d2
from archway_diagram_compiler.models import Flow, SemanticArchitectureSpec, ServiceNode
from archway_diagram_compiler.qa import (
    _svg_aspect_ratio,
    _svg_diagonal_connection_count,
    _svg_edge_crosses_node_count,
    _svg_edge_crossing_count,
    _svg_edge_label_overlap_count,
    _svg_node_label_icon_overlap_count,
    _svg_node_overlap_count,
)
from archway_diagram_compiler.renderer import find_d2_executable


AI_FLOW_TYPES = {
    "agent_orchestration",
    "agent_handoff",
    "tool_invocation",
    "model_invocation",
    "rag_retrieval",
    "vector_search",
    "hybrid_search",
    "document_ingestion",
    "document_chunking",
    "embedding_generation",
    "document_embedding",
    "memory_read",
    "memory_write",
    "guardrail_check",
    "evaluation",
    "human_approval",
    "audit_trace",
    "model_observability",
}

MANAGED_AI_SERVICES = {
    "bedrock",
    "bedrock_knowledge_base",
    "bedrock_guardrails",
    "opensearch_serverless",
    "opensearch_vector_index",
    "opensearch_hybrid_search",
    "generic_vector_store",
    "s3",
    "dynamodb",
    "kms",
    "secrets_manager",
    "cloudwatch",
    "cloudtrail",
}


SCENARIO_IDS = [
    "simple_rag_vpc_backend",
    "rag_ingestion_and_runtime",
    "agent_with_tools",
    "agentic_lambda_tool_fanout",
    "agent_memory",
    "guardrails_evaluation_audit",
    "private_bedrock_opensearch",
    "traditional_order_calls_ai",
    "multi_agent_workflow",
    "hybrid_search_rag",
    "ai_async_workflow",
    "unknown_ai_fallback",
]


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_mixed_aws_ai_scenarios(tmp_path, scenario_id):
    _, factory, expected_views, checks = next(item for item in _scenario_factories() if item[0] == scenario_id)
    spec = factory()
    render = _render_enabled()
    bundle = compile_architecture(
        spec,
        Path(tmp_path) / scenario_id,
        render=render,
        render_formats=("svg",),
    )
    view_names = {view.name for view in bundle.views}

    assert bundle.qa_report.passed, scenario_id
    _assert_expected_views(view_names, expected_views, scenario_id)
    _assert_flow_ledger_complete(bundle)
    _assert_ai_flows_accounted(bundle)
    _assert_managed_services_outside_vpc(bundle)
    _assert_no_internal_labels(bundle)

    if "rag_split" in checks:
        _assert_rag_ingestion_and_runtime_are_split(bundle)
    if "rag_runtime" in checks:
        _assert_rag_runtime_view(bundle)
    if "network_endpoints" in checks:
        _assert_network_endpoint_modeling(bundle)
    if "model_separated" in checks:
        _assert_model_invocation_separate_from_retrieval(bundle)
    if "tool_registry_once" in checks:
        _assert_single_layout_node(bundle, "tool_registry")
    if "tool_invocations" in checks:
        _assert_edge_type_count(bundle, "tool_invocation", minimum=2)
    if "tool_fanout" in checks:
        _assert_tool_fanout_summary(bundle, expected_count=12)
    if "memory" in checks:
        _assert_memory_flows(bundle)
    if "governance" in checks:
        _assert_governance_flows(bundle)
    if "traditional_ai_split" in checks:
        _assert_primary_is_not_all_in_one(bundle)
    if "multi_agent" in checks:
        _assert_multi_agent(bundle)
    if "hybrid_search" in checks:
        _assert_hybrid_search(bundle)
    if "async_fanout" in checks:
        _assert_async_fanout(bundle)
    if "fallback" in checks:
        _assert_fallback(bundle)

    if render:
        _assert_rendered_visual_qa(bundle)


def test_human_review_scorecard_template_exists():
    scorecard = Path(__file__).with_name("ai_rag_human_review_scorecard.md")
    assert scorecard.exists()
    text = scorecard.read_text(encoding="utf-8")
    for scenario in [
        "Simple RAG assistant",
        "RAG ingestion + retrieval",
        "Agent with 12 tools",
        "Private Bedrock/OpenSearch access",
        "Traditional order service + AI assistant",
        "Multi-agent workflow",
    ]:
        assert scenario in text


def _render_enabled() -> bool:
    if os.environ.get("RUN_RENDERED_DIAGRAM_TESTS") != "1":
        return False
    return find_d2_executable() is not None


def _assert_expected_views(view_names, expected_views, scenario_id):
    expected = set(expected_views)
    if "security_or_ai_governance" in expected:
        expected.remove("security_or_ai_governance")
        assert {"security_observability_controls", "ai_security_governance_view"} & view_names, scenario_id
    assert expected.issubset(view_names), scenario_id


def _scenario_factories():
    return [
        (
            "simple_rag_vpc_backend",
            _simple_rag_vpc_backend,
            {"production_logical_service_flow", "rag_retrieval_view", "network_private_connectivity"},
            ("rag_runtime", "network_endpoints", "model_separated"),
        ),
        (
            "rag_ingestion_and_runtime",
            _rag_ingestion_and_runtime,
            {"production_logical_service_flow", "rag_retrieval_view", "rag_ingestion_view", "network_private_connectivity"},
            ("rag_split",),
        ),
        (
            "agent_with_tools",
            _agent_with_tools,
            {"production_logical_service_flow", "agent_tool_execution_view"},
            ("tool_registry_once", "tool_invocations"),
        ),
        (
            "agentic_lambda_tool_fanout",
            _agentic_lambda_tool_fanout,
            {"production_logical_service_flow", "agent_tool_execution_view", "fanout_detail_view"},
            ("tool_fanout",),
        ),
        (
            "agent_memory",
            _agent_memory,
            {"agent_memory_view"},
            ("memory",),
        ),
        (
            "guardrails_evaluation_audit",
            _guardrails_evaluation_audit,
            {"production_logical_service_flow", "ai_security_governance_view"},
            ("governance",),
        ),
        (
            "private_bedrock_opensearch",
            _private_bedrock_opensearch,
            {"network_private_connectivity", "rag_retrieval_view", "ai_security_governance_view"},
            ("network_endpoints",),
        ),
        (
            "traditional_order_calls_ai",
            _traditional_order_calls_ai,
            {"production_logical_service_flow", "rag_retrieval_view", "network_private_connectivity", "security_or_ai_governance"},
            ("traditional_ai_split",),
        ),
        (
            "multi_agent_workflow",
            _multi_agent_workflow,
            {"production_logical_service_flow", "agent_tool_execution_view", "agent_memory_view"},
            ("multi_agent",),
        ),
        (
            "hybrid_search_rag",
            _hybrid_search_rag,
            {"rag_retrieval_view"},
            ("hybrid_search",),
        ),
        (
            "ai_async_workflow",
            _ai_async_workflow,
            {"production_logical_service_flow", "async_flow_view", "fanout_detail_view", "network_private_connectivity"},
            ("async_fanout",),
        ),
        (
            "unknown_ai_fallback",
            _unknown_ai_fallback,
            {"production_logical_service_flow"},
            ("fallback",),
        ),
    ]


def _assert_flow_ledger_complete(bundle):
    assert bundle.flow_ledger is not None
    assert {entry.flow_id for entry in bundle.flow_ledger.entries} == {flow.id for flow in bundle.normalized_spec.flows}
    valid_statuses = {"rendered_explicitly", "collapsed_into_group", "rendered_in_another_view", "omitted_with_reason"}
    assert {entry.status for entry in bundle.flow_ledger.entries}.issubset(valid_statuses)


def _assert_ai_flows_accounted(bundle):
    for entry in bundle.flow_ledger.entries:
        if entry.classification in AI_FLOW_TYPES:
            assert entry.status != "omitted_with_reason" or entry.reason


def _assert_managed_services_outside_vpc(bundle):
    for layout in bundle.layout_models:
        for node in layout.nodes:
            if node.service in MANAGED_AI_SERVICES:
                assert node.placement_scope not in {"vpc_resident", "vpc_workload", "vpc_data"}, (layout.view_id, node.id, node.service)


def _assert_no_internal_labels(bundle):
    internal = ["parallel branch", "synthetic", "repair node", "dependency branch"]
    for view in bundle.views:
        text = view.d2_text.lower()
        assert not any(label in text for label in internal), view.name


def _assert_rag_ingestion_and_runtime_are_split(bundle):
    retrieval = _layout(bundle, "rag_retrieval_view")
    ingestion = _layout(bundle, "rag_ingestion_view")
    assert {"rag_retrieval", "vector_search", "source_reference"} & {edge.edge_type for edge in retrieval.edges}
    assert {"document_ingestion", "document_chunking", "document_embedding", "embedding_generation"} & {edge.edge_type for edge in ingestion.edges}


def _assert_rag_runtime_view(bundle):
    retrieval = _layout(bundle, "rag_retrieval_view")
    lanes = {node.lane_id for node in retrieval.nodes}
    assert {"rag_retrieval", "vector_search", "data_sources"} & lanes


def _assert_network_endpoint_modeling(bundle):
    network = _layout(bundle, "network_private_connectivity")
    labels = {node.label for node in network.nodes}
    assert any("endpoint" in label.lower() for label in labels)
    assert any("Bedrock" in label for label in labels)
    _assert_network_endpoints_have_direct_targets(bundle)
    for node in network.nodes:
        if node.service in MANAGED_AI_SERVICES:
            assert node.placement_scope not in {"vpc_resident", "vpc_workload", "vpc_data"}


def _assert_model_invocation_separate_from_retrieval(bundle):
    retrieval = _layout(bundle, "rag_retrieval_view")
    edge_types = {edge.edge_type for edge in retrieval.edges}
    assert "rag_retrieval" in edge_types
    assert "model_invocation" in {entry.classification for entry in bundle.flow_ledger.entries}


def _assert_single_layout_node(bundle, role):
    nodes = [node for layout in bundle.layout_models for node in layout.nodes if node.role == role or node.metadata.get("role") == role]
    assert nodes
    by_view = {}
    for node in nodes:
        by_view.setdefault(node.id, 0)
        by_view[node.id] += 1
    assert len({node.id for node in nodes}) == 1


def test_network_endpoint_targets_are_directly_visible_for_ai_secondary_scenarios(tmp_path):
    expected_targets = {
        "agent_memory": {"Conversation Memory", "Long-Term Memory", "Transcript Archive"},
        "agent_with_tools": {"Tool Registry", "Tool State", "Secrets Manager"},
        "ai_async_workflow": {"Task Queue"},
    }
    for scenario_id, target_labels in expected_targets.items():
        _, factory, _, _ = next(item for item in _scenario_factories() if item[0] == scenario_id)
        bundle = compile_architecture(factory(), Path(tmp_path) / scenario_id, render=False)
        network = _layout(bundle, "network_private_connectivity")
        labels = {node.label for node in network.nodes}

        assert bundle.qa_report.passed, scenario_id
        assert target_labels.issubset(labels), scenario_id
        _assert_network_endpoints_have_direct_targets(bundle)


def test_every_ai_scenario_network_endpoint_has_visible_target(tmp_path):
    for scenario_id, factory, _, _ in _scenario_factories():
        bundle = compile_architecture(factory(), Path(tmp_path) / scenario_id, render=False)

        assert bundle.qa_report.passed, scenario_id
        _assert_network_endpoints_have_direct_targets(bundle)


def test_endpoint_targets_are_emitted_in_network_d2(tmp_path):
    expected_targets = {
        "agent_memory": {"Conversation Memory", "Long-Term Memory", "Transcript Archive"},
        "agent_with_tools": {"Tool State", "Secrets Manager"},
        "ai_async_workflow": {"Task Queue"},
    }
    for scenario_id, target_labels in expected_targets.items():
        _, factory, _, _ = next(item for item in _scenario_factories() if item[0] == scenario_id)
        bundle = compile_architecture(factory(), Path(tmp_path) / scenario_id, render=False)
        network = _layout(bundle, "network_private_connectivity")
        d2 = render_layout_model_to_d2(network)

        for label in target_labels:
            assert label in d2, (scenario_id, label)


def test_endpoint_targets_visible_traditional_ai(tmp_path):
    bundle = compile_architecture(_traditional_order_calls_ai(), Path(tmp_path), render=False)
    network = _layout(bundle, "network_private_connectivity")
    labels = {node.label for node in network.nodes}

    assert bundle.qa_report.passed
    assert {
        "Order Service",
        "Agent Assistant",
        "DynamoDB gateway endpoint",
        "Customers Table",
        "Orders Table",
        "Bedrock interface endpoint",
        "Bedrock Model",
        "OpenSearch interface endpoint",
        "OpenSearch Vector",
        "Secrets Manager interface endpoint",
        "Secrets Manager",
        "CloudWatch Logs interface endpoint",
        "CloudWatch",
    }.issubset(labels)
    _assert_endpoint_direct_targets_include(network, "DynamoDB gateway endpoint", {"Orders Table", "Customers Table"})
    _assert_endpoint_direct_targets_include(network, "Bedrock interface endpoint", {"Bedrock Model"})
    _assert_endpoint_direct_targets_include(network, "OpenSearch interface endpoint", {"OpenSearch Vector"})
    _assert_network_endpoints_have_direct_targets(bundle)


def test_private_rag_network_completeness(tmp_path):
    bundle = compile_architecture(_simple_rag_vpc_backend(), Path(tmp_path), render=False)
    network = _layout(bundle, "network_private_connectivity")
    labels = {node.label for node in network.nodes}

    assert bundle.qa_report.passed
    assert {
        "ECS Assistant",
        "Bedrock interface endpoint",
        "Bedrock Model",
        "Bedrock KB",
        "OpenSearch interface endpoint",
        "OpenSearch Serverless vector index",
        "S3 gateway endpoint",
        "Document Bucket",
        "CloudWatch Logs interface endpoint",
        "CloudWatch",
    }.issubset(labels)
    _assert_endpoint_direct_targets_include(network, "Bedrock interface endpoint", {"Bedrock Model", "Bedrock KB"})
    _assert_endpoint_direct_targets_include(network, "OpenSearch interface endpoint", {"OpenSearch Serverless vector index"})
    _assert_endpoint_direct_targets_include(network, "S3 gateway endpoint", {"Document Bucket"})
    _assert_network_endpoints_have_direct_targets(bundle)


def test_simple_rag_primary_summarization(tmp_path):
    bundle = compile_architecture(_simple_rag_vpc_backend(), Path(tmp_path), render=False)
    production = _layout(bundle, "production_logical_service_flow")
    labels = {node.label for node in production.nodes}
    node_ids = {node.id for node in production.nodes}

    assert bundle.qa_report.passed
    assert "RAG subsystem" in labels
    assert {"kb", "vector", "docs"}.isdisjoint(node_ids)
    _layout(bundle, "rag_retrieval_view")


def test_guardrails_primary_view_uses_semantic_chain_lane_labels(tmp_path):
    _, factory, _, _ = next(item for item in _scenario_factories() if item[0] == "guardrails_evaluation_audit")
    bundle = compile_architecture(factory(), Path(tmp_path), render=False)
    logical = _layout(bundle, "production_logical_service_flow")
    labels = {lane.label for lane in logical.lanes}
    d2 = next(view.d2_text for view in bundle.views if view.name == "production_logical_service_flow")

    assert bundle.qa_report.passed
    assert {"Governance workflow", "Evaluation and audit"}.issubset(labels)
    for forbidden in ["Flow section 1", "Flow section 2", "Stage 1", "Stage 2", "Workflow segment 1", "Workflow segment 2"]:
        assert forbidden not in d2


def _assert_network_endpoints_have_direct_targets(bundle):
    explanations = bundle.artifact_paths.get("placement_explanations")
    explanation_text = explanations.read_text(encoding="utf-8") if explanations and explanations.exists() else ""
    for layout in bundle.layout_models:
        if layout.view_id != "network_private_connectivity":
            continue
        nodes_by_id = {node.id: node for node in layout.nodes}
        for endpoint in [node for node in layout.nodes if node.service == "vpc_endpoint"]:
            has_direct_target = any(
                edge.source == endpoint.id
                and edge.target in nodes_by_id
                and nodes_by_id[edge.target].service not in {"vpc_endpoint", "vpc_link", "semantic_group"}
                and not nodes_by_id[edge.target].is_virtual
                for edge in layout.edges
            )
            assert has_direct_target or endpoint.id in explanation_text, (layout.view_id, endpoint.id, endpoint.label)


def _assert_endpoint_direct_targets_include(layout, endpoint_label, expected_target_labels):
    nodes_by_id = {node.id: node for node in layout.nodes}
    endpoint_ids = {node.id for node in layout.nodes if node.label == endpoint_label}
    target_labels = {
        nodes_by_id[edge.target].label
        for edge in layout.edges
        if edge.source in endpoint_ids
        and edge.target in nodes_by_id
        and nodes_by_id[edge.target].service not in {"vpc_endpoint", "vpc_link", "semantic_group"}
    }
    assert expected_target_labels.issubset(target_labels), (endpoint_label, target_labels)


def _assert_edge_type_count(bundle, edge_type, minimum):
    assert sum(1 for entry in bundle.flow_ledger.entries if entry.classification == edge_type) >= minimum


def _assert_tool_fanout_summary(bundle, expected_count):
    primary = _layout(bundle, "production_logical_service_flow")
    assert any(f"tools ×{expected_count}" in node.label.lower() for node in primary.nodes)
    tool_entries = [entry for entry in bundle.flow_ledger.entries if entry.classification == "tool_invocation"]
    assert len(tool_entries) == expected_count
    assert {entry.status for entry in tool_entries} == {"collapsed_into_group"}
    assert all(entry.group_id for entry in tool_entries)
    assert {entry.view_id for entry in tool_entries} <= {"production_logical_service_flow", "ai_logical_service_flow", "agent_tool_execution_view", "fanout_detail_view"}
    assert len([edge for edge in primary.edges if edge.edge_type == "tool_invocation"]) <= 1


def _assert_memory_flows(bundle):
    classifications = {entry.classification for entry in bundle.flow_ledger.entries}
    assert {"memory_read", "memory_write"} <= classifications
    _layout(bundle, "agent_memory_view")


def _assert_governance_flows(bundle):
    classifications = {entry.classification for entry in bundle.flow_ledger.entries}
    assert {"guardrail_check", "evaluation"} & classifications
    assert {"audit_trace", "model_observability", "audit", "observability"} & classifications
    _layout(bundle, "ai_security_governance_view")


def _assert_primary_is_not_all_in_one(bundle):
    primary = _layout(bundle, "production_logical_service_flow")
    assert len(primary.nodes) <= 24
    assert len(primary.edges) <= 24
    _layout(bundle, "rag_retrieval_view")


def _assert_multi_agent(bundle):
    classifications = {entry.classification for entry in bundle.flow_ledger.entries}
    assert "agent_handoff" in classifications
    assert "human_approval" in classifications
    _assert_single_layout_node(bundle, "tool_registry")
    _assert_single_layout_node(bundle, "conversation_memory")


def _assert_hybrid_search(bundle):
    retrieval = _layout(bundle, "rag_retrieval_view")
    assert any("hybrid search index" in node.label.lower() for node in retrieval.nodes)
    assert {"hybrid_search", "model_invocation"} <= {entry.classification for entry in bundle.flow_ledger.entries}


def _assert_async_fanout(bundle):
    assert "fanout_detail_view" in {view.name for view in bundle.views}
    primary = _layout(bundle, "production_logical_service_flow")
    assert any("lambda workers ×12" in node.label.lower() for node in primary.nodes)
    assert "async_flow_view" in {view.name for view in bundle.views}


def _assert_fallback(bundle):
    assert any(diagnostic.code == "aws_service_catalog_fallback" for diagnostic in bundle.diagnostics)
    assert bundle.flow_ledger is not None
    categories = {node.id: node.category for node in bundle.normalized_spec.nodes}
    if "llm" in categories:
        assert categories["llm"] == "external_ai_service"
    if "vector" in categories:
        assert categories["vector"] == "custom_vector_store"
    if "eval" in categories:
        assert categories["eval"] == "evaluation_service"
    if "madeup" in categories:
        assert categories["madeup"] == "custom_ai_service"


def _assert_rendered_visual_qa(bundle):
    for view in bundle.views:
        svg_path = view.artifact_paths.get("svg")
        if svg_path is None:
            continue
        aspect_ratio = _svg_aspect_ratio(svg_path)
        assert aspect_ratio is None or 0.35 <= aspect_ratio <= 3.5, view.name
        assert _svg_diagonal_connection_count(svg_path) == 0, view.name
        assert _svg_node_overlap_count(svg_path) == 0, view.name
        assert _svg_edge_label_overlap_count(svg_path) == 0, view.name
        assert _svg_node_label_icon_overlap_count(svg_path) == 0, view.name
        assert _svg_edge_crosses_node_count(svg_path) == 0, view.name
        crossings = _svg_edge_crossing_count(svg_path)
        if crossings is None:
            continue
        if view.name in {"production_logical_service_flow", "ai_logical_service_flow"}:
            assert crossings <= 8, view.name
        elif view.name == "network_private_connectivity":
            assert crossings <= 32, view.name


def _layout(bundle, view_id):
    return next(layout for layout in bundle.layout_models if layout.view_id == view_id)


def _simple_rag_vpc_backend():
    return SemanticArchitectureSpec(
        title="Simple RAG Assistant With VPC Backend",
        nodes=[
            ServiceNode(id="cloudfront", name="CloudFront", service="cloudfront", region="global"),
            ServiceNode(id="api", name="Assistant API", service="api_gateway", region="us-east-1"),
            ServiceNode(id="assistant", name="ECS Assistant", service="ecs", region="us-east-1", vpc_id="rag-vpc", metadata={"role": "agent_runtime"}),
            ServiceNode(id="kb", name="Bedrock KB", service="bedrock_knowledge_base", region="us-east-1", metadata={"role": "retrieval_layer"}),
            ServiceNode(id="vector", name="Vector Index", service="opensearch_vector_index", region="us-east-1", metadata={"role": "vector_index"}),
            ServiceNode(id="docs", name="Document Bucket", service="s3", region="us-east-1", metadata={"role": "source_documents"}),
            ServiceNode(id="model", name="Bedrock Model", service="bedrock", region="us-east-1", metadata={"role": "foundation_model"}),
            ServiceNode(id="cloudwatch", name="CloudWatch", service="cloudwatch", region="us-east-1"),
        ],
        flows=[
            Flow(id="f1", source="cloudfront", target="api", label="HTTPS"),
            Flow(id="f2", source="api", target="assistant", label="private integration"),
            Flow(id="f3", source="assistant", target="kb", label="RAG retrieval", metadata={"endpoint": "bedrock_interface_endpoint"}),
            Flow(id="f4", source="kb", target="vector", label="vector search"),
            Flow(id="f5", source="vector", target="docs", label="source references"),
            Flow(id="f6", source="assistant", target="model", label="invoke model", metadata={"endpoint": "bedrock_interface_endpoint"}),
            Flow(id="f7", source="assistant", target="cloudwatch", label="logs and metrics", metadata={"endpoint": "cloudwatch_logs_interface_endpoint"}),
        ],
        metadata={"internet_facing": True, "vpcs": [{"id": "rag-vpc", "name": "RAG VPC", "region": "us-east-1"}]},
    )


def _rag_ingestion_and_runtime():
    spec = _simple_rag_vpc_backend()
    nodes = [
        *spec.nodes,
        ServiceNode(id="chunker", name="Chunking Job", service="lambda", region="us-east-1", metadata={"role": "document_chunker"}),
        ServiceNode(id="embedder", name="Embedding Model", service="bedrock", region="us-east-1", metadata={"role": "embedding_model"}),
    ]
    flows = [
        *spec.flows,
        Flow(id="f8", source="docs", target="chunker", label="chunk documents"),
        Flow(id="f9", source="chunker", target="embedder", label="document embedding"),
        Flow(id="f10", source="embedder", target="vector", label="store embedding"),
    ]
    return SemanticArchitectureSpec(title="RAG Ingestion And Runtime", nodes=nodes, flows=flows, metadata=spec.metadata)


def _agent_with_tools():
    return SemanticArchitectureSpec(
        title="Agent With Tools",
        nodes=[
            ServiceNode(id="user", name="User", service="external_actor"),
            ServiceNode(id="api", name="Agent API", service="api_gateway", region="us-east-1"),
            ServiceNode(id="agent", name="Agent Runtime", service="ecs", region="us-east-1", vpc_id="agent-vpc", metadata={"role": "agent_runtime"}),
            ServiceNode(id="registry", name="Tool Registry", service="dynamodb", region="us-east-1", metadata={"role": "tool_registry"}),
            ServiceNode(id="tool1", name="Lambda Tool 1", service="lambda", region="us-east-1", metadata={"role": "lambda_tool"}),
            ServiceNode(id="tool2", name="Lambda Tool 2", service="lambda", region="us-east-1", metadata={"role": "lambda_tool"}),
            ServiceNode(id="table", name="Tool State", service="dynamodb", region="us-east-1"),
            ServiceNode(id="bucket", name="Tool Bucket", service="s3", region="us-east-1"),
            ServiceNode(id="external", name="External API", service="external_actor", metadata={"role": "external_tool"}),
            ServiceNode(id="secrets", name="Secrets Manager", service="secrets_manager", region="us-east-1"),
        ],
        flows=[
            Flow(id="f1", source="user", target="api", label="request"),
            Flow(id="f2", source="api", target="agent", label="private integration"),
            Flow(id="f3", source="agent", target="registry", label="tool lookup"),
            Flow(id="f4", source="agent", target="tool1", label="invoke tool"),
            Flow(id="f5", source="agent", target="tool2", label="invoke tool"),
            Flow(id="f6", source="tool1", target="table", label="write data"),
            Flow(id="f7", source="tool2", target="bucket", label="store object"),
            Flow(id="f8", source="tool2", target="external", label="call external tool"),
            Flow(id="f9", source="agent", target="secrets", label="read secret", metadata={"endpoint": "secrets_manager_interface_endpoint"}),
        ],
        metadata={"internet_facing": False, "expected_views": ["ai_logical_service_flow"]},
    )


def _agentic_lambda_tool_fanout():
    return SemanticArchitectureSpec(
        title="Agentic Lambda Tool Fanout",
        nodes=[
            ServiceNode(id="agent", name="Agent Orchestrator", service="bedrock_agent", region="us-east-1", metadata={"role": "agent_orchestrator"}),
            *[
                ServiceNode(id=f"tool_{index}", name=f"Lambda Tool {index}", service="lambda", region="us-east-1", metadata={"role": "lambda_tool"})
                for index in range(12)
            ],
        ],
        flows=[
            Flow(id=f"tool_flow_{index}", source="agent", target=f"tool_{index}", label="invoke tool")
            for index in range(12)
        ],
        metadata={"internet_facing": False},
    )


def _agent_memory():
    return SemanticArchitectureSpec(
        title="Agent Memory",
        nodes=[
            ServiceNode(id="agent", name="Agent Runtime", service="ecs", region="us-east-1", vpc_id="memory-vpc", metadata={"role": "agent_runtime"}),
            ServiceNode(id="conversation", name="Conversation Memory", service="dynamodb", region="us-east-1", metadata={"role": "conversation_memory"}),
            ServiceNode(id="longterm", name="Long-Term Memory", service="opensearch_vector_index", region="us-east-1", metadata={"role": "long_term_memory"}),
            ServiceNode(id="archive", name="Transcript Archive", service="s3", region="us-east-1", metadata={"role": "document_store"}),
        ],
        flows=[
            Flow(id="f1", source="agent", target="conversation", label="memory write", metadata={"endpoint": "dynamodb_gateway_endpoint"}),
            Flow(id="f2", source="agent", target="longterm", label="memory read", metadata={"endpoint": "opensearch_interface_endpoint"}),
            Flow(id="f3", source="agent", target="archive", label="memory write", metadata={"endpoint": "s3_gateway_endpoint"}),
        ],
        metadata={"internet_facing": False},
    )


def _guardrails_evaluation_audit():
    return SemanticArchitectureSpec(
        title="Guardrails Evaluation Audit",
        nodes=[
            ServiceNode(id="user", name="User", service="external_actor"),
            ServiceNode(id="agent", name="Agent Runtime", service="bedrock_agent", region="us-east-1", metadata={"role": "agent_orchestrator"}),
            ServiceNode(id="guardrails", name="Bedrock Guardrails", service="bedrock_guardrails", region="us-east-1", metadata={"role": "guardrails"}),
            ServiceNode(id="model", name="Bedrock Model", service="bedrock", region="us-east-1", metadata={"role": "foundation_model"}),
            ServiceNode(id="eval", name="Evaluation Runner", service="lambda", region="us-east-1", metadata={"role": "eval_runner"}),
            ServiceNode(id="audit", name="Audit Store", service="s3", region="us-east-1", metadata={"role": "audit_store"}),
            ServiceNode(id="cloudwatch", name="CloudWatch", service="cloudwatch", region="us-east-1"),
            ServiceNode(id="cloudtrail", name="CloudTrail", service="cloudtrail", region="us-east-1"),
            ServiceNode(id="kms", name="KMS", service="kms", region="us-east-1"),
        ],
        flows=[
            Flow(id="f1", source="user", target="agent", label="request"),
            Flow(id="f2", source="agent", target="guardrails", label="guardrail check"),
            Flow(id="f3", source="guardrails", target="model", label="invoke model"),
            Flow(id="f4", source="model", target="eval", label="evaluation"),
            Flow(id="f5", source="eval", target="audit", label="audit trace"),
            Flow(id="f6", source="eval", target="cloudwatch", label="model observability"),
            Flow(id="f7", source="cloudtrail", target="audit", label="audit events"),
            Flow(id="f8", source="audit", target="kms", label="encrypt objects"),
        ],
        metadata={"internet_facing": False},
    )


def _private_bedrock_opensearch():
    return SemanticArchitectureSpec(
        title="Private Bedrock OpenSearch",
        nodes=[
            ServiceNode(id="assistant", name="ECS Assistant", service="ecs", region="us-east-1", vpc_id="ai-vpc", metadata={"role": "agent_runtime"}),
            ServiceNode(id="bedrock", name="Bedrock Model", service="bedrock", region="us-east-1", metadata={"role": "foundation_model"}),
            ServiceNode(id="kb", name="Bedrock KB", service="bedrock_knowledge_base", region="us-east-1", metadata={"role": "retrieval_layer"}),
            ServiceNode(id="vector", name="OpenSearch Vector", service="opensearch_vector_index", region="us-east-1", metadata={"role": "vector_index"}),
            ServiceNode(id="docs", name="Document Bucket", service="s3", region="us-east-1", metadata={"role": "source_documents"}),
            ServiceNode(id="secrets", name="Secrets Manager", service="secrets_manager", region="us-east-1"),
            ServiceNode(id="cloudwatch", name="CloudWatch", service="cloudwatch", region="us-east-1"),
        ],
        flows=[
            Flow(id="f1", source="assistant", target="bedrock", label="invoke model", metadata={"endpoint": "bedrock_interface_endpoint"}),
            Flow(id="f2", source="assistant", target="kb", label="RAG retrieval", metadata={"endpoint": "bedrock_interface_endpoint"}),
            Flow(id="f3", source="kb", target="vector", label="vector search"),
            Flow(id="f4", source="vector", target="docs", label="source references"),
            Flow(id="f5", source="assistant", target="secrets", label="read secret", metadata={"endpoint": "secrets_manager_interface_endpoint"}),
            Flow(id="f6", source="assistant", target="cloudwatch", label="logs and metrics", metadata={"endpoint": "cloudwatch_logs_interface_endpoint"}),
            Flow(id="f7", source="assistant", target="docs", label="read documents", metadata={"endpoint": "s3_gateway_endpoint"}),
        ],
        metadata={"internet_facing": False, "vpcs": [{"id": "ai-vpc", "name": "AI VPC", "region": "us-east-1"}]},
    )


def _traditional_order_calls_ai():
    return SemanticArchitectureSpec(
        title="Traditional Order Service Calls AI",
        nodes=[
            ServiceNode(id="cloudfront", name="CloudFront", service="cloudfront", region="global"),
            ServiceNode(id="api", name="Order API", service="api_gateway", region="us-east-1"),
            ServiceNode(id="order", name="Order Service", service="ecs", region="us-east-1", vpc_id="order-vpc"),
            ServiceNode(id="assistant", name="Agent Assistant", service="ecs", region="us-east-1", vpc_id="order-vpc", metadata={"role": "agent_runtime"}),
            ServiceNode(id="bedrock", name="Bedrock Model", service="bedrock", region="us-east-1", metadata={"role": "foundation_model"}),
            ServiceNode(id="vector", name="OpenSearch Vector", service="opensearch_vector_index", region="us-east-1", metadata={"role": "vector_index"}),
            ServiceNode(id="orders", name="Orders Table", service="dynamodb", region="us-east-1"),
            ServiceNode(id="customers", name="Customers Table", service="dynamodb", region="us-east-1"),
            ServiceNode(id="docs", name="Document Bucket", service="s3", region="us-east-1", metadata={"role": "source_documents"}),
            ServiceNode(id="secrets", name="Secrets Manager", service="secrets_manager", region="us-east-1"),
            ServiceNode(id="cloudwatch", name="CloudWatch", service="cloudwatch", region="us-east-1"),
        ],
        flows=[
            Flow(id="f1", source="cloudfront", target="api", label="HTTPS"),
            Flow(id="f2", source="api", target="order", label="private integration"),
            Flow(id="f3", source="order", target="assistant", label="ask assistant"),
            Flow(id="f4", source="assistant", target="bedrock", label="invoke model", metadata={"endpoint": "bedrock_interface_endpoint"}),
            Flow(id="f5", source="assistant", target="vector", label="vector search", metadata={"endpoint": "opensearch_interface_endpoint"}),
            Flow(id="f6", source="vector", target="docs", label="source references"),
            Flow(id="f7", source="order", target="orders", label="write order", metadata={"endpoint": "dynamodb_gateway_endpoint"}),
            Flow(id="f8", source="order", target="customers", label="read customer", metadata={"endpoint": "dynamodb_gateway_endpoint"}),
            Flow(id="f9", source="order", target="secrets", label="read secret", metadata={"endpoint": "secrets_manager_interface_endpoint"}),
            Flow(id="f10", source="order", target="cloudwatch", label="logs and metrics", metadata={"endpoint": "cloudwatch_logs_interface_endpoint"}),
        ],
        metadata={"internet_facing": True, "vpcs": [{"id": "order-vpc", "name": "Order VPC", "region": "us-east-1"}]},
    )


def _multi_agent_workflow():
    return SemanticArchitectureSpec(
        title="Multi-Agent Workflow",
        nodes=[
            ServiceNode(id="planner", name="Planner Agent", service="bedrock_agent", region="us-east-1", metadata={"role": "planner_agent"}),
            ServiceNode(id="research", name="Research Agent", service="bedrock_agent", region="us-east-1", metadata={"role": "worker_agent"}),
            ServiceNode(id="summarizer", name="Summarizer Agent", service="bedrock_agent", region="us-east-1", metadata={"role": "worker_agent"}),
            ServiceNode(id="reviewer", name="Reviewer Agent", service="bedrock_agent", region="us-east-1", metadata={"role": "reviewer_agent"}),
            ServiceNode(id="approval", name="Human Approval", service="external_actor", metadata={"role": "human_approval"}),
            ServiceNode(id="response", name="Final Response", service="external_actor", metadata={"role": "response"}),
            ServiceNode(id="registry", name="Shared Tool Registry", service="dynamodb", region="us-east-1", metadata={"role": "tool_registry"}),
            ServiceNode(id="tool", name="Research Tool", service="lambda", region="us-east-1", metadata={"role": "lambda_tool"}),
            ServiceNode(id="model", name="Bedrock Model", service="bedrock", region="us-east-1", metadata={"role": "foundation_model"}),
            ServiceNode(id="memory", name="Shared Memory", service="dynamodb", region="us-east-1", metadata={"role": "conversation_memory"}),
        ],
        flows=[
            Flow(id="f1", source="planner", target="research", label="agent handoff"),
            Flow(id="f2", source="research", target="summarizer", label="agent handoff"),
            Flow(id="f3", source="summarizer", target="reviewer", label="agent handoff"),
            Flow(id="f4", source="reviewer", target="approval", label="human approval"),
            Flow(id="f5", source="approval", target="response", label="final response"),
            Flow(id="f6", source="planner", target="registry", label="tool lookup"),
            Flow(id="f7", source="research", target="tool", label="invoke tool"),
            Flow(id="f8", source="summarizer", target="model", label="invoke model"),
            Flow(id="f9", source="reviewer", target="memory", label="memory write"),
            Flow(id="f10", source="planner", target="memory", label="memory read"),
        ],
        metadata={"internet_facing": False},
    )


def _hybrid_search_rag():
    return SemanticArchitectureSpec(
        title="Hybrid Search RAG",
        nodes=[
            ServiceNode(id="assistant", name="Assistant Service", service="lambda", region="us-east-1"),
            ServiceNode(id="hybrid", name="Hybrid Search", service="opensearch_hybrid_search", region="us-east-1", metadata={"role": "hybrid_search_index"}),
            ServiceNode(id="docs", name="S3 Document Store", service="s3", region="us-east-1", metadata={"role": "source_documents"}),
            ServiceNode(id="model", name="Bedrock Model", service="bedrock", region="us-east-1", metadata={"role": "foundation_model"}),
        ],
        flows=[
            Flow(id="f1", source="assistant", target="hybrid", label="hybrid search"),
            Flow(id="f2", source="hybrid", target="docs", label="source references"),
            Flow(id="f3", source="assistant", target="model", label="invoke model"),
        ],
        metadata={"internet_facing": False},
    )


def _ai_async_workflow():
    return SemanticArchitectureSpec(
        title="AI Async Workflow",
        nodes=[
            ServiceNode(id="api", name="Task API", service="api_gateway", region="us-east-1"),
            ServiceNode(id="agent", name="Agent Runtime", service="ecs", region="us-east-1", vpc_id="async-vpc", metadata={"role": "agent_runtime"}),
            ServiceNode(id="queue", name="Task Queue", service="sqs", region="us-east-1"),
            ServiceNode(id="workflow", name="Step Functions Workflow", service="step_functions", region="us-east-1"),
            *[
                ServiceNode(id=f"worker_{index}", name=f"Lambda Worker {index}", service="lambda", region="us-east-1")
                for index in range(12)
            ],
            ServiceNode(id="model", name="Bedrock Model", service="bedrock", region="us-east-1", metadata={"role": "foundation_model"}),
            ServiceNode(id="results", name="Result Bucket", service="s3", region="us-east-1"),
        ],
        flows=[
            Flow(id="f1", source="api", target="agent", label="private integration"),
            Flow(id="f2", source="agent", target="queue", label="enqueue task", metadata={"endpoint": "sqs_interface_endpoint"}),
            Flow(id="f3", source="queue", target="workflow", label="start workflow"),
            *[
                Flow(id=f"worker_flow_{index}", source="workflow", target=f"worker_{index}", label="invoke worker", edge_type="async")
                for index in range(12)
            ],
            Flow(id="f4", source="workflow", target="model", label="invoke model"),
            Flow(id="f5", source="workflow", target="results", label="store result"),
        ],
        metadata={"internet_facing": False, "vpcs": [{"id": "async-vpc", "name": "Async VPC", "region": "us-east-1"}]},
    )


def _unknown_ai_fallback():
    return SemanticArchitectureSpec(
        title="Unknown AI Fallback",
        nodes=[
            ServiceNode(id="agent", name="Agent Runtime", service="agent_runtime", region="us-east-1"),
            ServiceNode(id="vector", name="Custom Vector Store", service="custom_vector_store", region="us-east-1"),
            ServiceNode(id="eval", name="Custom Eval Service", service="custom_eval_service", region="us-east-1"),
            ServiceNode(id="llm", name="Third Party LLM", service="third_party_llm_endpoint", region="us-east-1"),
            ServiceNode(id="madeup", name="Made Up AI Service", service="made_up_ai_service", region="us-east-1"),
        ],
        flows=[
            Flow(id="f1", source="agent", target="vector", label="vector search"),
            Flow(id="f2", source="agent", target="eval", label="evaluation"),
            Flow(id="f3", source="agent", target="llm", label="invoke model"),
            Flow(id="f4", source="agent", target="madeup", label="use AI service"),
        ],
        metadata={"internet_facing": False},
    )
