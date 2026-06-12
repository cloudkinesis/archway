"""Adapter from Archway ArchitectureSpec into SemanticArchitectureSpec.

This is intentionally the only Archway-aware module in the package. It accepts
plain dictionaries or Pydantic-like objects with `dict()`/`model_dump()`.
"""

from typing import Any, Dict

from archway_diagram_compiler.models import Flow, SemanticArchitectureSpec, ServiceNode


def archway_to_semantic_spec(architecture_spec: Any) -> SemanticArchitectureSpec:
    data = _to_dict(architecture_spec)
    components = data.get("components") or data.get("nodes") or data.get("services") or []
    relationships = data.get("relationships") or data.get("flows") or data.get("edges") or []

    nodes = []
    for component in components:
        item = _to_dict(component)
        nodes.append(
            ServiceNode(
                id=str(item.get("id") or item.get("name")),
                name=str(item.get("name") or item.get("id")),
                service=str(item.get("service") or item.get("type") or item.get("aws_service")),
                scope=item.get("scope"),
                region=item.get("region"),
                vpc_id=item.get("vpc_id") or item.get("vpc"),
                subnet_id=item.get("subnet_id") or item.get("subnet"),
                az=item.get("az") or item.get("availability_zone"),
                logical_group=item.get("logical_group"),
                active_active=bool(item.get("active_active", False)),
                annotation=bool(item.get("annotation", False)),
                metadata=item.get("metadata") or {},
            )
        )

    flows = []
    for index, relationship in enumerate(relationships, start=1):
        item = _to_dict(relationship)
        flows.append(
            Flow(
                id=str(item.get("id") or f"flow_{index}"),
                source=str(item.get("source") or item.get("from")),
                target=str(item.get("target") or item.get("to")),
                label=item.get("label") or item.get("name"),
                protocol=item.get("protocol"),
                metadata=item.get("metadata") or {},
            )
        )

    return SemanticArchitectureSpec(
        title=str(data.get("title") or data.get("name") or "Architecture"),
        nodes=nodes,
        flows=flows,
        regions=list(data.get("regions") or []),
        metadata={"source": "archway", **dict(data.get("metadata") or {})},
    )


def _to_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    raise TypeError(f"Unsupported Archway spec object: {type(value)!r}")
