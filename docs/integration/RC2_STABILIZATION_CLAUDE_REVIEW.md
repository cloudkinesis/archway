# RC2 Stabilization Integration Review

Integration of the reviewed RC2 bug-fix branches onto a single branch for review.
No source code was modified during integration; all five merges were `--no-ff`
with no conflicts and no squashing.

## 1. Baseline
- Baseline commit: `f692c04` (`chore: establish Archway RC2 baseline`)

## 2. Integration branch tip
- Branch: `integration/rc2-stabilization-claude`
- Tip: `a23e676`

## 3. Branches merged (in order) and merge commit hashes
| # | Branch | Source commit | Merge commit |
|---|---|---|---|
| 1 | `fix/architecture-revision-lifecycle` | `332df7c` | `3058f79` |
| 2 | `fix/synthesis-completion-loop` | `bbc9df2` | `b1b381b` |
| 3 | `fix/export-quality-artifacts` | `0dbe9e9` | `8b03f18` |
| 4 | `fix/job-manager-lifecycle` | `3556efa` | `9d9aebf` |
| 5 | `fix/typed-effectful-flow-detection` | `8dafe82` | `a23e676` |

## 4. What each merge fixes
1. **architecture-revision-lifecycle** — `/architecture/generate` now appends a new
   revision via `record_generation()` instead of the silent no-op when a revision
   already exists. `regenerate_from_active` clarified/renamed to
   `duplicate_active_revision` (copy, not re-derivation); old name kept as alias.
2. **synthesis-completion-loop** — once all interview questions are answered,
   `respond()` no longer re-answers question[0]; extra input is recorded as a
   deduplicated clarification instead of inflating assumptions / problem statement.
3. **export-quality-artifacts** — export collects golden-convergence and build-status
   loop-safely (thread offload when an event loop is running), and writes explicit
   status records / placeholders instead of vague "missing optional artifact" or
   event-loop warnings. Customer readiness fails closed.
4. **job-manager-lifecycle** — TTL eviction + max-retained cap for terminal jobs (no
   unbounded growth); honest cancellation (`cancelled` terminal state + cancellation
   metadata); `is_cancellation_requested()` API; never claims hard cancellation while
   a task is still running.
5. **typed-effectful-flow-detection** — governance detection prefers explicit typed
   flow metadata (`action_intent`, `external_write`, `mutates_source_system`, etc.)
   with label/classification string matching kept as a union fallback. Standardized
   typed metadata added to known effectful pattern flows.

## 5. Files changed grouped by area (vs `f692c04`, +1326 / -33, 15 files)
- **API / routes:** `app/api/routes.py`
- **Config / models:** `app/core/config.py`, `app/models/domain.py`
- **Architecture lifecycle:** `app/services/architecture_revisions.py`
- **Synthesis:** `app/services/synthesis.py`
- **Export:** `app/services/export_package.py`
- **Jobs:** `app/services/jobs.py`
- **Governance / patterns:** `app/services/governance_controls.py`, `app/services/pattern_catalog.py`
- **Frontend (additive types only):** `frontend/src/lib/types.ts`
- **Tests (new):** `tests/test_architecture_revision_lifecycle.py`,
  `tests/test_synthesis_completion_loop.py`, `tests/test_export_quality_artifacts.py`,
  `tests/test_job_manager_lifecycle.py`, `tests/test_typed_effectful_flow_detection.py`

The five branches touched largely disjoint files, hence no merge conflicts.

## 6. Tests run and results
Run on the integration tip (`a23e676`) using the project Python 3.12 venv.

- Per-merge focused tests: 6 / 5 / 6 / 9 / 9 passed (in merge order).
- Combined focused suite (all five branch test files): **35 passed**.
- Regression suite
  (`test_healthcare_operations_scheduling`, `test_healthcare_anti_drift`,
  `test_discovery_planner`, `test_pricing`, `golden_scenarios/test_scenario_matrix`):
  **32 passed**.
- Frontend build (`frontend/src/lib/types.ts` in diff): **success** (tsc + vite).
- Working tree clean after every merge and at tip.

## 7. Known pre-existing failures (not introduced here)
- `tests/test_end_to_end_flow.py::test_utility_grid_flow_is_not_misclassified_as_rag_assistant`
  — a citation-coverage assertion that fails on the untouched baseline (also sensitive
  to leftover `.archway` state). It is unrelated to these fixes, was excluded from the
  integration test commands, and is not caused by any merged branch.

## 8. Rollback commands
Per-merge, non-destructive (keeps mainline parent, creates a revert commit):
```bash
git revert -m 1 a23e676   # undo merge 5 (typed-effectful-flow-detection)
git revert -m 1 9d9aebf   # undo merge 4 (job-manager-lifecycle)
git revert -m 1 8b03f18   # undo merge 3 (export-quality-artifacts)
git revert -m 1 b1b381b   # undo merge 2 (synthesis-completion-loop)
git revert -m 1 3058f79   # undo merge 1 (architecture-revision-lifecycle)
```
Full reset of this branch to baseline (this branch only):
```bash
git reset --hard f692c04
```
Discard the integration branch entirely:
```bash
git switch master && git branch -D integration/rc2-stabilization-claude
```
Merges are file-disjoint, so each `git revert -m 1` is independent of the others.

## 9. Intentionally NOT merged
- `experiment/domain-pack-interface` (Phase 1 read-only domain-pack registry).
- `feature/domain-pack-phase2-pricing-drivers` (Phase 2A advisory pricing metadata).
- No merge to `master`.
- Open recommendations not in any branch and deliberately not applied here:
  fail-closed default for `pricing_can_be_displayed_as_headline`
  (`research_view_model.py`), corrupt-audit-line guard in `read_session_logs`
  (`logging.py`), and broader audit-log redaction.

## 10. Recommended Codex review order
Lowest-risk / most isolated first, highest-surface last:
1. `fix/synthesis-completion-loop` (`bbc9df2`) — single service, contained logic.
2. `fix/architecture-revision-lifecycle` (`332df7c`) — small, additive method + 2 call sites.
3. `fix/job-manager-lifecycle` (`3556efa`) — concurrency/lifecycle; review cancellation
   semantics and additive model/type fields.
4. `fix/export-quality-artifacts` (`0dbe9e9`) — async/thread-offload and artifact status;
   review event-loop handling.
5. `fix/typed-effectful-flow-detection` (`8dafe82`) — governance trust boundary; review
   typed-vs-string union semantics and that no gate was relaxed.
