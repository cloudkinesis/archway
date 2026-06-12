from archway_diagram_compiler.models import Flow, SemanticArchitectureSpec, ServiceNode
from archway_diagram_compiler.normalizer import normalize_spec


def test_moves_non_vpc_service_outside_vpc():
    spec = SemanticArchitectureSpec(
        title="Move Managed Service",
        nodes=[
            ServiceNode(id="api", name="API", service="api_gateway", region="us-east-1"),
            ServiceNode(
                id="s3",
                name="Bucket",
                service="s3",
                region="us-east-1",
                vpc_id="vpc-main",
                subnet_id="subnet-a",
                az="us-east-1a",
            ),
        ],
        flows=[Flow(id="f1", source="api", target="s3")],
    )

    normalized, diagnostics = normalize_spec(spec)

    bucket = next(node for node in normalized.nodes if node.id == "s3")
    assert bucket.scope == "regional_managed_data"
    assert bucket.vpc_id is None
    assert bucket.subnet_id is None
    assert bucket.az is None
    assert any(item.code == "moved_outside_vpc" for item in diagnostics)


def test_collapses_endpoint_into_access_path():
    spec = SemanticArchitectureSpec(
        title="Endpoint",
        nodes=[
            ServiceNode(id="lambda", name="Worker", service="lambda", region="us-east-1", vpc_id="vpc-main"),
            ServiceNode(id="s3", name="Documents", service="s3", region="us-east-1"),
            ServiceNode(
                id="s3_endpoint",
                name="S3 Endpoint",
                service="vpc_endpoint",
                region="us-east-1",
                vpc_id="vpc-main",
                metadata={"target_node_id": "s3"},
            ),
        ],
        flows=[Flow(id="f1", source="lambda", target="s3_endpoint", label="private access")],
    )

    normalized, diagnostics = normalize_spec(spec)

    assert "s3_endpoint" not in {node.id for node in normalized.nodes}
    assert normalized.flows[0].target == "s3"
    assert normalized.flows[0].metadata["endpoint_access_path"] is True
    assert any(item.code == "endpoint_access_path" for item in diagnostics)


def test_collapses_duplicate_az_replicas_unless_active_active():
    spec = SemanticArchitectureSpec(
        title="Replicas",
        nodes=[
            ServiceNode(id="alb", name="ALB", service="load_balancer", region="us-east-1"),
            ServiceNode(
                id="worker_a",
                name="Worker A",
                service="ecs",
                region="us-east-1",
                vpc_id="vpc-main",
                az="us-east-1a",
                logical_group="Worker",
            ),
            ServiceNode(
                id="worker_b",
                name="Worker B",
                service="ecs",
                region="us-east-1",
                vpc_id="vpc-main",
                az="us-east-1b",
                logical_group="Worker",
            ),
        ],
        flows=[
            Flow(id="f1", source="alb", target="worker_a"),
            Flow(id="f2", source="alb", target="worker_b"),
        ],
    )

    normalized, diagnostics = normalize_spec(spec)

    assert {node.id for node in normalized.nodes} == {"alb", "worker_a"}
    worker = next(node for node in normalized.nodes if node.id == "worker_a")
    assert worker.name == "Worker"
    assert worker.az is None
    assert len(normalized.flows) == 1
    assert normalized.flows[0].target == "worker_a"
    assert any(item.code == "collapsed_az_replicas" for item in diagnostics)


def test_rejects_orphan_and_invalid_scope():
    spec = SemanticArchitectureSpec(
        title="Invalid",
        nodes=[
            ServiceNode(id="api", name="API", service="api_gateway", scope="vpc_workload", region="us-east-1"),
            ServiceNode(id="orphan", name="Orphan", service="lambda", region="us-east-1", vpc_id="vpc-main"),
            ServiceNode(id="note", name="Note", service="note", annotation=True),
        ],
        flows=[Flow(id="f1", source="api", target="api")],
    )

    _, diagnostics = normalize_spec(spec)

    assert any(item.code == "invalid_scope" and item.node_id == "api" for item in diagnostics)
    assert any(item.code == "orphan_node" and item.node_id == "orphan" for item in diagnostics)
    assert not any(item.code == "orphan_node" and item.node_id == "note" for item in diagnostics)
