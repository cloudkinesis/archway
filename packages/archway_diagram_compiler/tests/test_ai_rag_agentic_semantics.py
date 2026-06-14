from pathlib import Path
import json
import re

from archway_diagram_compiler.compiler import compile_architecture
from archway_diagram_compiler.flow_classifier import classify_flow
from archway_diagram_compiler.models import Flow, SemanticArchitectureSpec, ServiceNode
from archway_diagram_compiler.normalizer import normalize_spec
from archway_diagram_compiler.providers import get_provider_catalog
from archway_diagram_compiler.qa import _svg_edge_crossing_count, _svg_edge_label_overlap_count
from archway_diagram_compiler.renderer import find_d2_executable
from examples.retail_order_fulfillment import retail_order_fulfillment_spec


def test_ai_catalog_aliases_and_flow_classification():
    spec = SemanticArchitectureSpec(
        title="AI aliases",
        nodes=[
            ServiceNode(id="agent", name="Agent", service="bedrock agent", region="us-east-1"),
            ServiceNode(id="kb", name="KB", service="bedrock kb", region="us-east-1"),
        ServiceNode(id="vector", name="Vector", service="opensearch vector index", region="us-east-1"),
        ServiceNode(id="short", name="Short KB", service="kb", region="us-east-1"),
        ServiceNode(id="generic_vector", name="Generic Vector", service="generic vector store", region="us-east-1"),
        ServiceNode(id="logs", name="Log Search", service="opensearch log analytics", region="us-east-1"),
        ServiceNode(id="app_search", name="App Search", service="opensearch application search", region="us-east-1"),
        ServiceNode(id="domain", name="Search Domain", service="opensearch domain", region="us-east-1"),
        ServiceNode(id="guardrail", name="Guardrail", service="bedrock guardrails", region="us-east-1"),
        ],
        flows=[],
    )

    normalized, diagnostics = normalize_spec(spec)
    services = {node.id: node.service for node in normalized.nodes}
    scopes = {node.id: node.scope for node in normalized.nodes}

    assert not [diagnostic for diagnostic in diagnostics if diagnostic.severity == "error"]
    assert services == {
        "agent": "bedrock_agent",
        "kb": "bedrock_knowledge_base",
        "vector": "opensearch_vector_index",
        "short": "bedrock_knowledge_base",
        "generic_vector": "generic_vector_store",
        "logs": "opensearch_log_analytics_index",
        "app_search": "opensearch_application_search_index",
        "domain": "opensearch_domain",
        "guardrail": "bedrock_guardrails",
    }
    assert scopes["agent"] == "regional_managed_ai"
    assert scopes["vector"] == "regional_managed_data"

    catalog = get_provider_catalog("aws")
    nodes = {node.id: node for node in normalized.nodes}
    assert classify_flow(Flow(id="r", source="agent", target="kb", label="RAG retrieval"), nodes["agent"], nodes["kb"], catalog).edge_type == "rag_retrieval"
    assert classify_flow(Flow(id="v", source="kb", target="vector", label="vector search"), nodes["kb"], nodes["vector"], catalog).edge_type == "vector_search"
    assert classify_flow(Flow(id="g", source="agent", target="guardrail", label="guardrail check"), nodes["agent"], nodes["guardrail"], catalog).edge_type == "guardrail_check"


def test_rag_runtime_and_ingestion_views_are_generated(tmp_path):
    spec = _rag_assistant_spec()
    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    view_names = {view.name for view in bundle.views}

    assert bundle.qa_report.passed
    assert "rag_retrieval_view" in view_names
    assert "rag_ingestion_view" in view_names
    assert "ai_security_governance_view" not in view_names
    assert "rag_view" not in view_names
    assert "network_private_connectivity" in view_names

    retrieval = next(layout for layout in bundle.layout_models if layout.view_id == "rag_retrieval_view")
    retrieval_lanes = {node.id: node.lane_id for node in retrieval.nodes}
    assert retrieval_lanes["kb"] == "rag_retrieval"
    assert retrieval_lanes["vector"] == "vector_search"
    assert retrieval_lanes["docs"] == "data_sources"
    assert {edge.edge_type for edge in retrieval.edges}.issuperset({"rag_retrieval", "vector_search", "source_reference"})
    ledger_views = {entry.flow_id: entry.view_id for entry in bundle.flow_ledger.entries}
    assert ledger_views["f05"] == "rag_retrieval_view"
    assert ledger_views["f06"] == "rag_retrieval_view"
    assert ledger_views["f09"] == "rag_ingestion_view"

    ingestion = next(layout for layout in bundle.layout_models if layout.view_id == "rag_ingestion_view")
    assert {edge.edge_type for edge in ingestion.edges}.issuperset({"document_ingestion", "document_chunking", "document_embedding"})
    assert {entry.flow_id for entry in bundle.flow_ledger.entries} == {flow.id for flow in bundle.normalized_spec.flows}


def test_agent_tool_memory_and_governance_views_are_generated(tmp_path):
    spec = _agentic_spec(tool_count=6)
    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    view_names = {view.name for view in bundle.views}

    assert bundle.qa_report.passed
    assert "agent_tool_execution_view" in view_names
    assert "agent_memory_view" in view_names
    assert "ai_security_governance_view" in view_names
    assert "fanout_detail_view" in view_names

    tool_layout = next(layout for layout in bundle.layout_models if layout.view_id == "agent_tool_execution_view")
    assert any(node.label == "Agent tools ×6" for node in tool_layout.nodes)
    assert not any("synthetic" in node.label.lower() or "repair node" in node.label.lower() for node in tool_layout.nodes)

    collapsed = [entry for entry in bundle.flow_ledger.entries if entry.source == "agent" and entry.target.startswith("tool_")]
    assert collapsed
    assert {entry.status for entry in collapsed} == {"collapsed_into_group"}
    assert {entry.reason for entry in collapsed} == {"agent tool fan-out summarized to reduce crossings"}

    memory = next(layout for layout in bundle.layout_models if layout.view_id == "agent_memory_view")
    assert {edge.edge_type for edge in memory.edges} == {"prompt_lookup", "memory_read", "memory_write"}
    ledger_views = {entry.flow_id: entry.view_id for entry in bundle.flow_ledger.entries}
    assert ledger_views["f03"] == "agent_memory_view"
    assert ledger_views["f06"] == "ai_security_governance_view"


def test_rendered_agent_tool_fanout_primary_stays_clean(tmp_path):
    if find_d2_executable() is None:
        return
    bundle = compile_architecture(_agentic_spec(tool_count=6), Path(tmp_path), render=True, render_formats=("svg",))
    tool_view = next(view for view in bundle.views if view.name == "agent_tool_execution_view")
    svg_path = tool_view.artifact_paths["svg"]

    assert bundle.qa_report.passed
    assert _svg_edge_crossing_count(svg_path) <= 8
    assert _svg_edge_label_overlap_count(svg_path) == 0
    assert "Agent tools ×6" in tool_view.d2_text
    assert all(internal not in tool_view.d2_text.lower() for internal in ["parallel branch", "synthetic", "repair node", "dependency branch"])


def test_agent_tool_fanout_count_is_consistent_across_views(tmp_path):
    bundle = compile_architecture(_agentic_spec(tool_count=12), Path(tmp_path), render=False)
    labels_by_view = {
        layout.view_id: {node.label for node in layout.nodes}
        for layout in bundle.layout_models
    }
    collapsed = [entry for entry in bundle.flow_ledger.entries if entry.source == "agent" and entry.target.startswith("tool_")]

    assert bundle.qa_report.passed
    assert "Agent tools ×12" in labels_by_view["production_logical_service_flow"]
    assert "Agent tools ×12" in labels_by_view["agent_tool_execution_view"]
    assert "Agent tools ×12" in labels_by_view["fanout_detail_view"]
    assert {entry.group_id for entry in collapsed} == {"agent_lambda_tool_fanout_group"}
    assert {entry.view_id for entry in collapsed} == {"production_logical_service_flow"}


def test_rendered_ai_rag_golden_scenarios(tmp_path):
    if find_d2_executable() is None:
        return
    scenarios = [
        ("simple_rag", _simple_rag_spec(), {"production_logical_service_flow", "rag_retrieval_view", "network_private_connectivity"}, {"rag_ingestion_view", "agent_tool_execution_view", "agent_memory_view", "ai_security_governance_view", "ai_logical_service_flow"}),
        ("rag_assistant", _rag_assistant_spec(), {"rag_retrieval_view", "rag_ingestion_view"}, {"agent_tool_execution_view", "agent_memory_view", "ai_logical_service_flow"}),
        ("agent_tools", _agentic_spec(tool_count=6), {"agent_tool_execution_view", "agent_memory_view", "ai_security_governance_view"}),
        ("ingestion_pipeline", _rag_ingestion_only_spec(), {"rag_ingestion_view"}),
        ("multi_agent", _multi_agent_spec(), {"agent_tool_execution_view"}),
        ("memory", _agent_memory_spec(), {"agent_memory_view"}),
        ("governance", _ai_governance_spec(), {"ai_security_governance_view"}),
        ("hybrid_search", _hybrid_search_spec(), {"rag_retrieval_view"}),
        ("sagemaker", _sagemaker_inference_spec(), {"production_logical_service_flow"}, {"rag_retrieval_view", "agent_tool_execution_view", "agent_memory_view", "ai_security_governance_view", "ai_logical_service_flow"}),
        ("private_bedrock", _private_bedrock_access_spec(), {"network_private_connectivity", "rag_retrieval_view"}),
        ("tool_registry", _tool_registry_spec(), {"agent_tool_execution_view"}),
        ("mixed_traditional_ai", _traditional_ai_mixed_spec(), {"rag_retrieval_view", "network_private_connectivity"}),
        ("private_ai_full", _private_ai_full_spec(), {"network_private_connectivity", "rag_retrieval_view", "agent_memory_view", "ai_security_governance_view"}),
    ]

    for item in scenarios:
        if len(item) == 3:
            name, spec, expected_views = item
            forbidden_views = set()
        else:
            name, spec, expected_views, forbidden_views = item
        bundle = compile_architecture(spec, Path(tmp_path) / name, render=True, render_formats=("svg",))
        view_names = {view.name for view in bundle.views}
        primary = next((view for view in bundle.views if view.name == "production_logical_service_flow"), bundle.views[0])

        assert bundle.qa_report.passed, name
        assert expected_views.issubset(view_names), name
        assert not (forbidden_views & view_names), name
        assert {entry.flow_id for entry in bundle.flow_ledger.entries} == {flow.id for flow in bundle.normalized_spec.flows}
        assert _svg_edge_label_overlap_count(primary.artifact_paths["svg"]) == 0
        _assert_final_svg_text_hardening(bundle, is_compliance=("compliance" in spec.title.lower() or spec.metadata.get("domain") == "compliance"))


def test_no_duplicate_rag_views_when_overview_requested(tmp_path):
    spec = _simple_rag_spec()
    spec.metadata["expected_views"] = ["rag_view"]
    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    view_names = {view.name for view in bundle.views}
    render_plan = (Path(tmp_path) / "render_plan.json").read_text(encoding="utf-8")

    assert bundle.qa_report.passed
    assert "rag_retrieval_view" in view_names
    assert "rag_view" not in view_names
    assert "Covered by dedicated RAG retrieval/ingestion views" in render_plan


def test_rag_ingestion_view_contains_vector_index(tmp_path):
    bundle = compile_architecture(_rag_ingestion_only_spec(), Path(tmp_path), render=False)
    ingestion = next(layout for layout in bundle.layout_models if layout.view_id == "rag_ingestion_view")

    assert bundle.qa_report.passed
    assert any(node.service == "opensearch_vector_index" for node in ingestion.nodes)
    assert {"document_ingestion", "document_chunking", "document_embedding"} <= {edge.edge_type for edge in ingestion.edges}


def test_rag_retrieval_view_excludes_ingestion_jobs(tmp_path):
    bundle = compile_architecture(_rag_assistant_spec(), Path(tmp_path), render=False)
    retrieval = next(layout for layout in bundle.layout_models if layout.view_id == "rag_retrieval_view")
    retrieval_node_ids = {node.id for node in retrieval.nodes}

    assert bundle.qa_report.passed
    assert {"ingestion", "chunker", "embedder"}.isdisjoint(retrieval_node_ids)
    assert {"kb", "vector", "docs"} <= retrieval_node_ids


def test_primary_view_summarizes_when_specialized_rag_views_exist(tmp_path):
    bundle = compile_architecture(_rag_assistant_spec(), Path(tmp_path), render=False)
    production = next(layout for layout in bundle.layout_models if layout.view_id == "production_logical_service_flow")
    production_node_ids = {node.id for node in production.nodes}
    production_labels = {node.label for node in production.nodes}

    assert bundle.qa_report.passed
    assert {"rag_retrieval_view", "rag_ingestion_view"} <= {layout.view_id for layout in bundle.layout_models}
    assert "AI/ML layer" in production_labels
    assert {"kb", "vector", "docs", "ingestion", "chunker", "embedder"}.isdisjoint(production_node_ids)


def test_rag_ingestion_lanes_are_semantic(tmp_path):
    bundle = compile_architecture(_rag_assistant_spec(), Path(tmp_path), render=False)
    ingestion = next(layout for layout in bundle.layout_models if layout.view_id == "rag_ingestion_view")
    labels = {lane.label for lane in ingestion.lanes}

    assert bundle.qa_report.passed
    assert "Stage 1" not in labels
    assert "Stage 2" not in labels
    assert {"Source Documents", "Document Ingestion", "Document Processing", "Embedding Generation"}.issubset(labels)


def test_rag_retrieval_model_invocation_is_side_path(tmp_path):
    bundle = compile_architecture(_rag_assistant_spec(), Path(tmp_path), render=False)
    retrieval = next(layout for layout in bundle.layout_models if layout.view_id == "rag_retrieval_view")
    nodes = {node.id: node for node in retrieval.nodes}

    assert bundle.qa_report.passed
    assert any(edge.source == "agent" and edge.target == "model" and edge.edge_type == "model_invocation" for edge in retrieval.edges)
    assert any(edge.source == "agent" and edge.target == "kb" and edge.edge_type == "rag_retrieval" for edge in retrieval.edges)
    assert not [
        edge
        for edge in retrieval.edges
        if nodes.get(edge.source) is not None
        and nodes[edge.source].service == "bedrock"
        and nodes.get(edge.target) is not None
        and nodes[edge.target].service in {"opensearch_vector_index", "opensearch_hybrid_search", "s3"}
    ]


def test_vpc_rag_network_contains_expected_endpoints(tmp_path):
    bundle = compile_architecture(_private_ai_full_spec(), Path(tmp_path), render=False)
    network = next(layout for layout in bundle.layout_models if layout.view_id == "network_private_connectivity")
    labels = {node.label for node in network.nodes}

    assert bundle.qa_report.passed
    assert any("Bedrock interface endpoint" in label for label in labels)
    assert any("OpenSearch interface endpoint" in label for label in labels)
    assert any("S3 gateway endpoint" in label for label in labels)
    assert any("Secrets Manager interface endpoint" in label for label in labels)
    assert any("CloudWatch Logs interface endpoint" in label for label in labels)
    for node in network.nodes:
        if node.service in {"bedrock", "opensearch_vector_index", "s3", "secrets_manager", "cloudwatch", "kms"}:
            assert node.placement_scope not in {"vpc_resident", "vpc_workload", "vpc_data"}


def test_network_endpoint_targets_are_visible(tmp_path):
    for name, spec in {
        "retail": retail_order_fulfillment_spec(),
        "private_ai": _private_ai_full_spec(),
    }.items():
        bundle = compile_architecture(spec, Path(tmp_path) / name, render=False)
        network = next(layout for layout in bundle.layout_models if layout.view_id == "network_private_connectivity")
        nodes = {node.id: node for node in network.nodes}

        assert bundle.qa_report.passed
        for endpoint in [node for node in network.nodes if node.service == "vpc_endpoint"]:
            targets = [
                nodes[edge.target]
                for edge in network.edges
                if edge.source == endpoint.id and edge.target in nodes
            ]
            assert targets, (name, endpoint.label)
            assert all(target.service != "vpc_endpoint" for target in targets), (name, endpoint.label)


def test_security_governance_does_not_duplicate_network_endpoints(tmp_path):
    bundle = compile_architecture(_private_ai_full_spec(), Path(tmp_path), render=False)
    governance = next(layout for layout in bundle.layout_models if layout.view_id == "ai_security_governance_view")

    assert bundle.qa_report.passed
    assert not [node for node in governance.nodes if node.service == "vpc_endpoint"]
    assert {"secrets_manager", "cloudwatch", "kms"} <= {node.service for node in governance.nodes}


def test_no_compliance_actor_leakage(tmp_path):
    bundle = compile_architecture(_simple_rag_spec(), Path(tmp_path), render=False)
    all_d2 = "\n".join(view.d2_text for view in bundle.views)
    explanations = (Path(tmp_path) / "placement_explanations.md").read_text(encoding="utf-8")

    assert bundle.qa_report.passed
    assert "Compliance Analyst" not in all_d2
    assert "Compliance Analyst" not in explanations


def test_ai_governance_view_requires_governance_semantics(tmp_path):
    spec = SemanticArchitectureSpec(
        title="Model Invocation With Logs",
        nodes=[
            ServiceNode(id="app", name="Inference Service", service="lambda", region="us-east-1"),
            ServiceNode(id="model", name="Bedrock Model", service="bedrock", region="us-east-1"),
            ServiceNode(id="logs", name="CloudWatch", service="cloudwatch", region="us-east-1"),
        ],
        flows=[
            Flow(id="f1", source="app", target="model", label="invoke model"),
            Flow(id="f2", source="app", target="logs", label="logs and metrics"),
        ],
        metadata={"internet_facing": False},
    )
    bundle = compile_architecture(spec, Path(tmp_path), render=False)

    assert bundle.qa_report.passed
    assert "ai_security_governance_view" not in {view.name for view in bundle.views}


def test_unknown_ai_fallback_does_not_overgenerate_views(tmp_path):
    spec = SemanticArchitectureSpec(
        title="Custom AI Retrieval",
        nodes=[
            ServiceNode(id="agent", name="Agent Runtime", service="agent_runtime", region="us-east-1"),
            ServiceNode(id="vector", name="Custom Vector Store", service="custom_vector_store", region="us-east-1"),
            ServiceNode(id="llm", name="Third Party LLM", service="third_party_llm_endpoint", region="us-east-1"),
            ServiceNode(id="madeup", name="Made Up AI Service", service="made_up_ai_service", region="us-east-1"),
        ],
        flows=[
            Flow(id="f1", source="agent", target="vector", label="vector search"),
            Flow(id="f2", source="agent", target="llm", label="invoke model"),
            Flow(id="f3", source="agent", target="madeup", label="use AI service"),
        ],
        metadata={"internet_facing": False},
    )
    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    view_names = {view.name for view in bundle.views}

    assert bundle.qa_report.passed
    assert "production_logical_service_flow" in view_names
    assert "rag_retrieval_view" in view_names
    assert "ai_security_governance_view" not in view_names
    assert any(diagnostic.code == "aws_service_catalog_fallback" for diagnostic in bundle.diagnostics)
    normalized_by_id = {node.id: node for node in bundle.normalized_spec.nodes}
    assert normalized_by_id["llm"].category == "external_ai_service"
    assert normalized_by_id["vector"].category == "custom_vector_store"
    assert normalized_by_id["madeup"].category == "custom_ai_service"
    assert "regional_managed_data category" not in "\n".join(diagnostic.message for diagnostic in bundle.diagnostics if diagnostic.node_id == "llm")


def test_acronym_casing_and_human_explanations(tmp_path):
    spec = _private_ai_full_spec()
    spec.title = "private ai rag vpc app"
    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    rendered_text = "\n".join([view.d2_text for view in bundle.views])
    rendered_text += "\n" + (Path(tmp_path) / "placement_explanations.md").read_text(encoding="utf-8")

    assert bundle.qa_report.passed
    for bad in ["Ai ", "Rag ", "sQS", "Vpc", "Api Gateway"]:
        assert bad not in rendered_text
    assert "source_lambda_fanout_group" not in rendered_text
    assert "target_0" not in rendered_text


def test_long_labels_are_summarized_in_diagrams(tmp_path):
    spec = _long_observability_label_spec()
    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    d2 = "\n".join(view.d2_text for view in bundle.views)
    explanations = (Path(tmp_path) / "placement_explanations.md").read_text(encoding="utf-8")

    assert bundle.qa_report.passed
    assert "Logs / metrics sources:" not in d2
    assert "Application and model telemetry" in d2
    assert "observability_sources" not in explanations


def test_retail_observability_uses_non_ai_telemetry_wording(tmp_path):
    bundle = compile_architecture(retail_order_fulfillment_spec(), Path(tmp_path), render=False)
    d2 = "\n".join(view.d2_text for view in bundle.views)

    assert bundle.qa_report.passed
    assert "Application telemetry" in d2
    assert "model telemetry" not in d2.lower()


def test_ai_flow_ledger_entries_have_view_or_omission_reason(tmp_path):
    bundle = compile_architecture(_rag_assistant_spec(), Path(tmp_path), render=False)

    assert bundle.qa_report.passed
    for entry in bundle.flow_ledger.entries:
        if entry.classification in {"rag_retrieval", "vector_search", "source_reference", "document_ingestion", "document_chunking", "document_embedding", "model_invocation", "guardrail_check"}:
            assert entry.view_id or (entry.status == "omitted_with_reason" and entry.reason), entry


def test_no_duplicate_semantic_views_after_suppression(tmp_path):
    scenarios = {
        "memory": _agent_memory_spec(),
        "ingestion_pipeline": _rag_ingestion_only_spec(),
        "hybrid_search": _hybrid_search_spec(),
        "simple_rag_vpc_backend": _simple_rag_spec(),
    }
    for name, spec in scenarios.items():
        out = Path(tmp_path) / name
        bundle = compile_architecture(spec, out, render=False)
        omitted = {
            item["view_id"]: item["reason"]
            for item in json.loads((out / "render_plan.json").read_text(encoding="utf-8"))["omitted_views"]
        }

        assert bundle.qa_report.passed, name
        if name == "memory":
            assert "agent_memory_view" in {view.name for view in bundle.views}
            assert "production_logical_service_flow" not in {view.name for view in bundle.views}
            assert "production_logical_service_flow" in omitted
        if name == "ingestion_pipeline":
            assert "rag_ingestion_view" in {view.name for view in bundle.views}
            assert "production_logical_service_flow" not in {view.name for view in bundle.views}
            assert "production_logical_service_flow" in omitted
        if name == "hybrid_search":
            assert "rag_retrieval_view" in {view.name for view in bundle.views}
            assert "production_logical_service_flow" not in {view.name for view in bundle.views}
            assert "production_logical_service_flow" in omitted
        for first_index, first in enumerate(bundle.views):
            for second in bundle.views[first_index + 1:]:
                assert not _views_overlap_more_than_80(first, second), (name, first.name, second.name)


def test_no_meaningless_network_views_are_emitted(tmp_path):
    scenarios = {
        "agent_tools": _agentic_spec(tool_count=6),
        "multi_agent": _multi_agent_spec(),
        "private_ai_full": _private_ai_full_spec(),
        "mixed_traditional_ai": _traditional_ai_mixed_spec(),
    }
    for name, spec in scenarios.items():
        out = Path(tmp_path) / name
        bundle = compile_architecture(spec, out, render=False)
        view_names = {view.name for view in bundle.views}
        omitted = {
            item["view_id"]: item["reason"]
            for item in json.loads((out / "render_plan.json").read_text(encoding="utf-8"))["omitted_views"]
        }
        if "network_private_connectivity" not in view_names:
            assert omitted.get("network_private_connectivity") == "No meaningful private connectivity path for this architecture"
            continue
        network = next(layout for layout in bundle.layout_models if layout.view_id == "network_private_connectivity")
        nodes = {node.id: node for node in network.nodes}
        assert any(nodes[edge.source].placement_scope in {"vpc_resident", "vpc_workload", "vpc_data"} for edge in network.edges if edge.source in nodes), name
        assert any("endpoint" in edge.id or "vpc_link" in edge.id or nodes[edge.source].service in {"vpc_endpoint", "vpc_link"} or nodes[edge.target].service in {"vpc_endpoint", "vpc_link"} for edge in network.edges if edge.source in nodes and edge.target in nodes), name
        assert any(nodes[edge.target].service not in {"api_gateway", "vpc_link"} for edge in network.edges if edge.target in nodes), name


def test_rendered_labels_do_not_join_title_and_subtitle(tmp_path):
    if find_d2_executable() is None:
        return
    bundle = compile_architecture(_traditional_ai_mixed_spec(), Path(tmp_path), render=True, render_formats=("svg",))
    svg_text = "\n".join(
        view.artifact_paths["svg"].read_text(encoding="utf-8")
        for view in bundle.views
        if "svg" in view.artifact_paths
    )

    assert bundle.qa_report.passed
    for bad in ["AWS WAFEdge", "OpenSearchhybrid", "Serverlessvector", "BedrockKnowledge", "DynamoDBgateway", "CloudWatchLogs"]:
        assert bad not in svg_text


def test_mixed_traditional_ai_network_endpoint_completeness(tmp_path):
    bundle = compile_architecture(_traditional_ai_mixed_spec(), Path(tmp_path), render=False)
    network = next(layout for layout in bundle.layout_models if layout.view_id == "network_private_connectivity")
    labels = {node.label for node in network.nodes}

    assert bundle.qa_report.passed
    assert any("Bedrock interface endpoint" in label for label in labels)
    assert any("OpenSearch interface endpoint" in label for label in labels)
    assert any("S3 gateway endpoint" in label for label in labels)
    assert any("DynamoDB gateway endpoint" in label for label in labels)
    for node in network.nodes:
        if node.service in {"bedrock_knowledge_base", "opensearch_vector_index", "s3", "dynamodb"}:
            assert node.placement_scope not in {"vpc_resident", "vpc_workload", "vpc_data"}


def test_bedrock_endpoint_is_deduplicated_for_model_and_knowledge_base(tmp_path):
    spec = SemanticArchitectureSpec(
        title="Private Bedrock Endpoint Dedup",
        nodes=[
            ServiceNode(id="assistant", name="VPC Assistant", service="ecs", region="us-east-1", vpc_id="ai-vpc"),
            ServiceNode(id="model", name="Bedrock Model", service="bedrock", region="us-east-1"),
            ServiceNode(id="kb", name="Bedrock Knowledge Base", service="bedrock_knowledge_base", region="us-east-1"),
        ],
        flows=[
            Flow(id="f1", source="assistant", target="model", label="invoke model", metadata={"endpoint": "bedrock_interface_endpoint"}),
            Flow(id="f2", source="assistant", target="kb", label="RAG retrieval", metadata={"endpoint": "bedrock_interface_endpoint"}),
        ],
        metadata={"internet_facing": False, "vpcs": [{"id": "ai-vpc", "name": "AI VPC", "region": "us-east-1"}]},
    )
    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    network = next(layout for layout in bundle.layout_models if layout.view_id == "network_private_connectivity")

    assert bundle.qa_report.passed
    bedrock_endpoints = [node for node in network.nodes if node.label == "Bedrock interface endpoint"]
    assert len(bedrock_endpoints) == 1
    endpoint_id = bedrock_endpoints[0].id
    assert {(edge.source, edge.target) for edge in network.edges}.issuperset(
        {("assistant", endpoint_id), (endpoint_id, "model"), (endpoint_id, "kb")}
    )
    assert {node.id for node in network.nodes if node.service in {"bedrock", "bedrock_knowledge_base"}} == {"model", "kb"}
    for node in network.nodes:
        if node.service in {"bedrock", "bedrock_knowledge_base"}:
            assert node.placement_scope == "regional_managed_ai"
    ledger_targets = {(entry.target, entry.classification) for entry in bundle.flow_ledger.entries}
    assert ("model", "model_invocation") in ledger_targets
    assert ("kb", "rag_retrieval") in ledger_targets


def test_network_private_connectivity_includes_vpc_source_workload(tmp_path):
    for name, (expected_source, spec) in {
        "private_bedrock": ("app", _private_bedrock_access_spec()),
        "private_ai_full": ("assistant", _private_ai_full_spec()),
    }.items():
        bundle = compile_architecture(spec, Path(tmp_path) / name, render=False)
        network = next(layout for layout in bundle.layout_models if layout.view_id == "network_private_connectivity")
        nodes = {node.id: node for node in network.nodes}

        assert bundle.qa_report.passed
        assert expected_source in nodes
        assert nodes[expected_source].placement_scope in {"vpc_resident", "vpc_workload", "vpc_data"}
        assert any(edge.source == expected_source for edge in network.edges)


def test_rendered_endpoint_dedupe_and_label_hardening(tmp_path):
    if find_d2_executable() is None:
        return
    bundle = compile_architecture(_private_bedrock_access_spec(), Path(tmp_path), render=True, render_formats=("svg",))
    network_view = next(view for view in bundle.views if view.name == "network_private_connectivity")
    svg_text = _svg_text_without_images(network_view.artifact_paths["svg"])

    assert bundle.qa_report.passed
    assert svg_text.count("Bedrock interface endpoint") == 1
    assert "VPC Assistant" in svg_text
    _assert_final_svg_text_hardening(bundle)


def test_layout_model_similarity_suppression_for_private_ai_and_governance(tmp_path):
    for name, spec in {"private_ai_full": _private_ai_full_spec(), "governance": _ai_governance_spec()}.items():
        bundle = compile_architecture(spec, Path(tmp_path) / name, render=False)
        omitted = {
            item["view_id"]: item["reason"]
            for item in json.loads((Path(tmp_path) / name / "render_plan.json").read_text(encoding="utf-8"))["omitted_views"]
        }

        assert bundle.qa_report.passed
        for first_index, first in enumerate(bundle.layout_models):
            for second in bundle.layout_models[first_index + 1:]:
                assert not _layout_models_overlap_more_than_80(first, second), (name, first.view_id, second.view_id)
        if "production_logical_service_flow" in {layout.view_id for layout in bundle.layout_models}:
            production = next(layout for layout in bundle.layout_models if layout.view_id == "production_logical_service_flow")
            assert any(edge.edge_type in {"request", "private_integration", "agent_orchestration", "agent_handoff"} for edge in production.edges)
        else:
            assert "production_logical_service_flow" in omitted


def test_node_labels_are_concise(tmp_path):
    bundle = compile_architecture(_long_observability_label_spec(), Path(tmp_path), render=False)

    assert bundle.qa_report.passed
    for layout in bundle.layout_models:
        for node in layout.nodes:
            for line in node.label.replace("\\n", "\n").splitlines():
                assert len(line) <= 48, (layout.view_id, node.label)


def _assert_final_svg_text_hardening(bundle, is_compliance=False):
    svg_text = "\n".join(
        _svg_text_without_images(view.artifact_paths["svg"])
        for view in bundle.views
        if "svg" in view.artifact_paths
    )
    forbidden = [
        "AWS WAFEdge",
        "OpenSearchhybrid",
        "Serverlessvector",
        "BedrockKnowledge",
        "DynamoDBgateway",
        "CloudWatchLogs",
        "Ai",
        "Rag",
        "sQS",
        "Vpc",
        "Api Gateway",
        "parallel fan-out",
        "repair node",
        "synthetic",
        "dependency branch",
        "Control dependency / parallel fan-out",
        "Async trigger / parallel fan-out",
        "Agent memory / parallel fan-out",
        "Stage 1",
        "Stage 2",
        "Workflow segment 1",
        "Workflow segment 2",
    ]
    if not is_compliance:
        forbidden.append("Compliance Analyst")
    for bad in forbidden:
        assert bad not in svg_text


def _svg_text_without_images(svg_path: Path) -> str:
    svg_text = svg_path.read_text(encoding="utf-8")
    svg_text = re.sub(r"<image\b[^>]*>", "", svg_text, flags=re.IGNORECASE | re.DOTALL)
    svg_text = re.sub(r"data:image/[^\"'>\s]+", "", svg_text, flags=re.IGNORECASE)
    return re.sub(r"[A-Za-z0-9+/=]{80,}", "", svg_text)


def _views_overlap_more_than_80(first, second):
    first_nodes = set(first.included_nodes)
    second_nodes = set(second.included_nodes)
    first_flows = set(first.included_flows)
    second_flows = set(second.included_flows)
    if not first_nodes or not second_nodes or not first_flows or not second_flows:
        return False
    node_overlap = len(first_nodes & second_nodes) / float(max(len(first_nodes), len(second_nodes)))
    flow_overlap = len(first_flows & second_flows) / float(max(len(first_flows), len(second_flows)))
    return node_overlap > 0.8 and flow_overlap > 0.8


def _layout_models_overlap_more_than_80(first, second):
    first_nodes = {node.id for node in first.nodes}
    second_nodes = {node.id for node in second.nodes}
    first_flows = {flow_id for edge in first.edges for flow_id in edge.source_flow_ids}
    second_flows = {flow_id for edge in second.edges for flow_id in edge.source_flow_ids}
    if not first_nodes or not second_nodes or not first_flows or not second_flows:
        return False
    node_overlap = len(first_nodes & second_nodes) / float(max(len(first_nodes), len(second_nodes)))
    flow_overlap = len(first_flows & second_flows) / float(max(len(first_flows), len(second_flows)))
    return node_overlap > 0.8 and flow_overlap > 0.8


def _simple_rag_spec():
    return SemanticArchitectureSpec(
        title="Simple RAG App",
        nodes=[
            ServiceNode(id="api", name="Assistant API", service="api_gateway", region="us-east-1"),
            ServiceNode(id="assistant", name="Assistant Service", service="ecs", region="us-east-1", vpc_id="rag-vpc", metadata={"role": "agent_runtime"}),
            ServiceNode(id="kb", name="Bedrock KB", service="bedrock_knowledge_base", region="us-east-1", metadata={"role": "retrieval_layer"}),
            ServiceNode(id="vector", name="Vector Index", service="opensearch_vector_index", region="us-east-1", metadata={"role": "vector_index"}),
            ServiceNode(id="docs", name="Documents", service="s3", region="us-east-1", metadata={"role": "source_documents"}),
        ],
        flows=[
            Flow(id="f1", source="api", target="assistant", label="private integration"),
            Flow(id="f2", source="assistant", target="kb", label="RAG retrieval", metadata={"endpoint": "bedrock_interface_endpoint"}),
            Flow(id="f3", source="kb", target="vector", label="vector search"),
            Flow(id="f4", source="vector", target="docs", label="source references"),
        ],
        metadata={"internet_facing": False, "vpcs": [{"id": "rag-vpc", "name": "RAG VPC", "region": "us-east-1"}]},
    )


def _long_observability_label_spec():
    nodes = [
        ServiceNode(id="api", name="Assistant API", service="api_gateway", region="us-east-1"),
        ServiceNode(id="app", name="ECS Assistant", service="ecs", region="us-east-1", vpc_id="obs-vpc"),
        ServiceNode(id="model", name="Bedrock Model", service="bedrock", region="us-east-1"),
        ServiceNode(id="worker", name="Chunking Job", service="lambda", region="us-east-1"),
        ServiceNode(id="secrets", name="Secrets Manager", service="secrets_manager", region="us-east-1"),
        ServiceNode(id="kms", name="KMS Key", service="kms", region="us-east-1"),
        ServiceNode(id="trail", name="CloudTrail", service="cloudtrail", region="us-east-1"),
        ServiceNode(id="logs", name="CloudWatch", service="cloudwatch", region="us-east-1"),
    ]
    return SemanticArchitectureSpec(
        title="Observability Label Summary",
        nodes=nodes,
        flows=[
            Flow(id="f1", source="api", target="app", label="private integration"),
            Flow(id="f2", source="app", target="model", label="invoke model"),
            Flow(id="f3", source="app", target="worker", label="run processing"),
            Flow(id="f4", source="app", target="secrets", label="read secret", metadata={"endpoint": "secrets_manager_interface_endpoint"}),
            Flow(id="f5", source="secrets", target="kms", label="decrypt secret"),
        ],
        metadata={"internet_facing": True, "vpcs": [{"id": "obs-vpc", "name": "Observability VPC", "region": "us-east-1"}]},
    )


def _rag_assistant_spec():
    return SemanticArchitectureSpec(
        title="Agentic RAG Assistant",
        nodes=[
            ServiceNode(id="user", name="Analyst", service="external_actor"),
            ServiceNode(id="api", name="AI API", service="api_gateway", region="us-east-1"),
            ServiceNode(id="app", name="Agent Runtime", service="ecs", region="us-east-1", vpc_id="ai-vpc", metadata={"role": "agent_runtime"}),
            ServiceNode(id="agent", name="Bedrock Agent", service="bedrock_agent", region="us-east-1", metadata={"role": "agent_orchestrator"}),
            ServiceNode(id="kb", name="Bedrock KB", service="bedrock_kb", region="us-east-1", metadata={"role": "retrieval_layer"}),
            ServiceNode(id="vector", name="Vector Index", service="opensearch_vector_index", region="us-east-1", metadata={"role": "vector_index"}),
            ServiceNode(id="docs", name="Source Documents", service="s3", region="us-east-1", metadata={"role": "source_documents"}),
            ServiceNode(id="ingestion", name="Ingestion Job", service="lambda", region="us-east-1", metadata={"role": "document_ingestion"}),
            ServiceNode(id="chunker", name="Document Chunker", service="lambda", region="us-east-1", metadata={"role": "document_chunker"}),
            ServiceNode(id="embedder", name="Embedding Model", service="bedrock", region="us-east-1", metadata={"role": "embedding_model"}),
            ServiceNode(id="model", name="Foundation Model", service="bedrock", region="us-east-1", metadata={"role": "foundation_model"}),
            ServiceNode(id="guardrail", name="Bedrock Guardrails", service="bedrock_guardrails", region="us-east-1", metadata={"role": "guardrails"}),
        ],
        flows=[
            Flow(id="f01", source="user", target="api", label="ask question"),
            Flow(id="f02", source="api", target="app", label="invoke assistant"),
            Flow(id="f03", source="app", target="agent", label="agent orchestration"),
            Flow(id="f04", source="agent", target="guardrail", label="guardrail check"),
            Flow(id="f05", source="agent", target="kb", label="RAG retrieval"),
            Flow(id="f06", source="kb", target="vector", label="vector search"),
            Flow(id="f07", source="vector", target="docs", label="source references"),
            Flow(id="f08", source="agent", target="model", label="invoke model"),
            Flow(id="f09", source="docs", target="ingestion", label="document ingestion"),
            Flow(id="f10", source="ingestion", target="chunker", label="chunk document"),
            Flow(id="f11", source="chunker", target="embedder", label="document embedding"),
            Flow(id="f12", source="embedder", target="vector", label="store embedding"),
        ],
        metadata={"internet_facing": False},
    )


def _agentic_spec(tool_count):
    return SemanticArchitectureSpec(
        title="Agent Tool Platform",
        nodes=[
            ServiceNode(id="user", name="Operator", service="external_actor"),
            ServiceNode(id="api", name="Agent API", service="api_gateway", region="us-east-1"),
            ServiceNode(id="agent", name="Planner Agent", service="bedrock_agent", region="us-east-1", metadata={"role": "planner_agent"}),
            ServiceNode(id="prompts", name="Prompt Templates", service="s3", region="us-east-1", metadata={"role": "prompt_template_store"}),
            ServiceNode(id="memory", name="Conversation Memory", service="dynamodb", region="us-east-1", metadata={"role": "conversation_memory"}),
            ServiceNode(id="guardrail", name="Guardrails", service="bedrock_guardrails", region="us-east-1", metadata={"role": "guardrails"}),
            ServiceNode(id="eval", name="Evaluation Runner", service="lambda", region="us-east-1", metadata={"role": "eval_runner"}),
            *[
                ServiceNode(id=f"tool_{index}", name=f"Tool {index}", service="lambda", region="us-east-1", metadata={"role": "lambda_tool"})
                for index in range(tool_count)
            ],
        ],
        flows=[
            Flow(id="f01", source="user", target="api", label="request"),
            Flow(id="f02", source="api", target="agent", label="agent orchestration"),
            Flow(id="f03", source="agent", target="prompts", label="prompt lookup"),
            Flow(id="f04", source="agent", target="memory", label="memory read"),
            Flow(id="f05", source="agent", target="memory", label="memory write"),
            Flow(id="f06", source="agent", target="guardrail", label="guardrail check"),
            Flow(id="f07", source="agent", target="eval", label="evaluation"),
            *[
                Flow(id=f"tool_flow_{index}", source="agent", target=f"tool_{index}", label="invoke tool")
                for index in range(tool_count)
            ],
        ],
        metadata={"internet_facing": False},
    )


def _rag_ingestion_only_spec():
    return SemanticArchitectureSpec(
        title="Knowledge Base Ingestion",
        nodes=[
            ServiceNode(id="docs", name="Raw Documents", service="s3", region="us-east-1", metadata={"role": "source_documents"}),
            ServiceNode(id="ingestion", name="Ingestion Pipeline", service="lambda", region="us-east-1", metadata={"role": "document_ingestion"}),
            ServiceNode(id="chunker", name="Chunking Job", service="lambda", region="us-east-1", metadata={"role": "document_chunker"}),
            ServiceNode(id="embedder", name="Embedding Model", service="bedrock", region="us-east-1", metadata={"role": "embedding_model"}),
            ServiceNode(id="vector", name="Vector Index", service="opensearch_vector_index", region="us-east-1", metadata={"role": "vector_index"}),
        ],
        flows=[
            Flow(id="f1", source="docs", target="ingestion", label="document ingestion"),
            Flow(id="f2", source="ingestion", target="chunker", label="chunk document"),
            Flow(id="f3", source="chunker", target="embedder", label="document embedding"),
            Flow(id="f4", source="embedder", target="vector", label="store embedding"),
        ],
        metadata={"internet_facing": False},
    )


def _multi_agent_spec():
    return SemanticArchitectureSpec(
        title="Multi-Agent Review",
        nodes=[
            ServiceNode(id="api", name="Agent API", service="api_gateway", region="us-east-1"),
            ServiceNode(id="planner", name="Planner Agent", service="bedrock_agent", region="us-east-1", metadata={"role": "planner_agent"}),
            ServiceNode(id="worker", name="Worker Agent", service="bedrock_agent", region="us-east-1", metadata={"role": "worker_agent"}),
            ServiceNode(id="reviewer", name="Reviewer Agent", service="bedrock_agent", region="us-east-1", metadata={"role": "reviewer_agent"}),
            ServiceNode(id="tool", name="Policy Tool", service="lambda", region="us-east-1", metadata={"role": "lambda_tool"}),
        ],
        flows=[
            Flow(id="f1", source="api", target="planner", label="agent orchestration"),
            Flow(id="f2", source="planner", target="worker", label="handoff"),
            Flow(id="f3", source="worker", target="tool", label="invoke tool"),
            Flow(id="f4", source="worker", target="reviewer", label="handoff"),
        ],
        metadata={"internet_facing": False},
    )


def _agent_memory_spec():
    return SemanticArchitectureSpec(
        title="Agent Memory",
        nodes=[
            ServiceNode(id="agent", name="Agent", service="bedrock_agent", region="us-east-1", metadata={"role": "agent_orchestrator"}),
            ServiceNode(id="prompts", name="Prompts", service="s3", region="us-east-1", metadata={"role": "prompt_template_store"}),
            ServiceNode(id="memory", name="Long-Term Memory", service="dynamodb", region="us-east-1", metadata={"role": "long_term_memory"}),
        ],
        flows=[
            Flow(id="f1", source="agent", target="prompts", label="prompt lookup"),
            Flow(id="f2", source="agent", target="memory", label="memory read"),
            Flow(id="f3", source="agent", target="memory", label="memory write"),
        ],
        metadata={"internet_facing": False},
    )


def _ai_governance_spec():
    return SemanticArchitectureSpec(
        title="AI Governance",
        nodes=[
            ServiceNode(id="agent", name="Agent", service="bedrock_agent", region="us-east-1", metadata={"role": "agent_orchestrator"}),
            ServiceNode(id="guardrail", name="Guardrails", service="bedrock_guardrails", region="us-east-1", metadata={"role": "guardrails"}),
            ServiceNode(id="eval", name="Eval Runner", service="lambda", region="us-east-1", metadata={"role": "eval_runner"}),
            ServiceNode(id="approval", name="Human Approval", service="external_actor", metadata={"role": "human_approval"}),
            ServiceNode(id="logs", name="Model Observability", service="cloudwatch", region="us-east-1", metadata={"role": "observability_sink"}),
        ],
        flows=[
            Flow(id="f1", source="agent", target="guardrail", label="guardrail check"),
            Flow(id="f2", source="agent", target="eval", label="evaluation"),
            Flow(id="f3", source="agent", target="approval", label="human approval"),
            Flow(id="f4", source="agent", target="logs", label="model observability"),
        ],
        metadata={"internet_facing": False},
    )


def _hybrid_search_spec():
    return SemanticArchitectureSpec(
        title="Hybrid Search RAG",
        nodes=[
            ServiceNode(id="app", name="Assistant", service="lambda", region="us-east-1"),
            ServiceNode(id="kb", name="Knowledge Base", service="bedrock_knowledge_base", region="us-east-1", metadata={"role": "retrieval_layer"}),
            ServiceNode(id="hybrid", name="Hybrid Index", service="opensearch_hybrid_search", region="us-east-1", metadata={"role": "hybrid_search_index"}),
            ServiceNode(id="docs", name="Documents", service="s3", region="us-east-1", metadata={"role": "source_documents"}),
        ],
        flows=[
            Flow(id="f1", source="app", target="kb", label="RAG retrieval"),
            Flow(id="f2", source="kb", target="hybrid", label="hybrid search"),
            Flow(id="f3", source="hybrid", target="docs", label="source references"),
        ],
        metadata={"internet_facing": False},
    )


def _sagemaker_inference_spec():
    return SemanticArchitectureSpec(
        title="SageMaker Inference",
        nodes=[
            ServiceNode(id="api", name="Inference API", service="api_gateway", region="us-east-1"),
            ServiceNode(id="svc", name="Inference Service", service="lambda", region="us-east-1"),
            ServiceNode(id="model", name="SageMaker Endpoint", service="sagemaker", region="us-east-1", metadata={"role": "model_endpoint"}),
            ServiceNode(id="artifacts", name="Model Artifacts", service="s3", region="us-east-1", metadata={"role": "document_store"}),
        ],
        flows=[
            Flow(id="f1", source="api", target="svc", label="request"),
            Flow(id="f2", source="svc", target="model", label="invoke model"),
            Flow(id="f3", source="model", target="artifacts", label="read artifacts"),
        ],
        metadata={"internet_facing": False},
    )


def _private_bedrock_access_spec():
    return SemanticArchitectureSpec(
        title="Private Bedrock Access",
        nodes=[
            ServiceNode(id="app", name="VPC Assistant", service="ecs", region="us-east-1", vpc_id="ai-vpc", metadata={"role": "agent_runtime"}),
            ServiceNode(id="kb", name="Bedrock KB", service="bedrock_knowledge_base", region="us-east-1", metadata={"role": "retrieval_layer", "access": "private_endpoint"}),
            ServiceNode(id="bedrock", name="Bedrock Model", service="bedrock", region="us-east-1", metadata={"role": "foundation_model", "access": "private_endpoint"}),
        ],
        flows=[
            Flow(id="f1", source="app", target="kb", label="RAG retrieval", metadata={"endpoint": "bedrock_interface_endpoint"}),
            Flow(id="f2", source="app", target="bedrock", label="invoke model", metadata={"endpoint": "bedrock_interface_endpoint"}),
        ],
        metadata={"internet_facing": False, "vpcs": [{"id": "ai-vpc", "name": "AI VPC", "region": "us-east-1"}]},
    )


def _traditional_ai_mixed_spec():
    return SemanticArchitectureSpec(
        title="Traditional And AI Mixed Workload",
        nodes=[
            ServiceNode(id="user", name="Customer", service="external_actor"),
            ServiceNode(id="cloudfront", name="CloudFront", service="cloudfront", region="global"),
            ServiceNode(id="api", name="Order API", service="api_gateway", region="us-east-1"),
            ServiceNode(id="orders", name="Order Service", service="ecs", region="us-east-1", vpc_id="mix-vpc"),
            ServiceNode(id="assistant", name="Agent Assistant", service="ecs", region="us-east-1", vpc_id="mix-vpc", metadata={"role": "agent_runtime"}),
            ServiceNode(id="kb", name="Bedrock KB", service="bedrock_knowledge_base", region="us-east-1", metadata={"role": "retrieval_layer"}),
            ServiceNode(id="vector", name="OpenSearch Vector", service="opensearch_vector_index", region="us-east-1", metadata={"role": "vector_index"}),
            ServiceNode(id="docs", name="Documents", service="s3", region="us-east-1", metadata={"role": "source_documents"}),
            ServiceNode(id="table", name="Orders Table", service="dynamodb", region="us-east-1"),
        ],
        flows=[
            Flow(id="f1", source="user", target="cloudfront", label="HTTPS"),
            Flow(id="f2", source="cloudfront", target="api", label="HTTPS"),
            Flow(id="f3", source="api", target="orders", label="private integration"),
            Flow(id="f4", source="orders", target="table", label="write order"),
            Flow(id="f5", source="orders", target="assistant", label="ask assistant"),
            Flow(id="f6", source="assistant", target="kb", label="RAG retrieval", metadata={"endpoint": "bedrock_interface_endpoint"}),
            Flow(id="f7", source="assistant", target="vector", label="vector search", metadata={"endpoint": "opensearch_interface_endpoint"}),
            Flow(id="f8", source="vector", target="docs", label="source references"),
            Flow(id="f9", source="assistant", target="docs", label="read documents", metadata={"endpoint": "s3_gateway_endpoint"}),
        ],
        metadata={"internet_facing": True, "vpcs": [{"id": "mix-vpc", "name": "Mixed VPC", "region": "us-east-1"}]},
    )


def _private_ai_full_spec():
    return SemanticArchitectureSpec(
        title="Private AI Full Connectivity",
        nodes=[
            ServiceNode(id="assistant", name="Private Assistant", service="ecs", region="us-east-1", vpc_id="ai-vpc", metadata={"role": "agent_runtime"}),
            ServiceNode(id="bedrock", name="Bedrock Model", service="bedrock", region="us-east-1", metadata={"role": "foundation_model"}),
            ServiceNode(id="vector", name="OpenSearch Vector", service="opensearch_vector_index", region="us-east-1", metadata={"role": "vector_index"}),
            ServiceNode(id="docs", name="Document Bucket", service="s3", region="us-east-1", metadata={"role": "source_documents"}),
            ServiceNode(id="memory", name="Conversation Memory", service="dynamodb", region="us-east-1", metadata={"role": "conversation_memory"}),
            ServiceNode(id="secrets", name="Secrets Manager", service="secrets_manager", region="us-east-1"),
            ServiceNode(id="kms", name="KMS Key", service="kms", region="us-east-1"),
            ServiceNode(id="cloudwatch", name="CloudWatch", service="cloudwatch", region="us-east-1"),
        ],
        flows=[
            Flow(id="f1", source="assistant", target="bedrock", label="invoke model", metadata={"endpoint": "bedrock_interface_endpoint"}),
            Flow(id="f2", source="assistant", target="vector", label="vector search", metadata={"endpoint": "opensearch_interface_endpoint"}),
            Flow(id="f3", source="vector", target="docs", label="source references"),
            Flow(id="f4", source="assistant", target="memory", label="memory write", metadata={"endpoint": "dynamodb_gateway_endpoint"}),
            Flow(id="f5", source="assistant", target="secrets", label="read secret", metadata={"endpoint": "secrets_manager_interface_endpoint"}),
            Flow(id="f6", source="secrets", target="kms", label="decrypt secret"),
            Flow(id="f7", source="assistant", target="cloudwatch", label="model observability", metadata={"endpoint": "cloudwatch_logs_interface_endpoint"}),
            Flow(id="f8", source="assistant", target="docs", label="read documents", metadata={"endpoint": "s3_gateway_endpoint"}),
        ],
        metadata={"internet_facing": False, "vpcs": [{"id": "ai-vpc", "name": "AI VPC", "region": "us-east-1"}]},
    )


def _tool_registry_spec():
    return SemanticArchitectureSpec(
        title="Tool Registry",
        nodes=[
            ServiceNode(id="agent", name="Agent", service="bedrock_agent", region="us-east-1", metadata={"role": "agent_orchestrator"}),
            ServiceNode(id="registry", name="Tool Registry", service="dynamodb", region="us-east-1", metadata={"role": "tool_registry"}),
            ServiceNode(id="executor", name="Tool Executor", service="lambda", region="us-east-1", metadata={"role": "tool_executor"}),
            ServiceNode(id="external", name="External Tool", service="external_actor", metadata={"role": "external_tool"}),
        ],
        flows=[
            Flow(id="f1", source="agent", target="registry", label="tool lookup"),
            Flow(id="f2", source="agent", target="executor", label="invoke tool"),
            Flow(id="f3", source="executor", target="external", label="call external tool"),
        ],
        metadata={"internet_facing": False},
    )
