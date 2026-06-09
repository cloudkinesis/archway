# RC2 Branch Ledger

All branches as of this log. Commit hashes are the branch tips at integration time.
"Merge status" is relative to `master` (nothing has been merged to master).

Rollback conventions:
- Undo a `--no-ff` merge on the integration branch: `git revert -m 1 <merge_commit>`.
- Reset a working branch to baseline: `git reset --hard f692c04` (that branch only).
- Discard a branch: `git switch master && git branch -D <branch>`.

---

## master — `f692c04`
- **Purpose:** RC2 baseline (root commit).
- **Files:** baseline tree.
- **Tests:** baseline; carries pre-existing e2e/synthesis failures (see KNOWN_ISSUES I1/I2).
- **Merge status:** n/a (default branch).
- **Rollback:** n/a.

## integration/rc2-stabilization-claude — `a23e676`
- **Purpose:** integrate the five stabilization fixes for review (no master merge).
- **Files:** union of the five fix branches below (9 source/frontend files + 5 new test files).
- **Tests:** combined focused suite 35 passed; regression subset 32 passed; frontend build OK. Full suite not yet run on the tip (see GOLDEN_GATE).
- **Merge status:** contains merges of all five `fix/*` stabilization branches; not merged to master.
- **Rollback:** `git revert -m 1` of any of `3058f79 / b1b381b / 8b03f18 / 9d9aebf / a23e676`, or `git reset --hard f692c04`.

## fix/architecture-revision-lifecycle — `332df7c`
- **Purpose:** `/architecture/generate` appends a new active revision instead of a silent no-op; clarify `regenerate` as duplicate.
- **Files:** `app/api/routes.py`, `app/services/architecture_revisions.py`, + new lifecycle test.
- **Tests:** 6 passed.
- **Merge status:** merged into integration (`3058f79`); not on master.
- **Rollback:** `git revert -m 1 3058f79`.

## fix/synthesis-completion-loop — `bbc9df2`
- **Purpose:** stop re-answering question[0] after the interview is complete; record extra input as clarification.
- **Files:** `app/services/synthesis.py`, + new test.
- **Tests:** 5 passed.
- **Merge status:** merged into integration (`b1b381b`); not on master.
- **Rollback:** `git revert -m 1 b1b381b`.

## fix/export-quality-artifacts — `0dbe9e9`
- **Purpose:** loop-safe convergence/build-status collection; explicit quality-artifact status; readiness fails closed.
- **Files:** `app/services/export_package.py`, + new `tests/test_export_quality_artifacts.py`.
- **Tests:** 6 passed.
- **Merge status:** merged into integration (`8b03f18`); not on master.
- **Rollback:** `git revert -m 1 8b03f18`.

## fix/job-manager-lifecycle — `3556efa`
- **Purpose:** TTL eviction + max-retained cap; honest cancellation; `is_cancellation_requested` API.
- **Files:** `app/services/jobs.py`, `app/core/config.py`, `app/models/domain.py`, `frontend/src/lib/types.ts` (additive), + new test.
- **Tests:** 9 passed; frontend build OK.
- **Merge status:** merged into integration (`9d9aebf`); not on master.
- **Rollback:** `git revert -m 1 9d9aebf`.

## fix/typed-effectful-flow-detection — `8dafe82`
- **Purpose:** prefer typed flow metadata for governance detection; string matching as union fallback; no gate relaxed.
- **Files:** `app/services/governance_controls.py`, `app/services/pattern_catalog.py`, + new test.
- **Tests:** 9 passed.
- **Merge status:** merged into integration (`a23e676`); not on master.
- **Rollback:** `git revert -m 1 a23e676`.

## fix/pricing-headline-fail-closed — `f39852b`
- **Purpose:** fail-closed default for `PricingSanityReview.pricing_can_be_displayed_as_headline` (presentation already fail-closed on baseline).
- **Files:** `app/services/pricing_sanity_reviewer.py`, + new `tests/test_pricing_headline_fail_closed.py`.
- **Tests:** 7 new passed; view-model + pricing suites 26 passed; anti-drift/discovery/golden 20 passed.
- **Merge status:** standalone; NOT in the integration branch yet; not on master.
- **Rollback:** `git reset --hard f692c04` (branch only) or discard branch.

## fix/export-pricing-headline-fail-closed — `439b73b`
- **Purpose:** fail-closed default for the export pricing headline check in `_pricing_markdown`.
- **Files:** `app/services/export_package.py`, `tests/test_export_package.py` (focused tests appended).
- **Tests:** `test_export_package.py` 10 passed.
- **Merge status:** standalone; NOT in the integration branch yet; not on master.
- **Rollback:** `git reset --hard f692c04` (branch only) or discard branch.
- **Note:** built off baseline, so it does not contain the `fix/export-quality-artifacts`
  changes; both touch `export_package.py` — sequence/conflict-check on merge (see MERGE_PLAN).

## experiment/domain-pack-interface — `fe886af` (design note `d68de2f`; docs-correction `eee308e`)
- **Purpose:** Phase 1 read-only/delegating domain-pack registry + design note, feature-flagged (default off).
- **Files:** `app/domain_packs/*` (new), `app/core/config.py` flag, `app/api/routes.py` diagnostics hook, `docs/experiments/...`, domain-pack tests; plus review-doc corrections.
- **Tests:** domain-pack suite passed flag on/off; full suite parity (2 pre-existing failures only).
- **Merge status:** DEFER until Codex review; not on master.
- **Rollback:** discard branch (no master impact).

## feature/domain-pack-phase2-pricing-drivers — `20eea81`
- **Purpose:** Phase 2A advisory pricing-driver metadata behind the registry flag (delegating; parity-preserving).
- **Files:** `app/domain_packs/{base,builtin,pricing}.py`, `app/services/pricing.py` (flag-gated diagnostics only), + new phase-2 tests.
- **Tests:** domain-pack 18 / pricing suites green flag off; 39 passed flag on; golden/anti-drift parity.
- **Merge status:** DEFER until Codex review; built on the experiment branch; not on master.
- **Rollback:** discard branch (no master impact).

---

## SKU-backed pricing stack (stacked branches)

These three branches form a dependency chain; each is stacked on the previous,
NOT independently on master. Review/merge bottom-up (foundation first).

### feature/sku-backed-pricing-foundation — `9b168d7` (base: `f692c04`)
- **Purpose:** standalone SKU-backed pricing foundation — versioned snapshot abstraction, fail-closed rate binding, reproducible estimate input hash, evidence-classed traces, static fixture support. Not wired into live pricing.
- **Files:** `app/services/sku_pricing/{__init__,snapshot,binding,estimate}.py`, `tests/fixtures/sku_pricing/snapshot_us_east_1_fixture.json`, `tests/test_sku_backed_pricing.py` (all new).
- **Tests:** 17 new passed; existing pricing suites unchanged (21).
- **Merge status:** standalone; not on master. Foundation of the SKU stack.
- **Rollback:** discard branch (no master/live impact).

### feature/sku-pricing-local-cache-adapter — `efe0849` (base: `feature/sku-backed-pricing-foundation` @ `9b168d7`)
- **Purpose:** local-cache adapter for official AWS Price List-derived snapshots — provenance validation, reduced Price List parser, source authority classification. A `local_cache` snapshot can unlock procurement-ready line items only with valid upstream provenance + exact binding.
- **Files:** new `app/services/sku_pricing/{provenance,price_list_parser,cache}.py`; small additive edits to `app/services/sku_pricing/{__init__,snapshot,estimate}.py`; `tests/fixtures/sku_pricing/{aws_price_list_reduced_us_east_1,local_cache_snapshot_us_east_1}.json`; `tests/test_sku_pricing_local_cache.py`.
- **Tests:** 29 passed (17 foundation + 12 local-cache); existing pricing suites unchanged (21).
- **Merge status:** stacked on `9b168d7`; not on master. Foundation branch unchanged.
- **Rollback:** discard branch (no master/live impact).

### feature/sku-pricing-source-truth-pilot — `c301362` (base: `feature/sku-pricing-local-cache-adapter` @ `efe0849`)
- **Purpose:** first controlled, flag-gated bridge from the SKU module into live pricing — a SUPPLEMENTAL SKU-backed trace for legal/document RAG only. Does not change PricingAnalysis totals or global headline/procurement readiness.
- **Files:** `app/core/config.py` (2 new flags, default off), `app/services/pricing.py` (3-line flag-gated hook), new `app/services/sku_pricing/pilot.py`, `tests/test_sku_pricing_source_truth_pilot.py`.
- **Flags:** `ARCHWAY_ENABLE_SKU_PRICING_PILOT` (default false), `ARCHWAY_SKU_PRICING_SNAPSHOT_PATH` (default unset).
- **Tests:** 9 pilot + 29 SKU module + 21 existing pricing passed; flag-off behavior byte/behavior-equivalent.
- **Merge status:** stacked on `efe0849`; not on master. Base SKU branches unchanged.
- **Rollback:** discard branch (no master impact). With the flag off there is no live effect even if merged.
