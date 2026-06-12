"""Central quality thresholds for compiler planning, QA, and repair."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DiagramQualityConfig:
    max_aspect_ratio: float = 3.5
    min_primary_aspect_ratio: float = 0.55
    max_visible_nodes: int = 24
    max_visible_edges: int = 24
    max_visible_edges_expanded: int = 32
    max_direct_workload_fanout: int = 3
    homogeneous_fanout_threshold: int = 8
    max_repair_attempts: int = 3
    logical_edge_crossing_max: int = 8
    network_edge_crossing_max: int = 32
    async_edge_crossing_max: int = 32
    default_edge_crossing_max: int = 16
    fanout_detail_crossing_max_12: int = 16
    fanout_detail_crossing_max_24: int = 24
    fanout_detail_crossing_max_large: int = 32

    def max_edge_crossings_for_view(self, view_id: Optional[str], target_count: int = 0) -> int:
        if view_id == "production_logical_service_flow":
            return self.logical_edge_crossing_max
        if view_id == "network_private_connectivity":
            return self.network_edge_crossing_max
        if view_id == "async_flow_view":
            return self.async_edge_crossing_max
        if view_id in {"live_media_delivery_view", "media_rights_ad_decisioning_view", "media_qoe_analytics_view"}:
            return self.async_edge_crossing_max
        if view_id == "fanout_detail_view":
            if target_count <= 12:
                return self.fanout_detail_crossing_max_12
            if target_count <= 24:
                return self.fanout_detail_crossing_max_24
            return self.fanout_detail_crossing_max_large
        return self.default_edge_crossing_max


DEFAULT_QUALITY_CONFIG = DiagramQualityConfig()
