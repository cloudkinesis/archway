from archway_diagram_compiler.compiler import compile_architecture
from archway_diagram_compiler.models import Flow, SemanticArchitectureSpec, ServiceNode


def compliance_knowledge_assistant_spec():
    return SemanticArchitectureSpec(
        title="Compliance Knowledge Assistant",
        nodes=[
            ServiceNode(id="cloudfront", name="CloudFront", service="cloudfront"),
            ServiceNode(id="api", name="API Gateway", service="api_gateway", region="us-east-1"),
            ServiceNode(id="cognito", name="Cognito", service="cognito", region="us-east-1"),
            ServiceNode(
                id="assistant_a",
                name="Assistant A",
                service="ecs",
                region="us-east-1",
                vpc_id="app-vpc",
                az="us-east-1a",
                logical_group="Assistant Service",
            ),
            ServiceNode(
                id="assistant",
                name="Assistant Service",
                service="ecs",
                region="us-east-1",
                vpc_id="app-vpc",
                az="us-east-1b",
                logical_group="Assistant Service",
            ),
            ServiceNode(id="bedrock", name="Bedrock", service="bedrock", region="us-east-1"),
            ServiceNode(
                id="documents",
                name="Compliance Document Bucket",
                service="s3",
                region="us-east-1",
                vpc_id="app-vpc",
            ),
            ServiceNode(
                id="s3_endpoint",
                name="S3 Gateway Endpoint",
                service="vpc_endpoint",
                region="us-east-1",
                vpc_id="app-vpc",
                metadata={"target_node_id": "documents"},
            ),
            ServiceNode(id="knowledge_index", name="Knowledge Index", service="kendra", region="us-east-1"),
            ServiceNode(id="secrets", name="Secrets Manager", service="secrets_manager", region="us-east-1"),
            ServiceNode(id="kms", name="KMS", service="kms", region="us-east-1"),
            ServiceNode(id="cloudwatch", name="CloudWatch", service="cloudwatch", region="us-east-1"),
            ServiceNode(id="cloudtrail", name="CloudTrail", service="cloudtrail", region="us-east-1"),
        ],
        flows=[
            Flow(id="f01", source="cloudfront", target="api", label="HTTPS"),
            Flow(id="f02", source="api", target="cognito", label="JWT authorizer"),
            Flow(id="f03", source="api", target="assistant", label="Invoke"),
            Flow(id="f04", source="assistant", target="bedrock", label="RAG prompt"),
            Flow(id="f05", source="assistant", target="s3_endpoint", label="Read documents"),
            Flow(id="f06", source="bedrock", target="knowledge_index", label="Retrieve"),
            Flow(id="f07", source="assistant", target="secrets", label="Read secret"),
            Flow(id="f08", source="secrets", target="kms", label="Decrypt"),
            Flow(id="f09", source="assistant", target="cloudwatch", label="Metrics and logs"),
            Flow(id="f10", source="cloudtrail", target="documents", label="Audit events"),
        ],
    )


def test_compliance_knowledge_assistant_golden(tmp_path):
    bundle = compile_architecture(compliance_knowledge_assistant_spec(), tmp_path, render=False)

    assert bundle.artifact_paths["d2"].exists()
    assert bundle.qa_report.passed
    assert bundle.qa_report.metrics["node_count"] == 25
    assert any(item.code == "moved_outside_vpc" and item.node_id == "documents" for item in bundle.diagnostics)
    assert any(item.code == "endpoint_access_path" for item in bundle.diagnostics)
    assert any(item.code == "collapsed_az_replicas" for item in bundle.diagnostics)
    assert bundle.flow_ledger is not None
    assert not [entry for entry in bundle.flow_ledger.entries if entry.reason is None and entry.status == "omitted_with_reason"]
    assert bundle.layout_models
    assert "bedrock_knowledge_base" in bundle.d2_text
