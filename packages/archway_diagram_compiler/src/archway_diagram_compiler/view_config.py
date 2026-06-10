"""Data-driven view configuration."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ViewConfig(BaseModel):
    id: str
    title: str
    view_type: str
    include_node_filter: Dict[str, Any] = Field(default_factory=dict)
    include_flow_filter: Dict[str, Any] = Field(default_factory=dict)
    grouping_dimension: Optional[str] = None
    lane_template: str
    layout_strategy: str
    max_visible_nodes: int = 24
    max_visible_edges: int = 24
    split_conditions: List[Dict[str, Any]] = Field(default_factory=list)
