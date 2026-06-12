"""Provider enrichment rule registry."""

from typing import Iterable, List

from archway_diagram_compiler.enrichment_rule import CompileContext, EnrichmentRule, RuleResult
from archway_diagram_compiler.models import SemanticArchitectureSpec


class RuleRegistry:
    def __init__(self, rules: Iterable[EnrichmentRule] = ()) -> None:
        self._rules = sorted(list(rules), key=lambda rule: (rule.priority, rule.id))

    def register(self, rule: EnrichmentRule) -> None:
        self._rules.append(rule)
        self._rules.sort(key=lambda item: (item.priority, item.id))

    def rules_for(self, provider: str, rule_sets: Iterable[str] = ("default",)) -> List[EnrichmentRule]:
        selected_rule_sets = set(rule_sets)
        return [
            rule
            for rule in self._rules
            if rule.provider == provider and rule.default_enabled and rule.rule_set in selected_rule_sets
        ]

    def apply(self, spec: SemanticArchitectureSpec, context: CompileContext) -> List[RuleResult]:
        results: List[RuleResult] = []
        for rule in self.rules_for(context.provider, context.enabled_rule_sets):
            matched = rule.matches(spec, context)
            if not matched:
                results.append(RuleResult(rule_id=rule.id, matched=False, why="Rule did not match."))
                continue
            results.append(rule.apply(spec, context))
        return results
