"""Structural QA gates."""

from typing import Iterable, List

from archway_diagram_compiler.flow_ledger import validate_flow_ledger
from archway_diagram_compiler.models import Diagnostic, FlowLedger, SemanticArchitectureSpec
from archway_diagram_compiler.qa import run_graph_qa


def run_structural_qa(
    spec: SemanticArchitectureSpec,
    diagnostics: Iterable[Diagnostic],
    flow_ledger: FlowLedger,
) -> List[Diagnostic]:
    report = run_graph_qa(spec, diagnostics)
    return list(report.diagnostics) + validate_flow_ledger(spec, flow_ledger)
