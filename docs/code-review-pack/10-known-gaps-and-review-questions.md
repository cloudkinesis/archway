# Known Gaps and Review Questions

This file intentionally lists weaknesses. It is better for review than hiding them.

## Pricing Gaps

- Not all pricing line items are procurement-ready.
- Some estimates remain heuristic or directional.
- Scenario profiles are not complete for every workload family.
- SKU/rate binding can be missing or partial.
- Pricing ledger and headline safety must be inspected for every export.
- Non-zero pricing with empty or weak trace should be treated as a blocker/warning.

Review questions:

- Does the UI ever present directional pricing as exact?
- Are line items clearly marked when SKU/tier is unresolved?
- Are workload-specific drivers used instead of legacy generic scale?
- Does procurement readiness require actual driver and rate evidence?

## Domain Drift Gaps

- Domain logic is spread across classifier, synthesis, pricing, research view model, pattern catalog, and dossier modules.
- This makes leakage possible when adding a new domain family.

Review questions:

- Do generic scenarios remain generic?
- Does telecom HBase/HDFS ask access-pattern questions before target-store choice?
- Does media streaming avoid accidental computer vision?
- Does healthcare reserved vocabulary lint apply only to healthcare?

## UI Maintainability Gaps

- `frontend/src/components/App.tsx` is very large and contains many view components.
- UX is improved but still should be modularized later.
- Frontend may still need better visual regression coverage.

Review questions:

- Are research sections readable by an architecture reviewer?
- Are raw evidence ids hidden by default?
- Do visible buttons work or show disabled state?
- Does session hydration restore every tab after reload?

## Diagram Gaps

- Compiler path is local and environment-dependent.
- Semantic view to compiler view mapping can drift.
- Some domain-specific views may be missing or substituted.
- Diagram QA can fail for placement/crossing issues independent of icon embedding.

Review questions:

- Are semantic requested views preserved or explicitly reported missing?
- Does Archway always use `DiagramCompilerAdapter`?
- Are missing/degraded views visible in UI/export?

## Repair/Convergence Gaps

- Repair loop is bounded and only handles selected repair types.
- Some `RepairAction` types are planned but not fully executable.
- Export-time convergence is not the same as rerunning all product phases from scratch.

Review questions:

- Are auto-applicable repairs actually applied?
- Are `repairs_applied` recorded?
- Does final readiness reflect unresolved blockers?

## Evidence and MCP Gaps

- AWS Docs MCP and AWS Pricing MCP are optional environment integrations.
- Tavily competitor search is budget/config dependent.
- Managed AWS documentation search is evidence/context, not procurement pricing.

Review questions:

- Does competitor scan status say exactly what was attempted?
- Are AWS docs, web, user input, local policy, and pricing evidence labeled distinctly?
- Are assumptions separated from facts?

## Security and Governance Gaps

- Effectful flow classification exists but must be reviewed for completeness.
- Approval, guardrail, rollback, kill switch, override, and audit controls should be linked to governed flow ids.

Review questions:

- Do dispatch/pre-position/update/delete/external-write flows receive controls?
- Are unsafe unresolved actions downgraded to recommendation-only or queue-for-review?
- Is the system avoiding brittle string-only approval detection?

