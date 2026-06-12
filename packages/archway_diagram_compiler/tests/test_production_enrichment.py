from pathlib import Path

from archway_diagram_compiler.compiler import compile_architecture
from tests.test_compliance_knowledge_assistant_golden import compliance_knowledge_assistant_spec


def test_production_enrichment_adds_edge_auth_private_and_rag_patterns(tmp_path):
    bundle = compile_architecture(compliance_knowledge_assistant_spec(), Path(tmp_path), render=False)
    nodes = {node.id: node for node in bundle.normalized_spec.nodes}
    flows = {(flow.source, flow.target): flow for flow in bundle.normalized_spec.flows}

    assert {"user", "route53", "shield", "waf"}.issubset(nodes)
    assert ("waf", "cloudfront") in flows
    assert flows[("waf", "cloudfront")].metadata["edge_kind"] == "control"

    assert ("api", "cognito") not in flows
    assert ("user", "cognito") in flows
    assert ("cognito", "user") in flows
    assert ("user", "api") in flows

    assert "assistant_vpc_link" in nodes
    assert "assistant_private_lb" in nodes
    assert ("api", "assistant_vpc_link") in flows
    assert ("assistant_vpc_link", "assistant_private_lb") in flows
    assert ("assistant_private_lb", "assistant") in flows

    assert "assistant_s3_endpoint" in nodes
    assert "assistant_bedrock_endpoint" in nodes
    assert "assistant_secrets_manager_endpoint" in nodes
    assert "assistant_cloudwatch_logs_endpoint" in nodes

    assert "bedrock_knowledge_base" in nodes
    assert "opensearch_vector_index" in nodes
    assert "knowledge_index" not in nodes

    assert "audit_log_bucket" in nodes
    assert ("cloudtrail", "audit_log_bucket") in flows

    assert bundle.qa_report.passed
    assert [view.name for view in bundle.views][:2] == [
        "production_logical_service_flow",
        "network_private_connectivity",
    ]
    assert "rag_retrieval_view" in {view.name for view in bundle.views}
    assert "rag_view" not in {view.name for view in bundle.views}
    assert bundle.qa_report.metrics["main_visible_edge_count"] <= 16
