from app.services.view_planner import (
    DiagramViewType,
    customer_title_for_compiler_view,
    diagram_view_mappings,
)


def test_diagram_view_mapping_records_compiler_fallbacks():
    mappings = diagram_view_mappings(
        [
            DiagramViewType.TELEMETRY_INGESTION.value,
            DiagramViewType.STREAM_PROCESSING.value,
            DiagramViewType.DISPATCH_WORKFLOW.value,
        ]
    )

    async_flow_mappings = [item for item in mappings if item.compiler_view_id == "async_flow_view"]

    assert len(async_flow_mappings) == 3
    assert all(item.rendered_as_native_view is False for item in async_flow_mappings)
    assert all(item.fallback_reason for item in async_flow_mappings)
    assert customer_title_for_compiler_view("async_flow_view", mappings).endswith("Semantic Views)")


def test_network_view_mapping_is_native_when_supported():
    mappings = diagram_view_mappings([DiagramViewType.NETWORK_PRIVATE_CONNECTIVITY.value])

    assert mappings[0].compiler_view_id == "network_private_connectivity"
    assert mappings[0].rendered_as_native_view is True
    assert mappings[0].fallback_reason is None
