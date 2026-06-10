from pathlib import Path
from hashlib import sha256
import json

from archway_diagram_compiler.aws_provider import AWS_PROVIDER
from archway_diagram_compiler.artifact_hygiene import (
    copy_bundle_artifacts_flat,
    remove_flat_artifact_aliases,
    validate_flat_artifact_dir,
)
from archway_diagram_compiler.compiler import compile_architecture
from archway_diagram_compiler.flow_classifier import classify_flow
from archway_diagram_compiler.high_fanout_handler import detect_high_fanout
from archway_diagram_compiler.icons import package_icon_dir, service_icon_filename
from archway_diagram_compiler.models import Flow, LayoutEdge, LayoutGroup, LayoutLane, LayoutModel, LayoutNode, SemanticArchitectureSpec, ServiceNode
from archway_diagram_compiler.normalizer import normalize_spec
from archway_diagram_compiler.quality_config import DEFAULT_QUALITY_CONFIG
from archway_diagram_compiler.qa import (
    _svg_edge_crossing_count,
    _svg_edge_crosses_node_count,
    _svg_edge_label_overlap_count,
    _svg_node_label_icon_overlap_count,
)
from archway_diagram_compiler.renderer import find_d2_executable
from archway_diagram_compiler.visual_layout_qa import run_visual_layout_qa
from examples.retail_order_fulfillment import retail_order_fulfillment_spec


def test_aws_provider_catalog_places_lambda_by_vpc_context():
    regional = ServiceNode(id="fn", name="Function", service="lambda")
    vpc_attached = ServiceNode(id="fn", name="Function", service="lambda", vpc_id="app-vpc")

    assert AWS_PROVIDER.get_placement_scope("lambda", regional) == "regional_compute"
    assert AWS_PROVIDER.get_placement_scope("lambda", vpc_attached) == "vpc_resident"
    assert AWS_PROVIDER.get_endpoint_type("dynamodb") == "gateway"
    assert AWS_PROVIDER.get_endpoint_type("sqs") == "interface"


def test_aws_provider_catalog_places_vpc_resident_data_services_by_context():
    vpc_services = ["rds", "aurora", "redshift", "msk", "elasticache", "efs", "rds_proxy"]

    for service in vpc_services:
        node = ServiceNode(id="data", name="Data", service=service, region="us-east-1", vpc_id="data-vpc")
        normalized, diagnostics = normalize_spec(SemanticArchitectureSpec(title=service, nodes=[node], flows=[]))
        data_node = next(item for item in normalized.nodes if item.id == "data")

        assert data_node.scope == "vpc_resident"
        assert data_node.vpc_id == "data-vpc"
        assert not [diagnostic for diagnostic in diagnostics if diagnostic.code == "moved_outside_vpc"]


def test_flow_classifier_assigns_first_class_edge_types():
    service = ServiceNode(id="svc", name="Order Service", service="ecs", vpc_id="retail-vpc")
    table = ServiceNode(id="orders", name="Orders", service="dynamodb")
    queue = ServiceNode(id="queue", name="Queue", service="sqs")
    secrets = ServiceNode(id="secrets", name="Secrets", service="secrets_manager")

    assert classify_flow(Flow(id="f1", source="svc", target="orders", label="write order"), service, table, AWS_PROVIDER).edge_type == "data_write"
    assert classify_flow(Flow(id="f2", source="svc", target="queue", label="enqueue fulfillment"), service, queue, AWS_PROVIDER).edge_type == "async"
    assert classify_flow(Flow(id="f3", source="svc", target="secrets", label="read secret"), service, secrets, AWS_PROVIDER).edge_type == "secret_access"


def test_v2_artifacts_and_flow_ledger_are_written(tmp_path):
    bundle = compile_architecture(retail_order_fulfillment_spec(), Path(tmp_path), render=False)
    expected_artifacts = {
        "flow_ledger",
        "render_plan",
        "layout_model",
        "qa_report",
        "placement_explanations",
    }

    assert expected_artifacts.issubset(bundle.artifact_paths)
    for name in expected_artifacts:
        assert bundle.artifact_paths[name].exists()
    assert bundle.flow_ledger is not None
    assert {entry.flow_id for entry in bundle.flow_ledger.entries} == {flow.id for flow in bundle.normalized_spec.flows}
    assert not [entry for entry in bundle.flow_ledger.entries if entry.status == "omitted_with_reason" and not entry.reason]
    assert bundle.layout_models
    assert bundle.qa_report.passed


def test_no_duplicate_user_visible_artifacts(tmp_path):
    bundle = compile_architecture(retail_order_fulfillment_spec(), Path(tmp_path), render=True, render_formats=("svg",))
    visible = bundle.user_visible_artifacts
    keys = [(artifact.view_id, artifact.format) for artifact in visible]
    hashes = {}

    assert bundle.qa_report.passed
    assert visible
    assert len(keys) == len(set(keys))
    assert all(artifact.name == f"{artifact.view_id}.{artifact.format}" for artifact in visible)
    assert not any("__svg.svg" in artifact.name or artifact.name.endswith("_svg.svg") for artifact in visible)
    for artifact in visible:
        digest = sha256(artifact.path.read_bytes()).hexdigest()
        assert digest not in hashes
        hashes[digest] = artifact.path


def test_endpoint_access_group_label_is_concise(tmp_path):
    bundle = compile_architecture(retail_order_fulfillment_spec(), Path(tmp_path), render=False)
    rendered_text = "\n".join(view.d2_text for view in bundle.views)
    labels = {node.label for layout in bundle.layout_models for node in layout.nodes}

    assert "Private AI service access / Parallel access paths" not in rendered_text
    assert "Private data access / Parallel access paths" not in rendered_text
    assert {"Private AWS service access", "Private data access"} & labels


def test_flat_artifact_export_removes_stale_aliases(tmp_path):
    bundle = compile_architecture(retail_order_fulfillment_spec(), Path(tmp_path) / "compile", render=True, render_formats=("svg",))
    flat = Path(tmp_path) / "flat"
    flat.mkdir()
    stale = flat / "retail_order_fulfillment__network_private_connectivity 2.svg"
    stale.write_text("<svg>stale missing endpoint targets</svg>", encoding="utf-8")

    diagnostics = copy_bundle_artifacts_flat(bundle, "retail_order_fulfillment", flat)

    assert not diagnostics
    assert not stale.exists()
    assert (flat / "retail_order_fulfillment__network_private_connectivity.svg").exists()
    assert not list(flat.glob("* 2.*"))
    assert not list(flat.glob("*(2).*"))


def test_flat_artifact_validation_detects_conflicting_aliases(tmp_path):
    flat = Path(tmp_path)
    (flat / "scenario__network_private_connectivity.svg").write_text("<svg>good</svg>", encoding="utf-8")
    (flat / "scenario__network_private_connectivity 2.svg").write_text("<svg>stale</svg>", encoding="utf-8")

    diagnostics = validate_flat_artifact_dir(flat)

    assert any(diagnostic.code == "conflicting_artifact_error" for diagnostic in diagnostics)


def test_flat_artifact_alias_cleanup_removes_duplicate_names(tmp_path):
    flat = Path(tmp_path)
    content = "<svg>same</svg>"
    (flat / "scenario__production_logical_service_flow.svg").write_text(content, encoding="utf-8")
    (flat / "scenario__production_logical_service_flow(2).svg").write_text(content, encoding="utf-8")
    (flat / "scenario__production_logical_service_flow__svg.svg").write_text(content, encoding="utf-8")

    diagnostics = validate_flat_artifact_dir(flat)
    remove_flat_artifact_aliases(flat)

    assert not any(diagnostic.code == "conflicting_artifact_error" for diagnostic in diagnostics)
    assert [path.name for path in flat.iterdir()] == ["scenario__production_logical_service_flow.svg"]


def test_conditional_views_and_high_fanout_grouping_are_generic(tmp_path):
    bundle = compile_architecture(retail_order_fulfillment_spec(), Path(tmp_path), render=False)
    view_names = {view.name for view in bundle.views}

    assert "async_flow_view" in view_names
    assert "security_observability_controls" in view_names

    logical_layout = next(layout for layout in bundle.layout_models if layout.view_id == "production_logical_service_flow")
    group_nodes = {node.label for node in logical_layout.nodes if node.is_virtual and node.metadata.get("fanout_group")}
    assert "Business data writes" in group_nodes
    assert "Async fulfillment" in group_nodes
    assert {
        node.subtitle
        for node in logical_layout.nodes
        if node.metadata.get("fanout_group") and node.metadata.get("parallel_dependency_group")
    } == {None}
    assert not detect_high_fanout([layout for layout in bundle.layout_models if layout.view_id == "production_logical_service_flow"][0])


def test_aws_catalog_fallback_degrades_gracefully(tmp_path):
    services = ["kinesis", "glue", "sagemaker", "rds_proxy", "transit_gateway", "app_runner", "made_up_aws_service"]
    spec = SemanticArchitectureSpec(
        title="Fallback AWS Services",
        nodes=[
            ServiceNode(id="app", name="App", service="ecs", region="us-east-1", vpc_id="app-vpc"),
            *[
                ServiceNode(id=f"svc_{index}", name=service.replace("_", " ").title(), service=service, region="us-east-1")
                for index, service in enumerate(services)
            ],
        ],
        flows=[
            Flow(id=f"f{index}", source="app", target=f"svc_{index}", label=f"use {service}")
            for index, service in enumerate(services)
        ],
    )

    normalized, diagnostics = normalize_spec(spec)
    bundle = compile_architecture(spec, Path(tmp_path), render=False)

    assert not [diagnostic for diagnostic in diagnostics if diagnostic.code == "unknown_service"]
    assert {diagnostic.node_id for diagnostic in diagnostics if diagnostic.code == "aws_service_catalog_fallback"} == {"svc_6"}
    assert {node.service for node in normalized.nodes}.issuperset(set(services))
    assert bundle.qa_report.passed


def test_broader_aws_catalog_uses_real_packaged_icons(tmp_path):
    expected_icons = {
        "kinesis": "kinesis.svg",
        "firehose": "firehose.svg",
        "msk": "msk.svg",
        "rds": "rds.svg",
        "rds_proxy": "rds.svg",
        "glue": "glue.svg",
        "athena": "athena.svg",
        "redshift": "redshift.svg",
        "sagemaker": "sagemaker.svg",
        "app_runner": "app_runner.svg",
        "appsync": "appsync.svg",
        "elasticache": "elasticache.svg",
        "transit_gateway": "transit_gateway.svg",
        "direct_connect": "direct_connect.svg",
        "vpn": "vpn.svg",
        "nat_gateway": "transit_gateway.svg",
        "iot_core": "iot_core.svg",
        "xray": "xray.svg",
        "security_hub": "security_hub.svg",
        "privatelink_service": "privatelink.svg",
    }

    icon_dir = package_icon_dir()
    for service, filename in expected_icons.items():
        assert service_icon_filename(service) == filename
        assert (icon_dir / filename).exists()
        assert AWS_PROVIDER.get_icon(service).path == filename

    spec = SemanticArchitectureSpec(
        title="Broad AWS Icon Coverage",
        nodes=[
            ServiceNode(id="app", name="App", service="ecs", region="us-east-1", vpc_id="icon-vpc"),
            ServiceNode(id="stream", name="Stream", service="kinesis", region="us-east-1"),
            ServiceNode(id="etl", name="ETL", service="glue", region="us-east-1"),
            ServiceNode(id="model", name="Model Endpoint", service="sagemaker", region="us-east-1"),
            ServiceNode(id="network", name="Transit", service="transit_gateway", region="us-east-1"),
        ],
        flows=[
            Flow(id="f1", source="app", target="stream", label="publish stream"),
            Flow(id="f2", source="stream", target="etl", label="process"),
            Flow(id="f3", source="etl", target="model", label="train model"),
            Flow(id="f4", source="app", target="network", label="route traffic"),
        ],
    )
    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    d2_text = bundle.views[0].d2_text

    assert bundle.qa_report.passed
    assert "kinesis.svg" in d2_text
    assert "glue.svg" in d2_text
    assert "sagemaker.svg" in d2_text
    assert "transit_gateway.svg" in d2_text


def test_shared_database_with_many_writers_is_repaired_not_rejected(tmp_path):
    spec = SemanticArchitectureSpec(
        title="Shared Database Hub",
        nodes=[
            *[
                ServiceNode(
                    id=f"svc_{index}",
                    name=f"Writer {index}",
                    service="ecs",
                    region="us-east-1",
                    vpc_id="hub-vpc",
                )
                for index in range(8)
            ],
            ServiceNode(id="orders", name="Shared Orders DB", service="dynamodb", region="us-east-1"),
        ],
        flows=[
            Flow(id=f"f{index}", source=f"svc_{index}", target="orders", label="write order")
            for index in range(8)
        ],
        metadata={"internet_facing": False},
    )

    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    logical_layout = next(layout for layout in bundle.layout_models if layout.view_id == "production_logical_service_flow")

    assert bundle.qa_report.passed
    assert not [diagnostic for diagnostic in bundle.diagnostics if diagnostic.code == "too_many_incoming_edges"]
    assert any(node.label == "Shared data access" for node in logical_layout.nodes)


def test_wide_fanout_wraps_targets_across_lanes(tmp_path):
    spec = SemanticArchitectureSpec(
        title="Wide Event Fanout",
        nodes=[
            ServiceNode(id="publisher", name="Event Publisher", service="ecs", region="us-east-1", vpc_id="events-vpc"),
            *[
                ServiceNode(id=f"target_{index}", name=f"Subscriber {index}", service="lambda", region="us-east-1")
                for index in range(10)
            ],
        ],
        flows=[
            Flow(id=f"fanout_{index}", source="publisher", target=f"target_{index}", label="notify subscriber")
            for index in range(10)
        ],
        metadata={"internet_facing": False},
    )

    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    logical_layout = next(layout for layout in bundle.layout_models if layout.view_id == "production_logical_service_flow")

    assert bundle.qa_report.passed
    assert any(node.label == "Lambda workers ×10" for node in logical_layout.nodes)
    assert "fanout_detail_view" in {view.name for view in bundle.views}
    assert not [diagnostic for diagnostic in bundle.diagnostics if diagnostic.code in {"diagram_aspect_ratio_too_narrow", "too_many_edge_crossings"}]


def test_homogeneous_lambda_fanout_is_summarized_and_ledgered(tmp_path):
    spec = _homogeneous_fanout_spec(
        title="Orchestrator Lambda Fanout",
        source_service="step_functions",
        source_name="Orchestrator",
        target_service="lambda",
        target_name="Worker",
        count=12,
        label="invoke worker",
    )

    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    logical_layout = next(layout for layout in bundle.layout_models if layout.view_id == "production_logical_service_flow")
    ledger_entries = [entry for entry in bundle.flow_ledger.entries if entry.source == "source"]

    assert bundle.qa_report.passed
    assert "fanout_detail_view" in {view.name for view in bundle.views}
    assert "network_private_connectivity" not in {view.name for view in bundle.views}
    assert any(node.label == "Lambda workers ×12" for node in logical_layout.nodes)
    detail_layout = next(layout for layout in bundle.layout_models if layout.view_id == "fanout_detail_view")
    assert {lane.label for lane in detail_layout.lanes if lane.id.startswith("fanout_targets_")} == {
        "Lambda targets 1-4",
        "Lambda targets 5-8",
        "Lambda targets 9-12",
    }
    lane_contents = {
        lane.id: [node.id for node in sorted(detail_layout.nodes, key=lambda item: item.rank) if node.lane_id == lane.id]
        for lane in detail_layout.lanes
        if lane.id.startswith("fanout_targets_")
    }
    assert lane_contents["fanout_targets_1"] == ["target_0", "target_1", "target_2", "target_3"]
    assert lane_contents["fanout_targets_3"] == ["target_8", "target_9", "target_10", "target_11"]
    assert all(entry.status == "collapsed_into_group" for entry in ledger_entries)
    assert {entry.group_id for entry in ledger_entries} == {"source_lambda_fanout_group"}
    assert {entry.reason for entry in ledger_entries} == {"homogeneous fan-out summarized to reduce crossings"}
    assert {entry.view_id for entry in ledger_entries} == {"production_logical_service_flow"}


def test_homogeneous_sns_to_sqs_fanout_is_summarized(tmp_path):
    spec = _homogeneous_fanout_spec(
        title="SNS Subscriber Fanout",
        source_service="sns",
        source_name="Order Topic",
        target_service="sqs",
        target_name="Subscriber Queue",
        count=12,
        label="deliver message",
    )

    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    logical_layout = next(layout for layout in bundle.layout_models if layout.view_id == "production_logical_service_flow")

    assert bundle.qa_report.passed
    assert any(node.label == "SQS subscriber queues ×12" for node in logical_layout.nodes)
    assert "fanout_detail_view" in {view.name for view in bundle.views}
    assert "async_flow_view" not in {view.name for view in bundle.views}
    assert "network_private_connectivity" not in {view.name for view in bundle.views}


def test_homogeneous_eventbridge_to_lambda_fanout_is_summarized(tmp_path):
    spec = _homogeneous_fanout_spec(
        title="EventBridge Target Fanout",
        source_service="eventbridge",
        source_name="Domain Event Bus",
        target_service="lambda",
        target_name="Event Target",
        count=12,
        label="route event",
    )

    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    logical_layout = next(layout for layout in bundle.layout_models if layout.view_id == "production_logical_service_flow")

    assert bundle.qa_report.passed
    assert any(node.label == "Event targets ×12" for node in logical_layout.nodes)
    assert "fanout_detail_view" in {view.name for view in bundle.views}
    assert "async_flow_view" not in {view.name for view in bundle.views}
    assert "network_private_connectivity" not in {view.name for view in bundle.views}


def test_homogeneous_step_functions_map_fanout_is_summarized(tmp_path):
    spec = _homogeneous_fanout_spec(
        title="Step Functions Map Fanout",
        source_service="step_functions",
        source_name="Map State",
        target_service="ecs",
        target_name="Worker Task",
        count=16,
        label="run task",
        target_metadata={"role": "worker_task"},
    )

    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    logical_layout = next(layout for layout in bundle.layout_models if layout.view_id == "production_logical_service_flow")

    assert bundle.qa_report.passed
    assert any(node.label == "Parallel worker tasks ×16" for node in logical_layout.nodes)
    assert "fanout_detail_view" in {view.name for view in bundle.views}
    assert "network_private_connectivity" not in {view.name for view in bundle.views}
    detail_layout = next(layout for layout in bundle.layout_models if layout.view_id == "fanout_detail_view")
    assert "Worker tasks 1-4" in {lane.label for lane in detail_layout.lanes}


def test_rendered_homogeneous_fanout_primary_view_stays_clean(tmp_path):
    if find_d2_executable() is None:
        return
    spec = _homogeneous_fanout_spec(
        title="Rendered Homogeneous Fanout",
        source_service="sns",
        source_name="Notification Topic",
        target_service="sqs",
        target_name="Subscriber Queue",
        count=12,
        label="deliver message",
    )

    bundle = compile_architecture(spec, Path(tmp_path), render=True, render_formats=("svg",))
    logical_view = next(view for view in bundle.views if view.name == "production_logical_service_flow")
    svg_path = logical_view.artifact_paths["svg"]
    d2_text = logical_view.d2_text.lower()

    assert bundle.qa_report.passed
    assert _svg_edge_crossing_count(svg_path) <= 8
    assert _svg_edge_label_overlap_count(svg_path) == 0
    assert _svg_node_label_icon_overlap_count(svg_path) == 0
    assert all(internal not in d2_text for internal in ["parallel branch", "synthetic", "repair node", "dependency branch"])


def test_rendered_homogeneous_fanout_detail_view_stays_readable(tmp_path):
    if find_d2_executable() is None:
        return
    spec = _homogeneous_fanout_spec(
        title="Rendered Fanout Detail",
        source_service="eventbridge",
        source_name="EventBridge Bus",
        target_service="lambda",
        target_name="Event Target",
        count=12,
        label="route event",
    )

    bundle = compile_architecture(spec, Path(tmp_path), render=True, render_formats=("svg",))
    detail_view = next(view for view in bundle.views if view.name == "fanout_detail_view")
    svg_path = detail_view.artifact_paths["svg"]
    detail_layout = next(layout for layout in bundle.layout_models if layout.view_id == "fanout_detail_view")

    assert bundle.qa_report.passed
    assert _svg_edge_crossing_count(svg_path) <= DEFAULT_QUALITY_CONFIG.fanout_detail_crossing_max_12
    assert _svg_edge_label_overlap_count(svg_path) == 0
    assert _svg_edge_crosses_node_count(svg_path) == 0
    assert {lane.label for lane in detail_layout.lanes if lane.id.startswith("fanout_targets_")} == {
        "Lambda targets 1-4",
        "Lambda targets 5-8",
        "Lambda targets 9-12",
    }
    assert detail_layout.parallel_groups
    assert all(group.preferred_direction == "left_to_right" for group in detail_layout.parallel_groups)


def test_parallel_endpoint_group_is_not_vertical_chain(tmp_path):
    spec = SemanticArchitectureSpec(
        title="Parallel Endpoint Access",
        nodes=[
            ServiceNode(id="app", name="Private Assistant", service="ecs", region="us-east-1", vpc_id="app-vpc"),
            ServiceNode(id="cloudwatch", name="CloudWatch Logs", service="cloudwatch", region="us-east-1"),
            ServiceNode(id="orders", name="Orders Table", service="dynamodb", region="us-east-1"),
            ServiceNode(id="secrets", name="Secrets Manager", service="secrets_manager", region="us-east-1"),
            ServiceNode(id="bedrock", name="Bedrock Model", service="bedrock", region="us-east-1"),
            ServiceNode(id="vector", name="OpenSearch Vector Index", service="opensearch_serverless", region="us-east-1"),
            ServiceNode(id="docs", name="Documents Bucket", service="s3", region="us-east-1"),
        ],
        flows=[
            Flow(id="f1", source="app", target="cloudwatch", label="logs and metrics"),
            Flow(id="f2", source="app", target="orders", label="write order"),
            Flow(id="f3", source="app", target="secrets", label="read secret"),
            Flow(id="f4", source="app", target="bedrock", label="invoke model"),
            Flow(id="f5", source="app", target="vector", label="vector search"),
            Flow(id="f6", source="app", target="docs", label="read documents"),
        ],
        metadata={"internet_facing": False},
    )

    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    network = next(layout for layout in bundle.layout_models if layout.view_id == "network_private_connectivity")
    labels = {node.label for node in network.nodes}
    endpoint_nodes = [node for node in network.nodes if node.service == "vpc_endpoint"]
    endpoint_chains = [
        edge for edge in network.edges
        if _node_service(network, edge.source) == "vpc_endpoint" and _node_service(network, edge.target) == "vpc_endpoint"
    ]

    assert bundle.qa_report.passed
    assert {"Private AWS service access", "Private AI service access", "Private data access"} & labels
    assert network.parallel_groups
    assert any(group.group_type == "endpoint_access_group" for group in network.parallel_groups)
    assert not endpoint_chains
    assert len(endpoint_nodes) >= 5
    for endpoint in endpoint_nodes:
        assert _endpoint_has_direct_target(network, endpoint.id), endpoint.label


def test_retail_network_endpoint_targets_are_directly_visible(tmp_path):
    bundle = compile_architecture(retail_order_fulfillment_spec(), Path(tmp_path), render=False)
    network = next(layout for layout in bundle.layout_models if layout.view_id == "network_private_connectivity")
    labels = {node.label for node in network.nodes}
    endpoint_targets = {
        edge.source: set()
        for edge in network.edges
        if _node_service(network, edge.source) == "vpc_endpoint"
    }
    for edge in network.edges:
        if edge.source in endpoint_targets:
            target_service = _node_service(network, edge.target)
            if target_service not in {None, "vpc_endpoint", "vpc_link", "semantic_group"}:
                target = next(node for node in network.nodes if node.id == edge.target)
                endpoint_targets[edge.source].add(target.label)

    assert bundle.qa_report.passed
    assert {"Orders Table", "Inventory Table", "Order Queue"}.issubset(labels)
    assert any({"Orders Table", "Inventory Table"}.issubset(targets) for targets in endpoint_targets.values())
    assert any("Order Queue" in targets for targets in endpoint_targets.values())


def test_endpoint_without_target_is_error():
    view_spec = SemanticArchitectureSpec(
        title="Broken Network",
        nodes=[
            ServiceNode(id="app", name="App", service="ecs", scope="vpc_resident"),
            ServiceNode(id="endpoint", name="DynamoDB gateway endpoint", service="vpc_endpoint", scope="vpc_resident"),
        ],
        flows=[Flow(id="f1", source="app", target="endpoint", label="gateway endpoint")],
        metadata={"diagram_view": "network_private_connectivity"},
    )
    layout = LayoutModel(
        view_id="network_private_connectivity",
        title="Broken Network",
        groups=[LayoutGroup(id="root", label="root", group_type="view", order=0)],
        lanes=[
            LayoutLane(id="private_backend", label="Private backend", group_id="root", order=0, orientation="vertical"),
        ],
        nodes=[
            LayoutNode(id="app", source_node_ids=["app"], label="App", service="ecs", provider="aws", lane_id="private_backend", rank=0, order=0, placement_scope="vpc_resident", role="ecs"),
            LayoutNode(id="endpoint", source_node_ids=["endpoint"], label="DynamoDB gateway endpoint", service="vpc_endpoint", provider="aws", lane_id="private_backend", rank=1, order=1, placement_scope="vpc_resident", role="vpc_endpoint"),
        ],
        edges=[
            LayoutEdge(id="f1", source="app", target="endpoint", source_flow_ids=["f1"], label="gateway endpoint", edge_type="vpc_endpoint_access"),
        ],
    )

    report = run_visual_layout_qa(view_spec, {}, max_aspect_ratio=3.5, max_visible_edges=24, layout_model=layout)

    assert not report.passed
    assert any(diagnostic.code == "network_endpoint_missing_target" for diagnostic in report.diagnostics)


def test_quality_config_is_single_source_for_core_thresholds():
    src_root = Path(__file__).resolve().parents[1] / "src" / "archway_diagram_compiler"
    offenders = []
    forbidden_snippets = [
        "max_edge_crossings = 8",
        "max_edge_crossings = 16",
        "max_edge_crossings = 32",
        "max_edge_crossings = 64",
        "for attempt in range(3)",
        "max_aspect_ratio=3.5",
        "max_visible_edges=24",
    ]
    for path in src_root.glob("*.py"):
        if path.name == "quality_config.py":
            continue
        text = path.read_text(encoding="utf-8")
        offenders.extend(f"{path.name}: {snippet}" for snippet in forbidden_snippets if snippet in text)

    assert offenders == []


def _node_service(layout, node_id):
    node = next((item for item in layout.nodes if item.id == node_id), None)
    return node.service if node else None


def _endpoint_has_direct_target(layout, endpoint_id):
    return any(
        edge.source == endpoint_id
        and _node_service(layout, edge.target) not in {None, "vpc_endpoint", "vpc_link", "semantic_group"}
        for edge in layout.edges
    )


def test_empty_views_are_omitted_with_reason_and_explained(tmp_path):
    spec = _homogeneous_fanout_spec(
        title="Omit Empty Network",
        source_service="eventbridge",
        source_name="EventBridge Bus",
        target_service="lambda",
        target_name="Lambda Target",
        count=12,
        label="route event",
    )

    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    render_plan = json.loads(bundle.artifact_paths["render_plan"].read_text())
    explanations = bundle.artifact_paths["placement_explanations"].read_text()

    assert "network_private_connectivity" not in {view.name for view in bundle.views}
    assert {"view_id": "network_private_connectivity", "title": "Omit Empty Network - Network and private connectivity", "reason": "No meaningful private connectivity path for this architecture"} in render_plan["omitted_views"]
    assert "`network_private_connectivity`: No meaningful private connectivity path for this architecture." in explanations
    assert "EventBridge Bus` had 12 homogeneous outgoing flows to Lambda targets" in explanations
    assert "summarizes them as “Event targets ×12”" in explanations


def test_compile_cleans_stale_omitted_view_artifacts(tmp_path):
    out = Path(tmp_path) / "stale"
    stale = out / "network_private_connectivity"
    stale.mkdir(parents=True)
    (stale / "diagram.svg").write_text("<svg></svg>", encoding="utf-8")

    spec = _homogeneous_fanout_spec(
        title="Clean Stale Views",
        source_service="sns",
        source_name="SNS Topic",
        target_service="sqs",
        target_name="SQS Queue",
        count=12,
        label="deliver message",
    )
    bundle = compile_architecture(spec, out, render=False)

    assert bundle.qa_report.passed
    assert not stale.exists()
    assert "network_private_connectivity" not in {view.name for view in bundle.views}


def _homogeneous_fanout_spec(
    title,
    source_service,
    source_name,
    target_service,
    target_name,
    count,
    label,
    target_metadata=None,
):
    target_metadata = target_metadata or {}
    return SemanticArchitectureSpec(
        title=title,
        nodes=[
            ServiceNode(id="source", name=source_name, service=source_service, region="us-east-1"),
            *[
                ServiceNode(
                    id=f"target_{index}",
                    name=f"{target_name} {index}",
                    service=target_service,
                    region="us-east-1",
                    metadata=dict(target_metadata),
                )
                for index in range(count)
            ],
        ],
        flows=[
            Flow(id=f"fanout_{index}", source="source", target=f"target_{index}", label=label)
            for index in range(count)
        ],
        metadata={"internet_facing": False},
    )


def test_same_lane_sibling_dependencies_use_handoff_to_avoid_false_chain(tmp_path):
    spec = SemanticArchitectureSpec(
        title="Cache And Database Dependencies",
        nodes=[
            ServiceNode(id="svc", name="Order Service", service="ecs", region="us-east-1", vpc_id="orders-vpc"),
            ServiceNode(id="cache", name="Redis Cache", service="elasticache", region="us-east-1", vpc_id="orders-vpc"),
            ServiceNode(id="db", name="Orders DB", service="rds", region="us-east-1", vpc_id="orders-vpc"),
        ],
        flows=[
            Flow(id="cache", source="svc", target="cache", label="cache"),
            Flow(id="query", source="svc", target="db", label="query"),
        ],
        metadata={"internet_facing": False},
    )

    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    logical_layout = next(layout for layout in bundle.layout_models if layout.view_id == "production_logical_service_flow")
    nodes_by_id = {node.id: node for node in logical_layout.nodes}
    handoff = nodes_by_id["svc_dependency_handoff"]

    assert bundle.qa_report.passed
    assert handoff.label == "Parallel dependencies"
    assert nodes_by_id["cache"].lane_id == "service_dependencies"
    assert nodes_by_id["db"].lane_id == "service_dependencies"
    assert {edge.source for edge in logical_layout.edges if edge.target in {"cache", "db"}} == {"svc_dependency_handoff"}


def test_deep_chain_wraps_into_stage_lanes_and_passes(tmp_path):
    spec = SemanticArchitectureSpec(
        title="Deep Workflow",
        nodes=[
            ServiceNode(id=f"step_{index}", name=f"Step {index}", service="step_functions", region="us-east-1")
            for index in range(8)
        ],
        flows=[
            Flow(id=f"flow_{index}", source=f"step_{index}", target=f"step_{index + 1}", label="next")
            for index in range(7)
        ],
        metadata={"internet_facing": False},
    )

    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    logical_layout = next(layout for layout in bundle.layout_models if layout.view_id == "production_logical_service_flow")

    assert bundle.qa_report.passed
    assert {"chain_stage_1", "chain_stage_2"}.issubset({lane.id for lane in logical_layout.lanes})


def test_single_node_disconnected_and_self_loop_are_valid_with_warnings(tmp_path):
    single = compile_architecture(
        SemanticArchitectureSpec(
            title="Single Node",
            nodes=[ServiceNode(id="bucket", name="Bucket", service="s3", region="us-east-1")],
            flows=[],
            metadata={"internet_facing": False},
        ),
        Path(tmp_path) / "single",
        render=False,
    )
    assert single.qa_report.passed
    assert any(diagnostic.code == "orphan_node" and diagnostic.severity == "warning" for diagnostic in single.diagnostics)

    disconnected = compile_architecture(
        SemanticArchitectureSpec(
            title="Disconnected",
            nodes=[
                ServiceNode(id="a", name="A", service="lambda", region="us-east-1"),
                ServiceNode(id="b", name="B", service="s3", region="us-east-1"),
            ],
            flows=[],
            metadata={"internet_facing": False},
        ),
        Path(tmp_path) / "disconnected",
        render=False,
    )
    assert disconnected.qa_report.passed
    assert len([diagnostic for diagnostic in disconnected.diagnostics if diagnostic.code == "orphan_node"]) == 2

    self_loop = compile_architecture(
        SemanticArchitectureSpec(
            title="Self Loop",
            nodes=[ServiceNode(id="fn", name="Function", service="lambda", region="us-east-1")],
            flows=[Flow(id="retry", source="fn", target="fn", label="retry")],
            metadata={"internet_facing": False},
        ),
        Path(tmp_path) / "self_loop",
        render=True,
        render_formats=("svg",),
    )
    assert self_loop.qa_report.passed
    assert {flow.id for flow in self_loop.normalized_spec.flows} == {"retry"}
    assert any(node.metadata.get("self_loop") for layout in self_loop.layout_models for node in layout.nodes)


def test_svg_geometry_qa_detects_edge_label_and_node_crossing(tmp_path):
    svg_path = Path(tmp_path) / "geometry.svg"
    svg_path.write_text(
        """<svg viewBox="0 0 300 180">
        <rect x="120" y="40" width="80" height="60" stroke="#94A3B8" fill="#fff" />
        <path d="M 10 70 L 290 70" stroke="#334155" class="connection" />
        <text x="160" y="75" class="text-italic" style="text-anchor:middle;font-size:17px">over node</text>
        <text x="170" y="75" class="text-italic" style="text-anchor:middle;font-size:17px">overlaps</text>
        </svg>""",
        encoding="utf-8",
    )

    assert _svg_edge_label_overlap_count(svg_path) > 0
    assert _svg_edge_crosses_node_count(svg_path) > 0


def test_svg_geometry_qa_detects_edge_to_edge_crossing(tmp_path):
    svg_path = Path(tmp_path) / "crossing.svg"
    svg_path.write_text(
        """<svg viewBox="0 0 300 180">
        <path d="M 40 40 L 260 140" stroke="#334155" class="connection" />
        <path d="M 40 140 L 260 40" stroke="#334155" class="connection" />
        </svg>""",
        encoding="utf-8",
    )

    assert _svg_edge_crossing_count(svg_path) == 1


def test_svg_geometry_qa_detects_node_label_icon_overlap(tmp_path):
    svg_path = Path(tmp_path) / "label_icon_overlap.svg"
    svg_path.write_text(
        """<svg viewBox="0 0 200 200">
        <text x="100" y="70" class="text-bold" style="text-anchor:middle;font-size:16px">Cognito</text>
        <image x="80" y="62" width="40" height="40"></image>
        </svg>""",
        encoding="utf-8",
    )

    assert _svg_node_label_icon_overlap_count(svg_path) == 1


def test_architecture_advisories_are_warnings_not_failures(tmp_path):
    spec = SemanticArchitectureSpec(
        title="Advisory Architecture",
        nodes=[
            ServiceNode(id="user", name="User", service="external_actor"),
            ServiceNode(id="api", name="Public API", service="api_gateway", region="us-east-1"),
            ServiceNode(id="db", name="Public Database", service="rds", region="us-east-1", metadata={"public_access": True, "datastore_role": "write_target"}),
        ],
        flows=[
            Flow(id="f1", source="user", target="api", label="HTTPS"),
            Flow(id="f2", source="api", target="db", label="read records"),
        ],
    )

    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    advisory_codes = {diagnostic.code for diagnostic in bundle.diagnostics if diagnostic.code.startswith("architecture_advisory")}

    assert bundle.qa_report.passed
    assert "architecture_advisory_public_entry_without_auth" in advisory_codes
    assert "architecture_advisory_datastore_without_writer" in advisory_codes
    assert "architecture_advisory_public_stateful_service" in advisory_codes


def test_intentionally_public_demo_downgrades_auth_advisory(tmp_path):
    spec = SemanticArchitectureSpec(
        title="Public Demo",
        nodes=[
            ServiceNode(id="user", name="User", service="external_actor"),
            ServiceNode(id="api", name="Demo API", service="api_gateway", region="us-east-1", metadata={"auth_mode": "public_demo"}),
        ],
        flows=[Flow(id="f1", source="user", target="api", label="HTTPS")],
    )

    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    advisories = [diagnostic for diagnostic in bundle.diagnostics if diagnostic.code == "architecture_advisory_public_entry_without_auth"]

    assert bundle.qa_report.passed
    assert advisories
    assert {diagnostic.severity for diagnostic in advisories} == {"info"}


def test_public_api_auth_advisory_has_placement_explanation(tmp_path):
    spec = SemanticArchitectureSpec(
        title="Unauthenticated API",
        nodes=[
            ServiceNode(id="user", name="User", service="external_actor"),
            ServiceNode(id="api", name="Public API", service="api_gateway", region="us-east-1"),
        ],
        flows=[Flow(id="f1", source="user", target="api", label="HTTPS")],
    )

    bundle = compile_architecture(spec, Path(tmp_path), render=False)
    explanations = bundle.artifact_paths["placement_explanations"].read_text(encoding="utf-8")

    assert bundle.qa_report.passed
    assert any(diagnostic.severity == "warning" and diagnostic.code == "architecture_advisory_public_entry_without_auth" for diagnostic in bundle.diagnostics)
    assert "add a Cognito/JWT authorizer, IAM auth" in explanations


def test_read_only_and_audit_datastores_do_not_raise_writer_advisory(tmp_path):
    spec = SemanticArchitectureSpec(
        title="Read Only Sources",
        nodes=[
            ServiceNode(id="app", name="App", service="ecs", region="us-east-1", vpc_id="app-vpc"),
            ServiceNode(id="docs", name="Document Bucket", service="s3", region="us-east-1", metadata={"role": "source_documents"}),
            ServiceNode(id="audit", name="Audit Store", service="s3", region="us-east-1", metadata={"role": "audit_store"}),
            ServiceNode(id="registry", name="Tool Registry", service="dynamodb", region="us-east-1", metadata={"role": "tool_registry"}),
        ],
        flows=[
            Flow(id="f1", source="app", target="docs", label="source reference", edge_type="source_reference"),
            Flow(id="f2", source="app", target="audit", label="audit trace", edge_type="audit_trace"),
            Flow(id="f3", source="app", target="registry", label="lookup tool", edge_type="data_read"),
        ],
        metadata={"internet_facing": False},
    )

    bundle = compile_architecture(spec, Path(tmp_path), render=False)

    assert bundle.qa_report.passed
    assert not [diagnostic for diagnostic in bundle.diagnostics if diagnostic.code == "architecture_advisory_datastore_without_writer"]


def test_rule_registry_and_lane_templates_are_load_bearing(tmp_path):
    bundle = compile_architecture(retail_order_fulfillment_spec(), Path(tmp_path), render=False)
    render_plan = bundle.artifact_paths["render_plan"].read_text()
    logical_layout = next(layout for layout in bundle.layout_models if layout.view_id == "production_logical_service_flow")
    network_layout = next(layout for layout in bundle.layout_models if layout.view_id == "network_private_connectivity")

    assert "retail_fulfillment" in render_plan
    assert "network_private_connectivity" in render_plan
    assert "aws.api_gateway.private_integration.vpc_link" in render_plan
    assert [lane.id for lane in logical_layout.lanes][:4] == [
        "edge_identity_controls",
        "request_path",
        "private_backend",
        "service_dependencies",
    ]
    assert [lane.id for lane in network_layout.lanes][:2] == ["request_path", "private_backend"]
    assert any(diagnostic.code == "private_api_integration_added" for diagnostic in bundle.diagnostics)
