"""AWS service placement catalog.

The compiler uses this catalog as the source of truth for physical placement.
LLM-generated or caller-provided scopes are validated against it.
"""

from typing import Optional

from archway_diagram_compiler.aws_provider import AWS_PROVIDER
from archway_diagram_compiler.models import PlacementScope, ServiceNode


def normalize_service_name(service: str) -> str:
    return AWS_PROVIDER.canonicalize_service(service)


def classify_service(service: str) -> Optional[PlacementScope]:
    return AWS_PROVIDER.get_placement_scope(service, ServiceNode(id="_", name="_", service=service))  # type: ignore[return-value]


def classify_node(node: ServiceNode) -> Optional[str]:
    return AWS_PROVIDER.get_placement_scope(node.service, node)


def is_vpc_scope(scope: Optional[str]) -> bool:
    return scope in {"vpc_workload", "vpc_data", "vpc_resident"}
