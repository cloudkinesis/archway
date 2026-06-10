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

### feature/sku-pricing-official-snapshot-builder — `b92b98f` (base: `feature/sku-pricing-source-truth-pilot` @ `c301362`)
- **Purpose:** convert the SKU stack from fixture-demonstrated to OFFICIAL-source-backed. An offline builder ingests operator-provided official AWS Price List offer files, hashes the RAW official bytes (DECISIONS D11), deterministically maps them to Archway dimension keys (exact usagetype, region-prefix aware), and fails closed on ambiguity/unit/region/tier. Also splits rate authority from quantity confidence so assumed quantities can never reach pilot procurement-ready.
- **Files:** new `app/services/sku_pricing/official_snapshot_builder.py`, `scripts/build_sku_price_snapshot.py`, `tests/test_sku_pricing_official_snapshot_builder.py`, `tests/fixtures/sku_pricing/official_offer_slices/*` (small real-shape slices, ≤7 KB); edits to `app/services/sku_pricing/{__init__,cache,pilot,provenance}.py` and `tests/test_sku_pricing_source_truth_pilot.py`. No frontend/export/routes/global-pricing changes.
- **Validation:** run against the REAL us-east-1 offer files (downloaded, NOT committed). Maps **9 of 10** supported dimensions with correct real rates; EventBridge intentionally unsupported (KNOWN_ISSUES I10). Output loads via `load_local_cache_snapshot` and is consumed by the source-truth pilot; assumed quantities keep `sku_pilot_procurement_ready=false`.
- **Tests:** 19 builder + 38 SKU stack + 21 existing pricing passed (78 total). Flag-off behavior unchanged.
- **Merge status:** stacked on `c301362`; not on master. Base SKU branches unchanged.
- **Rollback:** discard branch (no master/live impact). Builder/CLI are invoked manually; runtime only reads a pre-built cache.

### feature/verifiable-dossier-sku-export-ux — `91ad37d` (base: `feature/sku-pricing-official-snapshot-builder` @ `b92b98f`)
- **Purpose:** the anti-bloat trust spine. Adds a verifiable dossier manifest (`dossier_manifest.json`), supplemental SKU pilot trace export (JSON/CSV/Markdown), an offline verifier script, an offline diff script, and a read-only TrustPanel UI. Every export artifact + UI trust signal maps back to the manifest (DECISIONS D12).
- **Files:** new `app/services/dossier_manifest.py`, `app/services/sku_pricing/export_trace.py`, `scripts/verify_solution_dossier.py`, `scripts/diff_solution_dossiers.py`, `frontend/src/components/TrustPanel.tsx`, `docs/dossier_integration_notes.md`, and 4 test files; additive edits to `app/services/export_package.py`, `app/services/sku_pricing/pilot.py` (emits `upstream_source`/`version_hash`), `frontend/src/components/App.tsx` (one import + one render line).
- **Safety:** does not change legacy pricing totals; does not promote global `headline_safe`/`procurement_ready` (manifest keeps `pricing.global` separate from `pricing.sku_pilot`); SKU pilot stays supplemental; fixture-backed rates never shown authoritative; no runtime network (only a local `git` subprocess for commit/branch). TrustPanel never claims verification from manifest presence; verifier warns on partial SKU provenance and fails under `--strict`.
- **Tests:** dossier suites 25 passed, SKU stack 57 passed, export/pricing 26 passed, anti-drift 20 passed, offline socket-blocked proof 23 passed; frontend build passed (`tsc -b && vite build`).
- **Merge status:** READY_FOR_CODEX_REVIEW — stacked on `b92b98f`; not on master.
- **Rollback:**
  - Before merge: delete/reset the feature branch; no master impact.
  - To revert the feature-branch commit directly: `git revert 91ad37d`.
  - To revert a later `--no-ff` merge into master/integration: `git revert -m 1 <merge_commit_sha>`.
  - (Additive/flag-aware; runtime pricing is unchanged regardless.)

### fix/audit-log-robustness — `db77e0c` (base: master baseline `f692c04`)
- **Purpose:** hardening branch — make audit-log reading/writing robust so a corrupt
  `audit.jsonl` can never crash diagnostics, export, session hydration, the debug
  bundle, or readiness. Malformed/non-object/partial lines are skipped with structured
  warnings (`AuditReadResult`: `ok|degraded|missing|unreadable`); blank lines ignored.
  Adds recursive secret/token redaction (with an innocent-key allowlist) applied on
  write AND read; the writer never crashes the main flow on a write error.
- **Files:** `app/core/logging.py` (safe `read_audit_jsonl`/`read_session_audit`,
  `redact_sensitive`, hardened writer), `app/services/export_package.py` (adds a
  `raw/audit_log.json` payload + non-blocking degraded warning), new
  `tests/test_audit_log_robustness.py`. No pricing/architecture/discovery/frontend/
  diagram/governance/domain-pack/SKU/dossier files touched.
- **Safety:** audit degradation is warning-level, never a blocker (DECISIONS D13); no
  readiness/pricing/governance/diagram gate changed; secrets never leak through audit
  evidence; innocent keys (`author`/`token_count`/…) preserved.
- **Tests:** audit robustness 18 passed (incl. export integration); export+session
  hydration 6 passed; pricing 21 passed; anti-drift 20 passed (65 total).
- **Merge status:** READY_FOR_CODEX_REVIEW — off baseline `f692c04`; not on master.
  Stage 3 in MERGE_PLAN. Conflict expected in `export_package.py` with dossier/export
  branches — preserve both the `audit_log` payload and dossier/SKU exports.
- **Rollback:**
  - Before merge: delete/reset the branch; no master impact.
  - To revert the commit directly: `git revert db77e0c`.
  - To revert a later `--no-ff` merge: `git revert -m 1 <merge_commit_sha>`.

### fix/mcp-url-allowlist — `b6a51d7` (base: master baseline `f692c04`)
- **Purpose:** security/trust hardening — MCP endpoints are privileged integration
  points (DECISIONS D14). Bearer/API tokens are never sent to arbitrary/untrusted
  external MCP hosts. localhost + private network trusted by default; external hosts
  require explicit allowlist or global opt-in; AWS-managed `.api.aws` trusted by
  default; unsupported schemes / malformed URLs / embedded credentials blocked.
  Untrusted endpoints fail closed (no token, no call) into existing fallbacks.
- **Files:** new `app/services/mcp_security.py` (`validate_mcp_endpoint_url`,
  `McpUrlValidationResult`, `mcp_security_status`, `sanitize_mcp_url`), new
  `tests/test_mcp_url_allowlist.py`; edits to `app/core/config.py` (4 trust flags),
  `app/services/mcp_http.py` (validate + fail-closed + token guard), `app/api/routes.py`
  + `app/services/export_package.py` (token-safe `mcp_security` diagnostics/export).
  No pricing-calc / research-ranking / frontend / architecture / discovery / diagram /
  governance / domain-pack / SKU / dossier files touched.
- **Safety:** no token egress to untrusted hosts; diagnostics/export sanitize URLs
  (no userinfo/query/fragment) and never expose tokens; pricing/research ranking
  unchanged — only whether the unsafe MCP call is attempted; no live network in tests.
- **Tests:** MCP allowlist 19 passed; mcp_http+aws_research+health 9; keyword-mcp 26;
  pricing 21; export+session 6; anti-drift 20 (101 total).
- **Merge status:** READY_FOR_CODEX_REVIEW — off baseline `f692c04`; not on master.
  Stage 3 in MERGE_PLAN. Conflict expected in `export_package.py` + `routes.py` with
  the audit (item 8) and dossier/export (item 14) branches — preserve `mcp_security`
  alongside `audit_log` and dossier/SKU export payloads.
- **Rollback:**
  - Before merge: delete/reset the branch; no master impact.
  - To revert the commit directly: `git revert b6a51d7`.
  - To revert a later `--no-ff` merge: `git revert -m 1 <merge_commit_sha>`.

### feature/any-usecase-capability-router — `445c6de` (base: master baseline `f692c04`)
- **Purpose:** the any-usecase handling contract (DECISIONS D15). Adds the deterministic
  `CapabilityRouter` (supported / directional / discovery_needed / unsupported_or_blocked)
  and reuses the EXISTING `DiscoveryPlanner` (via `ModelRouter`) as a quarantined,
  advisory model prior — no parallel prior subsystem, no new external model client.
- **Files:** new `app/services/capability_router.py` (router + deterministic abuse
  blocker + sensitivity screen + per-session budget/cache), new
  `tests/test_capability_router.py`; edits to `app/services/discovery_planner.py`
  (flag-gating + quarantined merge + provenance), `app/services/synthesis.py` (router
  wiring), `app/services/use_case_profile.py` (`capability_decision` metadata),
  `app/core/config.py` (2 flags), and `tests/test_discovery_planner.py` (1 test updated
  to the opt-in/dominance behavior). No pricing-calc / architecture / governance /
  diagram / frontend / SKU / dossier / MCP / audit files touched.
- **Safety:** frontier prior OFF by default (`ARCHWAY_ENABLE_FRONTIER_DOMAIN_PRIOR=false`,
  cap 1); model influence quarantined to questions + generic fallback candidate;
  model pricing-driver names no longer reach pricing; deterministic-known dominates;
  unsafe/abusive → `unsupported_or_blocked` (no fake architecture); sensitive unknown
  (secrets / PHI-HIPAA markers) skips the model prior, deterministic fallback continues.
  No new egress; `ModelRouter` (Bedrock/Ollama) only.
- **Tests:** capability_router + discovery 24; healthcare anti-drift + scenario matrix
  15; pricing trio 21; export + session 6 (66 total). Pre-existing I2 synthesis failure
  excluded/not chased.
- **Merge status:** READY_FOR_CODEX_REVIEW — off baseline `f692c04`; not on master.
  Stage 5 in MERGE_PLAN. Conflict risk in discovery_planner/synthesis/use_case_profile/
  config; preserve the model-prior quarantine + pricing-driver leakage fix on merge.
- **Rollback:**
  - Before merge: delete/reset the branch; no master impact.
  - To revert the commit directly: `git revert 445c6de`.
  - To revert a later `--no-ff` merge: `git revert -m 1 <merge_commit_sha>`.

### fix/healthcare-diagram-crossings — `8d07ac0` (base: master baseline `f692c04`)
- **Purpose:** diagram-quality fix — introduces a reusable `DomainLaneModel` framework
  and a healthcare OR lane adapter so the production logical service-flow diagram passes
  the existing crossing gate (14 → ≤8) without weakening QA. Generic IoT/telemetry lane
  planning stays the unchanged fallback for non-specialized domains.
- **Files:** `app/services/lane_planner.py` (new domain-aware lane framework +
  `HEALTHCARE_OPERATIONS_LANE_MODEL`), `app/services/pattern_catalog.py` (select the
  domain model else generic fallback; route the healthcare governance/observability
  fan-out to a detail-only sidecar), new `tests/test_healthcare_diagram_crossings.py`. No
  external diagram-compiler / pricing / research / synthesis / discovery / frontend / SKU /
  dossier / MCP / audit files touched.
- **Safety:** no external compiler changes (its crossing/readability gates remain
  authoritative); crossing threshold remains 8 (`logical_edge_crossing_max`); healthcare
  semantics preserved (approval write-back, PHI/security, audit/governance sidecar, no IoT
  leakage); governance fan-out is PRESERVED (moved to detail-only and recorded in flow
  metadata — never dropped); generic fallback byte-identical for non-healthcare; no
  generated SVG/PNG/D2/export artifacts committed (DECISIONS D16).
- **Tests:** 30 focused healthcare/scenario tests passed post-commit (new crossing suite
  10 + healthcare anti-drift/operations 12 + scenario matrix 8). Full-branch verification:
  152 passed / 2 pre-existing known failures (KNOWN_ISSUES I1/I2, re-confirmed on a clean
  `f692c04` stash; not introduced here).
- **Merge status:** READY_FOR_CODEX_REVIEW — off baseline `f692c04`; not on master.
  Stage 6 in MERGE_PLAN (before final validation). Conflict risk in `pattern_catalog.py`
  (also edited by `fix/typed-effectful-flow-detection` and the capability-router/domain-pack
  branches) and the new `lane_planner.py`.
- **Rollback:**
  - Before merge: delete/reset the feature branch; no master impact.
  - To revert the commit directly: `git revert 8d07ac0`.
  - To revert a later `--no-ff` merge into master/integration: `git revert -m 1 <merge_commit_sha>`.

### chore/internalize-diagram-compiler — `4368266` (base: master baseline `f692c04`)
- **Purpose:** vendors `archway_diagram_compiler` into `packages/archway_diagram_compiler/`
  as a first-class internal package; the default runtime no longer depends on the external
  iCloud path `~/Documents/Archway Diagram Compiler`. Migration-only — no compiler logic
  rewritten, no diagram-quality change (the healthcare crossing issue still reproduces on
  this branch by design; the fix lives in `fix/healthcare-diagram-crossings`).
- **Source provenance** (full record in `packages/archway_diagram_compiler/SOURCE.md`):
  - External path: `~/Documents/Archway Diagram Compiler`.
  - External HEAD: `c9a8031` ("Initial archway diagram compiler" — the only commit in that
    repo's history).
  - Source type: **working-tree snapshot, NOT clean HEAD**; SOURCE.md lists all 12 dirty
    files copied (+223/−26 vs HEAD).
  - Reason: the Archway runtime always imported the working tree via sys.path injection —
    including the `semantic_archway` lane machinery, which does not exist in HEAD; vendoring
    HEAD-only would have changed compiler behavior and broken the healthcare lane adapter.
- **Files:** new `packages/archway_diagram_compiler/**` (93 files: compiler src, icon SVG
  package data, tests, pyproject, README, SOURCE.md); edits to
  `app/services/diagram_compiler_adapter.py` (internal-first import + `compiler_source`
  reporting), `app/core/config.py` (`diagram_compiler_path` is explicit-override-only,
  no iCloud default), new `tests/test_internal_diagram_compiler_import.py`,
  `.env.example` (documents override as optional/debug), `.gitignore` (adds `.tools/`).
- **Safety:** external compiler repo NOT modified (read-only source; no gc/prune/fsck run
  anywhere); no QA thresholds changed — `logical_edge_crossing_max` remains 8; external
  override is explicit/debug-only and warns `diagram_compiler_source = external_override`
  (never silent); the local renderer binary `.tools/d2/d2` (~44 MB) is gitignored and NOT
  committed; without the d2 binary, compilation degrades honestly (`.d2` artifacts +
  `d2_executable_not_found` QA failure — nothing faked).
- **Tests** (run with `ARCHWAY_DIAGRAM_COMPILER_PATH` blanked to prove iCloud independence):
  internal import suite 6 passed; diagram/lane/crossing selection 19 passed; healthcare
  anti-drift + scenario matrix 15 passed; export/session 6 passed; post-commit smoke 16
  passed. Behavior equivalence proven: baseline healthcare OR reproduces exactly
  "14 visible edge crossing(s); limit is 8" through the internal compiler.
- **Merge status:** READY_FOR_CODEX_REVIEW — off baseline `f692c04`; not on master.
  Stage 6 item 16 in MERGE_PLAN — merge BEFORE `fix/healthcare-diagram-crossings`.
- **Rollback:**
  - Before merge: delete/reset the feature branch; no master impact.
  - To revert the commit directly: `git revert 4368266`.
  - To revert a later `--no-ff` merge into master/integration: `git revert -m 1 <merge_commit_sha>`.

### integration/rc2-golden-rehearsal — `ee534db` (base: master baseline `f692c04`)
- **Purpose:** RC2 golden rehearsal — merges ALL reviewed branches in the documented
  MERGE_PLAN order to prove the stack integrates cleanly and is a viable Codex merge
  candidate. Merge/rehearsal branch only; not a feature branch; NOT merged to master.
- **Merge order executed** (15 `--no-ff` merges, 2026-06-10):
  1. `integration/rc2-stabilization-claude` (tip `068d5ca` = `a23e676` + its docs-only
     integration review note — no code delta vs the recorded hash)
  2. `fix/pricing-headline-fail-closed` (`f39852b`)
  3. `fix/export-pricing-headline-fail-closed` (`439b73b`)
  4. `feature/rc2-validation-harness` (`47782f1`)
  5. `fix/audit-log-robustness` (`db77e0c`)
  6. `fix/mcp-url-allowlist` (`b6a51d7`)
  7. `chore/internalize-diagram-compiler` (`4368266`)
  8. `feature/any-usecase-capability-router` (`445c6de`)
  9. `fix/healthcare-diagram-crossings` (`8d07ac0`)
  10–13. SKU stack bottom-up: `9b168d7` → `efe0849` → `c301362` → `b92b98f`
  14. `feature/verifiable-dossier-sku-export-ux` (`91ad37d`)
  15. `docs/rc2-decision-log` (`d050ce8`)
  Deferred branches (domain-pack experiment/phase2) were NOT merged.
- **Conflicts (resolved keep-both per MERGE_PLAN rules; no gate loosened, nothing dropped):**
  - `export_package.py` (audit merge): crash-safe `read_session_audit` + degraded warning
    PLUS Stage-1 loop-safe `_collect_async` build-status collection.
  - `export_package.py` (MCP merge): raw payloads carry BOTH `audit_log` AND `mcp_security`.
  - `config.py` (capability-router merge): job-TTL fields PLUS frontier-prior flags (default off, cap 1).
  - `config.py` (SKU pilot merge): all prior fields PLUS SKU pilot flags (default off).
  - `export_package.py` (dossier merge): imports only — audit + MCP + dossier/SKU-trace
    imports coexist; body auto-merged. Final file preserves export-quality artifacts,
    fail-closed pricing (`get(..., False)`), `audit_log`, `mcp_security`,
    `dossier_manifest.json`/`.md`, `README_DOSSIER.md`, SKU pilot trace files, and the
    legacy `manifest.json`.
- **Tests:** focused battery 196 passed; pricing trio 21; discovery/healthcare/matrix 20;
  export/hydration 11; diagram selection (external compiler path blanked) 32. Full suite:
  **363 passed / 2 failed — only the documented known failures I1 + I2; zero new failures.**
  Harness: focused **READY**; stabilization+frontend **READY** (62); golden+frontend
  **READY_WITH_KNOWN_ISSUES** (363 / 2 known / 0 new). Frontend build passed.
- **Golden export validation** (real end-to-end runs, isolated data dir): legal contract
  RAG, healthcare OR, telecom HBase/HDFS — all exported with zero blockers; WARNs were
  honest by-design statuses (info-level enrichment diagnostics; directional pricing per
  D3). Healthcare logical view rendered with **0 crossing violations**; no IoT leakage in
  the healthcare architecture (IoT strings appear only in the cross-scenario
  `golden_regression_summary.json` baseline). **Verifier VALID on all three packages**
  (89/85/75 artifacts checked, 0 mismatched, 0 missing; SKU pilot honestly recorded
  absent with the flag off). No tokens/secrets in exports; no generated artifacts staged.
- **Known failures:** I1 (e2e citation coverage) and I2 (`outage_reduction_target_percent`)
  only — accepted known exceptions for the rehearsal (see KNOWN_ISSUES).
- **Merge status:** READY_FOR_CODEX_REVIEW — recommended Codex review candidate for the
  master merge. Not on master.
- **Rollback:** delete/reset the rehearsal branch (no master impact), or
  `git revert -m 1 <merge_commit>` for any individual stage on the branch.
