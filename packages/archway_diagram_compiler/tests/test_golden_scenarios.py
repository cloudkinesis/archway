from pathlib import Path
import json

import pytest

from archway_diagram_compiler.compiler import compile_architecture
from archway_diagram_compiler.high_fanout_handler import detect_high_fanout
from archway_diagram_compiler.models import Flow, SemanticArchitectureSpec, ServiceNode
from archway_diagram_compiler.qa import (
    _svg_aspect_ratio,
    _svg_diagonal_connection_count,
    _svg_edge_crossing_count,
    _svg_edge_crosses_node_count,
    _svg_edge_label_overlap_count,
    _svg_node_label_icon_overlap_count,
    _svg_node_overlap_count,
)
from archway_diagram_compiler.renderer import find_d2_executable


def _n(node_id, name, service, **kwargs):
    return ServiceNode(id=node_id, name=name, service=service, **kwargs)


def _f(flow_id, source, target, label=None, edge_type=None, **metadata):
    return Flow(id=flow_id, source=source, target=target, label=label, edge_type=edge_type, metadata=metadata)


def _web_platform(title, compute_service="ecs", data_service="dynamodb"):
    return SemanticArchitectureSpec(
        title=title,
        nodes=[
            _n("user", "User", "external_actor", metadata={"role": "user"}),
            _n("cloudfront", "CloudFront", "cloudfront", region="global"),
            _n("api", "API", "api_gateway", region="us-east-1"),
            _n("workload", "Application Service", compute_service, region="us-east-1", vpc_id="app-vpc"),
            _n("data", "Application Data", data_service, region="us-east-1"),
            _n("cloudwatch", "CloudWatch", "cloudwatch", region="us-east-1"),
        ],
        flows=[
            _f("f1", "user", "cloudfront", "HTTPS request"),
            _f("f2", "cloudfront", "api", "HTTPS"),
            _f("f3", "api", "workload", "private integration", integration="vpc_link"),
            _f("f4", "workload", "data", "write data"),
            _f("f5", "workload", "cloudwatch", "logs and metrics"),
        ],
        metadata={"primary_region": "us-east-1"},
    )


def _serverless_platform(title):
    return SemanticArchitectureSpec(
        title=title,
        nodes=[
            _n("user", "User", "external_actor"),
            _n("api", "API", "api_gateway", region="us-east-1"),
            _n("fn", "Function", "lambda", region="us-east-1"),
            _n("table", "Table", "dynamodb", region="us-east-1"),
            _n("events", "Events", "eventbridge", region="us-east-1"),
        ],
        flows=[
            _f("f1", "user", "api", "HTTPS request"),
            _f("f2", "api", "fn", "invoke"),
            _f("f3", "fn", "table", "write item"),
            _f("f4", "fn", "events", "publish event"),
        ],
    )


def _event_platform(title):
    return SemanticArchitectureSpec(
        title=title,
        nodes=[
            _n("producer", "Producer Service", "ecs", region="us-east-1", vpc_id="event-vpc"),
            _n("queue", "Work Queue", "sqs", region="us-east-1"),
            _n("workflow", "Workflow", "step_functions", region="us-east-1"),
            _n("bus", "Event Bus", "eventbridge", region="us-east-1"),
            _n("topic", "Notifications", "sns", region="us-east-1"),
        ],
        flows=[
            _f("f1", "producer", "queue", "enqueue work"),
            _f("f2", "queue", "workflow", "start workflow"),
            _f("f3", "workflow", "bus", "publish event"),
            _f("f4", "bus", "topic", "notify subscribers"),
        ],
    )


def _rag_platform(title):
    return SemanticArchitectureSpec(
        title=title,
        nodes=[
            _n("user", "User", "external_actor"),
            _n("api", "API", "api_gateway", region="us-east-1"),
            _n("assistant", "Assistant Service", "ecs", region="us-east-1", vpc_id="rag-vpc"),
            _n("bedrock", "Amazon Bedrock", "bedrock", region="us-east-1"),
            _n("kb", "Bedrock Knowledge Base", "bedrock_knowledge_base", region="us-east-1"),
            _n("vector", "Vector Index", "opensearch_serverless", region="us-east-1"),
            _n("docs", "Documents", "s3", region="us-east-1"),
        ],
        flows=[
            _f("f1", "user", "api", "HTTPS request"),
            _f("f2", "api", "assistant", "private integration", integration="vpc_link"),
            _f("f3", "assistant", "kb", "RAG retrieval", edge_type="rag_retrieval"),
            _f("f4", "kb", "vector", "vector retrieval", edge_type="rag_retrieval"),
            _f("f5", "vector", "docs", "source references", edge_type="data_read"),
            _f("f6", "assistant", "bedrock", "invoke model", edge_type="model_invocation"),
        ],
    )


def _data_platform(title):
    return SemanticArchitectureSpec(
        title=title,
        nodes=[
            _n("source", "Source Bucket", "s3", region="us-east-1"),
            _n("workflow", "Processing Workflow", "step_functions", region="us-east-1"),
            _n("table", "Curated Table", "dynamodb", region="us-east-1"),
            _n("events", "Pipeline Events", "eventbridge", region="us-east-1"),
            _n("cloudwatch", "CloudWatch", "cloudwatch", region="us-east-1"),
        ],
        flows=[
            _f("f1", "source", "workflow", "object event"),
            _f("f2", "workflow", "table", "write curated data"),
            _f("f3", "workflow", "events", "publish status"),
            _f("f4", "workflow", "cloudwatch", "logs and metrics"),
        ],
    )


def _simple_web_app():
    return _web_platform("Simple Web App", data_service="rds")


def _serverless_api():
    return _serverless_platform("Serverless API")


def _retail_fulfillment():
    return SemanticArchitectureSpec(
        title="Retail Order Fulfillment",
        nodes=[
            _n("customer", "Customer", "external_actor"),
            _n("api", "Order API", "api_gateway", region="us-east-1"),
            _n("orders", "Order Service", "ecs", region="us-east-1", vpc_id="retail-vpc"),
            _n("queue", "Order Queue", "sqs", region="us-east-1"),
            _n("workflow", "Fulfillment Workflow", "step_functions", region="us-east-1"),
            _n("events", "Order Events", "eventbridge", region="us-east-1"),
            _n("notify", "Customer Notifications", "sns", region="us-east-1"),
        ],
        flows=[
            _f("f1", "customer", "api", "submit order"),
            _f("f2", "api", "orders", "private integration", integration="vpc_link"),
            _f("f3", "orders", "queue", "enqueue fulfillment"),
            _f("f4", "queue", "workflow", "start workflow"),
            _f("f5", "workflow", "events", "publish order event"),
            _f("f6", "events", "notify", "notify customer"),
        ],
    )


def _rag_assistant():
    return _rag_platform("RAG Assistant")


def _streaming_analytics():
    return SemanticArchitectureSpec(
        title="Streaming Analytics",
        nodes=[
            _n("stream", "Clickstream", "kinesis", region="us-east-1"),
            _n("firehose", "Delivery Stream", "firehose", region="us-east-1"),
            _n("glue", "Glue ETL", "glue", region="us-east-1"),
            _n("lake", "Analytics Lake", "s3", region="us-east-1"),
            _n("athena", "Athena Queries", "athena", region="us-east-1"),
        ],
        flows=[
            _f("f1", "stream", "firehose", "stream records"),
            _f("f2", "firehose", "glue", "transform"),
            _f("f3", "glue", "lake", "write parquet"),
            _f("f4", "lake", "athena", "query data"),
        ],
        metadata={"internet_facing": False},
    )


def _iot_ingestion():
    return SemanticArchitectureSpec(
        title="IoT Ingestion",
        nodes=[
            _n("device", "IoT Device", "external_actor"),
            _n("iot", "IoT Core", "iot_core", region="us-east-1"),
            _n("rules", "Rules Engine", "eventbridge", region="us-east-1"),
            _n("stream", "Telemetry Stream", "kinesis", region="us-east-1"),
            _n("table", "Device State", "dynamodb", region="us-east-1"),
        ],
        flows=[
            _f("f1", "device", "iot", "MQTT telemetry"),
            _f("f2", "iot", "rules", "route messages"),
            _f("f3", "rules", "stream", "publish telemetry"),
            _f("f4", "rules", "table", "write state"),
        ],
        metadata={"internet_facing": False},
    )


def _batch_processing():
    return SemanticArchitectureSpec(
        title="Batch Processing",
        nodes=[
            _n("schedule", "Schedule", "eventbridge", region="us-east-1"),
            _n("batch", "Batch Workers", "ecs", region="us-east-1", vpc_id="batch-vpc"),
            _n("input", "Input Bucket", "s3", region="us-east-1"),
            _n("output", "Output Bucket", "s3", region="us-east-1"),
            _n("state", "Job State", "dynamodb", region="us-east-1"),
        ],
        flows=[
            _f("f1", "schedule", "batch", "start job"),
            _f("f2", "batch", "input", "read objects"),
            _f("f3", "batch", "output", "write output"),
            _f("f4", "batch", "state", "write status"),
        ],
        metadata={"internet_facing": False},
    )


def _ml_inference():
    return SemanticArchitectureSpec(
        title="ML Inference Endpoint",
        nodes=[
            _n("client", "Client", "external_actor"),
            _n("api", "Inference API", "api_gateway", region="us-east-1"),
            _n("svc", "Inference Service", "lambda", region="us-east-1"),
            _n("endpoint", "SageMaker Endpoint", "sagemaker", region="us-east-1"),
            _n("artifacts", "Model Artifacts", "s3", region="us-east-1"),
        ],
        flows=[
            _f("f1", "client", "api", "HTTPS"),
            _f("f2", "api", "svc", "invoke"),
            _f("f3", "svc", "endpoint", "invoke endpoint", edge_type="model_invocation"),
            _f("f4", "endpoint", "artifacts", "load model"),
        ],
    )


def _multi_vpc():
    return SemanticArchitectureSpec(
        title="Multi VPC Application",
        nodes=[
            _n("app", "VPC A App", "ecs", region="us-east-1", vpc_id="vpc-a"),
            _n("tgw", "Transit Gateway", "transit_gateway", region="us-east-1"),
            _n("proxy", "RDS Proxy", "rds_proxy", region="us-east-1", vpc_id="vpc-b"),
            _n("db", "Aurora Database", "rds", region="us-east-1"),
        ],
        flows=[
            _f("f1", "app", "tgw", "private route"),
            _f("f2", "tgw", "proxy", "route to data VPC"),
            _f("f3", "proxy", "db", "database connection"),
        ],
        metadata={"internet_facing": False},
    )


def _multi_region_active_passive():
    return SemanticArchitectureSpec(
        title="Multi Region Active Passive",
        nodes=[
            _n("user", "User", "external_actor"),
            _n("dns", "Route 53 Failover", "route53", region="global"),
            _n("api_east", "API East", "api_gateway", region="us-east-1"),
            _n("api_west", "API West", "api_gateway", region="us-west-2"),
            _n("table_east", "Table East", "dynamodb", region="us-east-1"),
            _n("table_west", "Table West", "dynamodb", region="us-west-2"),
        ],
        flows=[
            _f("f1", "user", "dns", "resolve active region"),
            _f("f2", "dns", "api_east", "primary"),
            _f("f3", "dns", "api_west", "failover"),
            _f("f4", "api_east", "table_east", "write state"),
            _f("f5", "api_west", "table_west", "write state"),
        ],
    )


def _hybrid_connectivity():
    return SemanticArchitectureSpec(
        title="Hybrid Connectivity",
        nodes=[
            _n("onprem", "On-prem System", "external_actor"),
            _n("dx", "Direct Connect", "direct_connect", region="us-east-1"),
            _n("vpn", "VPN Backup", "vpn", region="us-east-1"),
            _n("tgw", "Transit Gateway", "transit_gateway", region="us-east-1"),
            _n("app", "Private App", "ecs", region="us-east-1", vpc_id="hybrid-vpc"),
        ],
        flows=[
            _f("f1", "onprem", "dx", "private circuit"),
            _f("f2", "onprem", "vpn", "backup tunnel"),
            _f("f3", "dx", "tgw", "route"),
            _f("f4", "vpn", "tgw", "backup route"),
            _f("f5", "tgw", "app", "private access"),
        ],
        metadata={"internet_facing": False},
    )


def _file_processing():
    return SemanticArchitectureSpec(
        title="File Processing",
        nodes=[_n("upload", "Upload Bucket", "s3", region="us-east-1"), _n("events", "Object Events", "eventbridge", region="us-east-1"), _n("fn", "Validator", "lambda", region="us-east-1"), _n("workflow", "Processing Workflow", "step_functions", region="us-east-1"), _n("out", "Processed Output", "s3", region="us-east-1")],
        flows=[_f("f1", "upload", "events", "object created"), _f("f2", "events", "fn", "validate file"), _f("f3", "fn", "workflow", "start workflow"), _f("f4", "workflow", "out", "write output")],
        metadata={"internet_facing": False},
    )


def _security_pipeline():
    return SemanticArchitectureSpec(
        title="Security Pipeline",
        nodes=[_n("trail", "CloudTrail", "cloudtrail", region="us-east-1"), _n("events", "Security Events", "eventbridge", region="us-east-1"), _n("fn", "Finding Processor", "lambda", region="us-east-1"), _n("hub", "Security Hub", "security_hub", region="us-east-1"), _n("topic", "Security Alerts", "sns", region="us-east-1")],
        flows=[_f("f1", "trail", "events", "API activity"), _f("f2", "events", "fn", "process finding"), _f("f3", "fn", "hub", "import finding"), _f("f4", "hub", "topic", "alert")],
        metadata={"internet_facing": False},
    )


def _observability_pipeline():
    return SemanticArchitectureSpec(
        title="Observability Pipeline",
        nodes=[_n("app", "Application", "ecs", region="us-east-1", vpc_id="obs-vpc"), _n("cw", "CloudWatch", "cloudwatch", region="us-east-1"), _n("xray", "X-Ray", "xray", region="us-east-1"), _n("alarm", "Alarm Topic", "sns", region="us-east-1")],
        flows=[_f("f1", "app", "cw", "logs and metrics"), _f("f2", "app", "xray", "traces"), _f("f3", "cw", "alarm", "alarm notification")],
        metadata={"internet_facing": False},
    )


def _data_lake_etl():
    return SemanticArchitectureSpec(
        title="Data Lake ETL",
        nodes=[_n("raw", "Raw S3", "s3", region="us-east-1"), _n("glue", "Glue Jobs", "glue", region="us-east-1"), _n("curated", "Curated S3", "s3", region="us-east-1"), _n("athena", "Athena", "athena", region="us-east-1"), _n("redshift", "Redshift", "redshift", region="us-east-1")],
        flows=[_f("f1", "raw", "glue", "read raw data"), _f("f2", "glue", "curated", "write curated data"), _f("f3", "curated", "athena", "query"), _f("f4", "curated", "redshift", "load warehouse")],
        metadata={"internet_facing": False},
    )


def _private_saas():
    return SemanticArchitectureSpec(
        title="Private SaaS Integration",
        nodes=[_n("app", "VPC Workload", "ecs", region="us-east-1", vpc_id="saas-vpc"), _n("endpoint", "PrivateLink Endpoint", "vpc_endpoint", region="us-east-1", vpc_id="saas-vpc", metadata={"target_node_id": "saas"}), _n("saas", "SaaS Endpoint Service", "privatelink_service", region="us-east-1")],
        flows=[_f("f1", "app", "endpoint", "private SaaS call"), _f("f2", "endpoint", "saas", "endpoint service")],
        metadata={"internet_facing": False},
    )


def _shared_database_hub():
    nodes = [_n(f"svc_{i}", f"Service {i}", "ecs", region="us-east-1", vpc_id="hub-vpc") for i in range(8)]
    nodes.append(_n("db", "Shared Aurora", "rds", region="us-east-1"))
    return SemanticArchitectureSpec(title="Shared Database Hub", nodes=nodes, flows=[_f(f"f{i}", f"svc_{i}", "db", "write data") for i in range(8)], metadata={"internet_facing": False})


def _wide_fanout():
    targets = ["dynamodb", "sqs", "sns", "eventbridge", "s3", "secrets_manager", "cloudwatch", "kinesis", "glue", "sagemaker"]
    nodes = [_n("svc", "Fanout Service", "ecs", region="us-east-1", vpc_id="fanout-vpc")] + [_n(f"dep_{i}", target.title(), target, region="us-east-1") for i, target in enumerate(targets)]
    return SemanticArchitectureSpec(title="Wide Fanout", nodes=nodes, flows=[_f(f"f{i}", "svc", f"dep_{i}", f"use {target}") for i, target in enumerate(targets)], metadata={"internet_facing": False})


def _deep_chain():
    nodes = [_n(f"svc_{i}", f"Service {i}", "lambda", region="us-east-1") for i in range(10)]
    return SemanticArchitectureSpec(title="Deep Service Chain", nodes=nodes, flows=[_f(f"f{i}", f"svc_{i}", f"svc_{i+1}", "invoke") for i in range(9)], metadata={"internet_facing": False})


def _unknown_fallback():
    services = ["kinesis", "glue", "sagemaker", "rds_proxy", "transit_gateway", "made_up_aws_service"]
    nodes = [_n("app", "Application", "ecs", region="us-east-1", vpc_id="fallback-vpc")] + [_n(f"svc_{i}", service.title(), service, region="us-east-1") for i, service in enumerate(services)]
    return SemanticArchitectureSpec(title="Unknown AWS Fallback", nodes=nodes, flows=[_f(f"f{i}", "app", f"svc_{i}", f"use {service}") for i, service in enumerate(services)], metadata={"internet_facing": False})


SCENARIOS = [
    ("simple_web_app", _simple_web_app()),
    ("serverless_api", _serverless_api()),
    ("retail_order_fulfillment", _retail_fulfillment()),
    ("rag_assistant", _rag_assistant()),
    ("streaming_analytics", _streaming_analytics()),
    ("iot_ingestion", _iot_ingestion()),
    ("batch_processing", _batch_processing()),
    ("ml_inference_endpoint", _ml_inference()),
    ("multi_vpc_app", _multi_vpc()),
    ("multi_region_active_passive", _multi_region_active_passive()),
    ("hybrid_connectivity", _hybrid_connectivity()),
    ("file_processing", _file_processing()),
    ("security_pipeline", _security_pipeline()),
    ("observability_pipeline", _observability_pipeline()),
    ("data_lake_etl", _data_lake_etl()),
    ("private_saas_integration", _private_saas()),
    ("shared_database_hub", _shared_database_hub()),
    ("wide_fanout", _wide_fanout()),
    ("deep_chain", _deep_chain()),
    ("unknown_fallback", _unknown_fallback()),
]

SCENARIO_EXPECTATIONS = {
    "streaming_analytics": {"services": {"kinesis", "firehose", "glue", "athena"}},
    "iot_ingestion": {"services": {"iot_core"}},
    "ml_inference_endpoint": {"services": {"sagemaker"}},
    "multi_vpc_app": {"services": {"transit_gateway", "rds_proxy"}},
    "multi_region_active_passive": {"views": {"multi_region_view"}},
    "hybrid_connectivity": {"services": {"direct_connect", "vpn", "transit_gateway"}},
    "private_saas_integration": {"services": {"privatelink_service"}},
    "shared_database_hub": {"layout_labels": {"Shared data access"}},
    "wide_fanout": {"layout_labels": {"Business data writes", "Service dependencies"}},
    "unknown_fallback": {"fallback_nodes": {"svc_5"}},
}


@pytest.mark.parametrize(("scenario_id", "spec"), SCENARIOS)
def test_golden_scenario_properties(tmp_path, scenario_id, spec):
    bundle = compile_architecture(spec, Path(tmp_path) / scenario_id, render=False)

    assert bundle.qa_report.passed
    view_names = {view.name for view in bundle.views}
    assert "production_logical_service_flow" in view_names
    if "network_private_connectivity" not in view_names:
        render_plan = json.loads(bundle.artifact_paths["render_plan"].read_text())
        assert any(view["view_id"] == "network_private_connectivity" for view in render_plan["omitted_views"])
    assert bundle.flow_ledger is not None
    assert {entry.flow_id for entry in bundle.flow_ledger.entries} == {flow.id for flow in bundle.normalized_spec.flows}
    assert not [entry for entry in bundle.flow_ledger.entries if entry.status == "omitted_with_reason" and not entry.reason]
    assert not [diagnostic for diagnostic in bundle.diagnostics if diagnostic.code == "logical_orphan_node"]
    assert not [diagnostic for diagnostic in bundle.diagnostics if diagnostic.code == "managed_service_inside_vpc"]
    assert not [
        finding
        for layout in bundle.layout_models
        for finding in detect_high_fanout(layout)
    ]
    assert bundle.artifact_paths["flow_ledger"].exists()
    assert bundle.artifact_paths["layout_model"].exists()
    assert bundle.artifact_paths["render_plan"].exists()
    assert bundle.artifact_paths["placement_explanations"].exists()
    expectations = SCENARIO_EXPECTATIONS.get(scenario_id, {})
    if expectations.get("services"):
        assert set(expectations["services"]).issubset({node.service for node in bundle.normalized_spec.nodes})
    if expectations.get("views"):
        assert set(expectations["views"]).issubset({view.name for view in bundle.views})
    if expectations.get("fallback_nodes"):
        assert set(expectations["fallback_nodes"]).issubset(
            {diagnostic.node_id for diagnostic in bundle.diagnostics if diagnostic.code == "aws_service_catalog_fallback"}
        )
    if expectations.get("layout_labels"):
        assert set(expectations["layout_labels"]).issubset(
            {node.label for layout in bundle.layout_models for node in layout.nodes}
        )


def test_golden_scenario_determinism(tmp_path):
    spec = _rag_platform("Deterministic RAG Assistant")
    first = compile_architecture(spec, Path(tmp_path) / "first", render=False)
    second = compile_architecture(spec, Path(tmp_path) / "second", render=False)

    assert first.views[0].d2_text == second.views[0].d2_text
    assert first.artifact_paths["flow_ledger"].read_text() == second.artifact_paths["flow_ledger"].read_text()


def test_rendered_svg_determinism(tmp_path):
    if find_d2_executable() is None:
        pytest.skip("D2 executable is not available for rendered determinism test")
    spec = _serverless_platform("Rendered Deterministic Serverless API")

    first = compile_architecture(spec, Path(tmp_path) / "first", render=True, render_formats=("svg",))
    second = compile_architecture(spec, Path(tmp_path) / "second", render=True, render_formats=("svg",))

    first_svg = first.views[0].artifact_paths["svg"].read_text(encoding="utf-8", errors="ignore")
    second_svg = second.views[0].artifact_paths["svg"].read_text(encoding="utf-8", errors="ignore")
    assert _normalize_svg_for_determinism(first_svg) == _normalize_svg_for_determinism(second_svg)


@pytest.mark.parametrize(("scenario_id", "spec"), SCENARIOS[:10])
def test_rendered_golden_scenarios_have_visual_quality(tmp_path, scenario_id, spec):
    if find_d2_executable() is None:
        pytest.skip("D2 executable is not available for rendered golden tests")

    bundle = compile_architecture(
        spec,
        Path(tmp_path) / scenario_id,
        render=True,
        render_formats=("svg",),
    )

    assert bundle.qa_report.passed
    for view in bundle.views:
        svg_path = view.artifact_paths.get("svg")
        assert svg_path is not None and svg_path.exists()
        aspect_ratio = _svg_aspect_ratio(svg_path)
        assert aspect_ratio is not None
        assert 0.35 <= aspect_ratio <= 3.5
        assert _svg_diagonal_connection_count(svg_path) == 0
        assert _svg_node_overlap_count(svg_path) == 0
        assert _svg_edge_label_overlap_count(svg_path) == 0
        assert _svg_edge_crosses_node_count(svg_path) == 0
        assert _svg_node_label_icon_overlap_count(svg_path) == 0
        if view.name == "production_logical_service_flow":
            crossing_limit = 8
        elif view.name in {"fanout_detail_view", "async_flow_view"}:
            crossing_limit = 64
        else:
            crossing_limit = 16
        assert _svg_edge_crossing_count(svg_path) <= crossing_limit


def _normalize_svg_for_determinism(svg_text: str) -> str:
    import re

    svg_text = re.sub(r"d2-\d+", "d2-ID", svg_text)
    svg_text = re.sub(r"mk-d2-ID-\d+", "mk-d2-ID", svg_text)
    svg_text = re.sub(r"url\\(#mk-d2-ID-?\\d*\\)", "url(#mk-d2-ID)", svg_text)
    svg_text = re.sub(r"url\\(#d2-ID\\)", "url(#d2-ID)", svg_text)
    return svg_text
