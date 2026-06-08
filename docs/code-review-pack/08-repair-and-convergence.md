# Repair and Convergence

Archway has bounded repair/convergence plumbing. It should be viewed as a deterministic safety net, not a universal autonomous fixer.

## Architecture-Time Repair

During architecture generation, routes call:

1. `ArchitecturePlanner`
2. `GovernanceControlEnricher`
3. `ArchitectureCritiqueService`
4. Deterministic repair logic for repairable critique findings
5. Architecture validation/revision storage

Effectful flows should receive typed governance controls before validation. The intended behavior is: auto-repair repairable governance gaps, revalidate, and only block customer-ready status if unresolved unsafe actions remain.

## Export-Time Golden Convergence

`app/services/convergence/golden_convergence_orchestrator.py` runs during export package generation.

It:

- Loads current context artifacts.
- Collects findings from understanding, pricing, diagrams, dossier consistency, customer readiness, and architecture.
- Builds a repair plan through `RepairPlanner`.
- Applies limited repairs through `ArchitectureRepairer`.
- Repeats up to a small max iteration count.
- Writes convergence artifacts and summary.
- Assigns final status.

Possible final statuses include:

- `golden_candidate`
- `customer_demo_ready_with_caveats`
- `directional_only`
- `internal_only`
- `failed_validation`

## Repair Planner

`app/services/convergence/repair_planner.py` maps findings to repair action types such as:

- classification
- metrics
- pricing driver model
- architecture component
- architecture flow
- governance control
- service replacement
- service decision
- provider catalog
- diagram view
- lane rename
- suppress view
- invalidate pricing
- regenerate dossier
- cap readiness

Not every action type has a full executor today. Reviewers should check whether `can_auto_apply=true` findings are actually applied and recorded.

## Architecture Repairer

`app/services/convergence/architecture_repairer.py` currently applies narrow repairs for selected patterns, such as missing capital markets risk or payment fraud paths, and generic missing components/flows/services.

## Important Honesty Point

The presence of a repair plan does not guarantee a fully fixed architecture. The product should never present unresolved critical repairable actions as if they were applied. If `repair_plan` has auto-applicable actions and `repairs_applied=0`, that should be treated as suspicious unless there is a clear reason.

## Reviewer Questions

Check:

- Are repairable governance findings fixed before blocking diagram/export?
- Are repairs recorded in artifacts and export?
- Are affected stages rerun when needed?
- Does readiness reflect unresolved issues?
- Does the UI/export distinguish "repaired", "queued", "not repairable", and "still blocked"?

