"""Rule interface for deterministic semantic enrichment."""

from typing import List, Protocol

from pydantic import BaseModel, Field

from archway_diagram_compiler.models import Diagnostic, SemanticArchitectureSpec


class CompileContext(BaseModel):
    provider: str = "aws"
    enabled_rule_sets: List[str] = Field(default_factory=lambda: ["default"])
    metadata: dict = Field(default_factory=dict)


class RuleResult(BaseModel):
    rule_id: str
    matched: bool
    why: str
    changed: bool = False
    added_nodes: List[str] = Field(default_factory=list)
    added_flows: List[str] = Field(default_factory=list)
    rewritten_flows: List[str] = Field(default_factory=list)
    diagnostics: List[Diagnostic] = Field(default_factory=list)


class EnrichmentRule(Protocol):
    id: str
    provider: str
    priority: int
    default_enabled: bool
    rule_set: str

    def matches(self, spec: SemanticArchitectureSpec, context: CompileContext) -> bool:
        ...

    def apply(self, spec: SemanticArchitectureSpec, context: CompileContext) -> RuleResult:
        ...
