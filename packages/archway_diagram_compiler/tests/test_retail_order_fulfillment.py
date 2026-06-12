from pathlib import Path

from archway_diagram_compiler.compiler import compile_architecture
from examples.retail_order_fulfillment import retail_order_fulfillment_spec


def test_retail_logical_view_preserves_business_edges(tmp_path):
    bundle = compile_architecture(retail_order_fulfillment_spec(), Path(tmp_path), render=False)
    logical_view = next(view for view in bundle.views if view.name == "production_logical_service_flow")

    assert "order_service -> rag_retrieval.orders_table" not in logical_view.d2_text
    assert "write order" in logical_view.d2_text
    assert "reserve inventory" in logical_view.d2_text
    assert "enqueue fulfillment" in logical_view.d2_text
    assert not [item for item in bundle.diagnostics if item.code == "logical_orphan_node"]
    assert bundle.qa_report.passed


def test_retail_network_view_keeps_only_vpc_resident_compute_inside_vpc(tmp_path):
    bundle = compile_architecture(retail_order_fulfillment_spec(), Path(tmp_path), render=False)
    network_view = next(view for view in bundle.views if view.name == "network_private_connectivity")

    assert "payment_lambda" not in network_view.d2_text
    assert "DynamoDB gateway endpoint" in network_view.d2_text
    assert "SQS interface endpoint" in network_view.d2_text
    assert "CloudWatch Logs interface endpoint" in network_view.d2_text
    assert bundle.qa_report.passed
