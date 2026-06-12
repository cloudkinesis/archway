"""Provider-specific semantic QA gates."""

from typing import List

from archway_diagram_compiler.catalog import is_vpc_scope
from archway_diagram_compiler.models import Diagnostic, SemanticArchitectureSpec
from archway_diagram_compiler.providers import get_provider_catalog


def run_provider_semantic_qa(spec: SemanticArchitectureSpec) -> List[Diagnostic]:
    diagnostics: List[Diagnostic] = []
    for node in spec.nodes:
        try:
            catalog = get_provider_catalog(node.provider)
            info = catalog.get_service_info(node.service)
        except KeyError:
            continue
        if node.vpc_id and not info.can_be_vpc_resident:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="managed_service_inside_vpc",
                    message=f"{node.service} cannot be rendered as VPC-resident.",
                    node_id=node.id,
                )
            )
        if is_vpc_scope(node.scope) and not info.can_be_vpc_resident and info.placement_scope not in {"vpc_resident"}:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="invalid_provider_scope",
                    message=f"{node.service} has invalid provider placement scope {node.scope}.",
                    node_id=node.id,
                )
            )
        if node.service == "lambda" and is_vpc_scope(node.scope) and not node.vpc_id:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="lambda_vpc_without_vpc_id",
                    message="Lambda may only be rendered inside a VPC when vpc_id is present.",
                    node_id=node.id,
                )
            )
    return diagnostics
