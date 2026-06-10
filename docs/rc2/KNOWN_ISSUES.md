# RC2 Known Issues

Open issues tracked for RC2. "Blocks internal pilot" assumes the pilot uses
sanitized, non-sensitive use cases on a local-only deployment (see DECISIONS D9).

Legend — Status: `open` | `fixed-on-branch` | `wontfix-now`. Severity: low / medium / high.

---

## I1. Pre-existing e2e citation-coverage failure (flaky / state-sensitive) — FIXED (`6081c76`)
- **What:** `tests/test_end_to_end_flow.py::test_utility_grid_flow_is_not_misclassified_as_rag_assistant`
  asserted `citation_coverage.passed is False`, but the run often yielded `True`.
- **Status:** FIXED by `fix/utility-grid-e2e-citation-determinism` @ `6081c76` (off
  baseline `f692c04`).
- **Root cause:** PRODUCT BEHAVIOR WAS NOT WRONG. The test was under-isolated and used
  citation coverage / research-quality as an ENVIRONMENT-SENSITIVE PROXY for
  classification: with AWS Docs MCP evidence configured in the local `.env`, research
  legitimately cited all claims ("Official MCP Evidence", `passed=True`); offline it
  failed closed ("Limited", `passed=False`). The test pinned `ARCHWAY_DATA_DIR` but not
  the evidence-source configuration, so its result tracked `.env`/network, never
  classification — the entire "flaky/state-sensitive" history.
- **Resolution:** the test now PINS all evidence sources off (MCP/web/Tavily disabled
  per-test; settings cache cleared and restored via try/finally), making the offline
  honesty invariant (no evidence → coverage fails closed + "Limited") deterministic on
  any machine, with no live network calls in tests. The actual anti-RAG classification
  invariant is asserted directly and STRENGTHENED: utility grid is never
  `rag_assistant` / `document_rag_assistant` / `document_intelligence`, and the pricing
  family is `INDUSTRIAL_IOT_STREAMING`, not document RAG. No assertion was blindly
  flipped; no app source changed.
- **Severity:** low → resolved.
- **Blocks internal pilot:** no.
- **RC2 rehearsal note (2026-06-10):** on `integration/rc2-golden-rehearsal @ ee534db`
  (all reviewed branches merged) the full suite showed **exactly two failures — I1 and
  I2 only; zero new failures** — accepted known exceptions at that time, surfaced via
  READY_WITH_KNOWN_ISSUES rather than laundered green.
- **Cleanup status:** with BOTH fix branches merged — `6081c76` (I1, test-only) and
  `1138849` (I2, see below) — the previous full-suite known failures should be CLEARED
  and a v2 integration candidate is expected to run fully green.

## I2. Utility metric label failure (`outage_reduction_target_percent`) — FIXED (`1138849`)
- **What:** `tests/test_synthesis.py::test_utility_metrics_and_business_goals_are_structured`
  raised `KeyError: 'outage_reduction_target_percent'`.
- **Status:** FIXED by `fix/utility-metric-structuring` @ `1138849` (off baseline
  `f692c04`).
- **Root cause:** metric-extractor consolidation drift — the value was always extracted
  correctly (45.0, percent), but the profile-level public label drifted from
  `outage_reduction_target_percent` to the structured extractor's
  `unplanned_outage_reduction_percent` when the profile layer became a compatibility
  view over the shared extractor (the exact two-extractor drift mode flagged in
  DECISIONS D1).
- **Resolution:** backward-compatible alias at the compatibility-view boundary restores
  the profile-level public label; the structured-extractor key is UNCHANGED for its
  direct consumers (golden metric-extraction tests still pass). Phrasing made
  deterministic across `reduce|reduces|reducing`, mirrored in BOTH extractors so they
  stay in agreement. Regression test added (alias stability, no structured-key leak,
  JSON-serializable output).
- **Severity:** low → resolved.
- **Blocks internal pilot:** no.
- **Earlier history:** re-confirmed pre-existing on clean `f692c04` stashes during the
  capability-router work and on `integration/rc2-golden-rehearsal @ ee534db` (where it
  was one of the only two full-suite failures, accepted as a known exception).
- **Post-fix note:** with `1138849`, the full suite on a baseline-based branch shows
  **144 passed / 1 failed — only I1 remains** from the previous known failures.
- **Merge note:** `use_case_profile.py` is also edited by
  `feature/any-usecase-capability-router` — on merge preserve BOTH the
  `capability_decision` metadata and the outage metric alias.

## I3. Audit-log robustness (`read_session_logs`) — FIXED (`db77e0c`)
- **What:** `app/core/logging.py` `json.loads(line)` over `audit.jsonl` had no
  per-line guard; a single corrupt/interrupted line could 500 `/diagnostics`,
  `/export`, and hydration. Append writes were unlocked.
- **Status:** FIXED by `fix/audit-log-robustness` @ `db77e0c` (off baseline `f692c04`).
- **Resolution:** a centralized crash-safe reader (`read_audit_jsonl` →
  `AuditReadResult`) skips malformed / non-object / partially-written lines with
  STRUCTURED warnings (`malformed_json` / `non_object_json` / `read_error`) and a
  `status` of `ok|degraded|missing|unreadable`; blank lines are ignored. Diagnostics,
  export, hydration, and the debug bundle now complete on a corrupt log. Events are
  recursively REDACTED (secrets/tokens/keys → `<redacted>`, with an allowlist so
  innocent keys like `author`/`token_count` survive); the writer redacts before
  persisting and never crashes the main flow on a write error. Export records
  `audit_log_status` / `audit_log_warnings` in `raw/audit_log.json` and surfaces a
  non-blocking warning when degraded.
- **Severity:** medium → resolved.
- **Blocks internal pilot:** no.
- **Merge note:** `app/services/export_package.py` is edited by this branch (adds the
  `audit_log` payload). Expect a conflict with the dossier/export branches that also
  touch export generation (KNOWN_ISSUES I9 / DECISIONS D12) — resolve by PRESERVING
  BOTH the `audit_log` payload and the dossier manifest / SKU trace exports.

## I4. MCP URL allowlist / token egress — FIXED (`b6a51d7`)
- **What:** `aws_docs_mcp_url` / `aws_pricing_mcp_url` were taken from env and
  POSTed to with the Bearer token attached, with no hostname allowlist
  (`aws_research_tools.py`). Only the web fallback results were allowlisted.
- **Status:** FIXED by `fix/mcp-url-allowlist` @ `b6a51d7` (off baseline `f692c04`).
- **Resolution:** centralized `app/services/mcp_security.py`
  (`validate_mcp_endpoint_url` / `McpUrlValidationResult`) classifies every MCP URL
  (localhost / private_network / allowed_external / untrusted_external / invalid /
  unsupported_scheme) using `urllib.parse` + `ipaddress`:
  - Unsafe external MCP URLs are **blocked by default** (`untrusted_external`).
  - **localhost / private network** endpoints remain **allowed by default**
    (`ARCHWAY_MCP_ALLOW_LOCALHOST` / `ARCHWAY_MCP_ALLOW_PRIVATE_NETWORK`, both true).
  - External hosts require an explicit allowlist (`ARCHWAY_MCP_ALLOWED_HOSTS`) or the
    global opt-in (`ARCHWAY_MCP_ALLOW_EXTERNAL=true`); AWS-managed `.api.aws` stays
    trusted by default (DECISIONS D14).
  - The **bearer/API token is never attached to an untrusted host**: `MCPHTTPClient`
    fails closed before building headers or making any HTTP call, and `_headers()` is
    guarded as defense in depth.
  - Diagnostics/export expose a token-safe `mcp_security` status (sanitized URL — no
    userinfo/query/fragment); tokens are never logged or exported.
- **Severity:** low → resolved.
- **Blocks internal pilot:** no.
- **Merge note:** touches `config.py`, `routes.py`, `export_package.py`, `mcp_http.py`
  — expect conflicts with the audit/dossier/export branches; preserve the
  `mcp_security` diagnostics/export payloads alongside `audit_log` and dossier/SKU
  exports.

## I5. Healthcare diagram crossings / placement QA — FIXED (`8d07ac0`)
- **What:** the healthcare OR production logical service-flow diagram rendered with 14
  visible edge crossings against a gate of 8 — the generic IoT/telemetry lane planner
  mis-grouped clinical components and the governance/observability fan-out crisscrossed the
  primary view. (Domain-specific placement/crossing QA, independent of icon embedding.)
- **Status:** FIXED by `fix/healthcare-diagram-crossings` @ `8d07ac0` (off baseline
  `f692c04`).
- **Resolution:** a reusable `DomainLaneModel` framework (`app/services/lane_planner.py`)
  with a healthcare OR lane adapter places clinical components into ordered lanes
  (Clinical Source Systems → Private Integration → PHI-safe Operational State → Decision
  Intelligence → Approval & Command Center) and routes the governance/observability fan-out
  into a detail-only sidecar (`logical_detail_only`, flows preserved). The production
  logical healthcare OR crossing count now PASSES the UNCHANGED 8-crossing gate
  (DECISIONS D16). Healthcare semantics preserved: approval write-back path, PHI/security
  posture, audit/governance sidecar, no IoT leakage. The generic lane fallback is unchanged
  for non-healthcare domains.
- **Severity:** low-medium → resolved.
- **Blocks internal pilot:** no.
- **Merge note:** touches `app/services/pattern_catalog.py` (also edited by
  `fix/typed-effectful-flow-detection` and the capability-router/domain-pack branches) and
  the new `app/services/lane_planner.py`; see MERGE_PLAN Stage 6.

## I6. Frontend monolith
- **What:** ~2,190 lines in `frontend/src/components/App.tsx` (~82% of frontend TS).
- **Status:** open (deferred).
- **Severity:** medium (maintainability/review surface, not functional).
- **Branch if fixed:** none.
- **Blocks internal pilot:** no.
- **Next action:** defer; extract phase views (Research/Pricing/Diagram tabs)
  post-stabilization.

## I7. Domain-pack migration incomplete
- **What:** registry is Phase 1 (read-only) + Phase 2A (advisory pricing
  metadata). Domain logic still lives across classifier/synthesis/pricing/pattern
  catalog/dossier/governance.
- **Status:** open (intentional; feature-flagged, default off).
- **Severity:** medium (structural debt / drift risk when adding domains).
- **Branch if fixed:** partial — `experiment/domain-pack-interface`,
  `feature/domain-pack-phase2-pricing-drivers`.
- **Blocks internal pilot:** no.
- **Next action:** defer remaining migration until after Codex review of the
  experiment branches.

## I8. Procurement-ready pricing mostly aspirational without MCP/SKU binding
- **What:** procurement-ready requires confirmed drivers + usage dimensions +
  exact SKU/rate binding; with MCPs off by default and fuzzy rate matching, most
  line items remain heuristic, so procurement-ready is effectively unreachable in
  a default local setup. Customer readiness is similarly capped at
  directional-only without the optional MCPs.
- **Status:** open / by-design honesty (not a bug; an expectation gap).
- **Severity:** medium (product-positioning, not correctness).
- **Branch if fixed:** none (presentation already fails closed — see DECISIONS D2/D3).
- **Blocks internal pilot:** no.
- **Next action:** product decision — state the ladder honestly (directional is
  the default ceiling), and decide whether to invest in live SKU/rate binding to
  make the top rungs reachable.
- **Update:** an SKU-backed pricing stack now exists (foundation `9b168d7`,
  local-cache adapter `efe0849`, supplemental pilot `c301362`, official snapshot
  builder `b92b98f`) that can produce reproducible, SKU-traceable, provenance-gated
  estimates for a narrow service set. As of the official snapshot builder these
  rates can be backed by REAL AWS Price List offer-file data (validated us-east-1,
  9 of 10 supported dimensions; see I10), hashed over raw official bytes (DECISIONS
  D11). It is standalone/flag-gated and does not yet change live readiness (see I9).

## I9. SKU pricing pilot trace not surfaced in live UI / export
- **What:** the SKU-backed pilot trace (`metadata["sku_pricing_pilot"]`, branch
  `feature/sku-pricing-source-truth-pilot` @ `c301362`) is attached to pricing
  metadata when the flag is on, but the frontend UI and the export package do not
  yet render or include it. Export integration was intentionally out of scope for
  the pilot branch (no `export_package`/frontend changes).
- **Status:** open (by design for the pilot; surfacing is a future branch).
- **Severity:** low (additive metadata exists; just not presented).
- **Branch if fixed:** none yet.
- **Blocks internal pilot:** no.
- **Next action:** a future branch to (a) include the SKU pilot trace in the export
  raw payloads / a dedicated pricing-trace artifact, and (b) optionally surface a
  read-only "SKU-backed (pilot)" panel in the UI — keeping it clearly supplemental
  and never promoting global readiness (DECISIONS D10).
- **Update (`91ad37d`):** RESOLVED for surfacing. The verifiable dossier branch
  (`feature/verifiable-dossier-sku-export-ux`) now surfaces the SKU pilot trace in
  the export package (`pricing/sku_pricing_pilot_trace.json|.csv|.md`,
  `dossier_manifest.json`) and a read-only TrustPanel in the UI, honestly showing the
  `rate_authoritative` vs `quantities_confirmed` split. **Still open:** product-level
  pricing *replacement* (SKU-backed totals superseding the legacy headline) is NOT
  done and is deliberately out of scope — the SKU pilot remains supplemental.

## I10. EventBridge custom events unsupported in SKU-backed pilot pricing
- **What:** the official snapshot builder
  (`feature/sku-pricing-official-snapshot-builder` @ `b92b98f`) intentionally does
  NOT emit a rate for `eventbridge_custom_events`. Real AWS EventBridge billing
  (offerCode `AWSEvents`) prices custom events per **`64K-Chunks`** (per 64 KB), not
  per raw **`Events`** as the pilot models. Equating them needs an unverified
  event-size/chunk assumption, so the dimension fails closed
  (`UNSUPPORTED_OFFICIAL_DIMENSIONS`).
- **Status:** open / by-design fail-closed (validated against real us-east-1 data).
- **Severity:** low (one optional pilot dimension; everything else maps).
- **Branch if fixed:** none yet.
- **Blocks internal pilot:** no.
- **Next action:** do NOT estimate EventBridge until event-size → 64KB-chunk
  quantity modeling exists (chunks = ceil(event_bytes / 65536) × events). Then add
  a `64K-Chunks` dimension and a documented conversion; until then keep it
  unsupported. Honesty note: the builder maps **9 of 10** supported dimensions —
  not "all 10".

## I11. Dossier diff is manifest/artifact-level only
- **What:** `scripts/diff_solution_dossiers.py` (branch `91ad37d`) compares manifest
  fields and artifact hashes (inputs, pricing totals, SKU subtotal, snapshot/trace
  hashes, architecture/diagram hashes, readiness/blockers). It does NOT recompute
  scenarios or perform a semantic architecture/diagram diff.
- **Status:** open / by-design scope limit.
- **Severity:** low.
- **Blocks internal pilot:** no.
- **Next action:** semantic scenario recomputation + diff is future work (a separate
  branch); keep the manifest-level diff as the fast, deterministic baseline.

## I12. TrustPanel shows trust state but does not itself verify hashes
- **What:** the UI TrustPanel (branch `91ad37d`) renders manifest/pricing trust state
  (manifest present/missing, pricing mode, rate authority, quantity confirmation,
  known gaps). It does NOT recompute artifact hashes; it never claims "verified" from
  manifest presence alone.
- **Status:** open / by-design (in-browser hash verification is out of scope).
- **Severity:** low.
- **Blocks internal pilot:** no.
- **Next action:** run the offline verifier (`python scripts/verify_solution_dossier.py
  <export>`, optionally `--strict`) for actual hash verification. A future option could
  embed a verifier result into the UI to flip the badge to "verified".

## I13. Capability routing is directional/generic for unknown domains
- **What:** the any-usecase handling contract (DECISIONS D15) is implemented by
  `feature/any-usecase-capability-router` @ `445c6de`: every normal use case is routed
  to `supported` / `directional` / `discovery_needed` / `unsupported_or_blocked`. For
  domains without a specialized pack, routing is `directional`/`discovery_needed` mapped
  to a GENERIC fallback family — it does NOT mean every domain has a specialized
  domain pack or deep modeling (related to I7).
- **Status:** by-design honesty (not a defect). The router widens *handling*, not depth.
- **Severity:** low (expectation-setting).
- **Blocks internal pilot:** no.
- **Next action:** treat unknown-domain output as directional; invest in specialized
  packs per vertical over time (I7). The frontier model prior is advisory-only and
  cannot upgrade an unknown domain to `supported`.
- **Accelerator-pack note (`1fc93de`, next-wave — NOT a blocker):** capability
  accelerator packs (`network_security_observability`, `hcm_payroll_workforce`;
  DECISIONS D18) are advisory INTAKE improvements — better questions and fallback
  hints only. They are NOT proof of full domain specialization: unknown domains still
  route to directional/generic unless a real domain pack or deterministic pattern
  exists. I13 remains intact and by-design.
- **Wave-2 update (`d3d7242`):** accelerator coverage has expanded (firewall/SecOps,
  smart spaces/location IoT, open banking/payments, financial-crime/risk operations —
  six packs total), but this still does NOT mean every domain has specialist
  domain-pack depth. Unknown domains remain directional/generic unless backed by
  deterministic pattern/domain support.

## I14. Additional domain lane adapters are future work
- **What:** the `DomainLaneModel` framework (DECISIONS D16,
  `fix/healthcare-diagram-crossings` @ `8d07ac0`) ships ONE adapter (healthcare OR). Other
  domains still use the GENERIC lane fallback, so some non-healthcare scenarios can still
  exceed the crossing gate — e.g. `aml_graph` has a PRE-EXISTING production-logical
  crossing issue (22 crossings on baseline `f692c04`, unchanged by this branch) and is a
  natural next adapter candidate.
- **Status:** open / by-design scope limit (the framework is the reusable path; only the
  healthcare adapter is implemented in this branch).
- **Severity:** low-medium (presentation quality for un-adapted domains; reported, not
  masked).
- **Branch if fixed:** partial — `fix/healthcare-diagram-crossings` (healthcare only).
- **Blocks internal pilot:** no.
- **Next action:** add domain lane adapters per vertical over time (start with
  `aml_graph`), each mapping to recognized compiler lanes; never loosen the compiler gate.
  Unknown domains continue to use the generic lane fallback.

## I15. D2 renderer binary remains a local tool dependency
- **Context — hidden external/iCloud compiler dependency FIXED/REDUCED (`4368266`):**
  Archway previously depended on `~/Documents/Archway Diagram Compiler` (iCloud-synced,
  dirty working tree, sys.path-injected) for ALL diagram compilation — invisible to repo
  review and unreproducible across machines. `chore/internalize-diagram-compiler`
  @ `4368266` vendors the compiler source into `packages/archway_diagram_compiler/`
  (provenance in its SOURCE.md; DECISIONS D17), so the default runtime and tests no longer
  require the external path at all.
- **What remains:** SVG rendering shells out to the `d2` CLI (~44 MB Mach-O binary).
  `.tools/d2/d2` is INTENTIONALLY not committed (gitignored here, as it was in the external
  repo — it is a tool, not source). A fresh clone needs `d2` on PATH or a binary copied to
  `<repo>/.tools/d2/`; the compiler's `find_d2_executable()` resolves both.
- **Degradation behavior:** without the binary, diagram compilation degrades HONESTLY —
  `.d2` text artifacts are still produced and QA reports `d2_executable_not_found` /
  `missing_render_artifact`; SVG-based checks (crossing counts etc.) cannot run, and
  nothing is silently faked.
- **Status:** open / by-design (binaries do not belong in git).
- **Severity:** low (machine-setup concern; current machine has the binary installed at
  `~/Developer/Archway/.tools/d2/d2`).
- **Blocks internal pilot:** no (binary present locally).
- **Next action:** optionally add a small setup script / README note that downloads or
  copies a pinned `d2` version into `.tools/d2/`; pin the d2 version in SOURCE.md if
  renderer output ever needs byte-stable reproducibility across machines.

## I16. Trade-off / uncertainty / reviewer upgrades are future work (next-wave; NOT RC2 v2 blockers)
- **What:** an external review identified three highest-impact upgrades toward a
  "pressure-test the answer" workbench. Status:
  - **Decision records: IMPLEMENTED** by `feature/architecture-decision-records`
    @ `ac3d86b` (deterministic ADRs in dossier exports; DECISIONS D19).
  - **Semantic scenario recomputation / true what-if simulation** (cost, scale,
    resilience, compliance deltas via deterministic re-runs with perturbed inputs)
    remains FUTURE WORK.
  - **Unified uncertainty map** (per-section/per-decision confidence rollup over the
    existing scattered signals — research quality, citation coverage, assumption
    ledger, ADR confidence/evidence-class fields) remains FUTURE WORK.
  - **Reviewer mode** (consolidated pre-export pass over weak claims, brittle
    assumptions, and over-patterned recommendations, assembling the existing critique/
    quality-findings/consistency-check machinery) remains FUTURE WORK.
- **Status:** open / by-design scope limit. These are next-wave product upgrades, NOT
  blockers for the frozen RC2 v2 candidate.
- **Severity:** low (product depth, not correctness).
- **Blocks internal pilot:** no.
- **Next action:** sequence reviewer mode (mostly integration of existing findings +
  the new ADR fields), then deterministic what-if recomputation; keep both outside the
  v2 line and behind the usual branch-per-change discipline.
