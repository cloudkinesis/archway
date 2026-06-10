# RC2 Known Issues

Open issues tracked for RC2. "Blocks internal pilot" assumes the pilot uses
sanitized, non-sensitive use cases on a local-only deployment (see DECISIONS D9).

Legend — Status: `open` | `fixed-on-branch` | `wontfix-now`. Severity: low / medium / high.

---

## I1. Pre-existing e2e citation-coverage failure (flaky / state-sensitive)
- **What:** `tests/test_end_to_end_flow.py::test_utility_grid_flow_is_not_misclassified_as_rag_assistant`
  asserts `citation_coverage.passed is False`, but the run often yields `True`.
- **Status:** open. Present on baseline `f692c04`; unrelated to any fix branch
  (research does not import the job system / governance / pricing-presentation).
  Also sensitive to leftover `.archway` state.
- **Severity:** low (test-only; no product impact).
- **Branch if fixed:** none.
- **Blocks internal pilot:** no.
- **Next action:** triage once — make the assertion deterministic or quarantine
  it — then wire CI so it is not re-proven by hand on every branch.

## I2. Utility metric label failure (`outage_reduction_target_percent`)
- **What:** `tests/test_synthesis.py::test_utility_metrics_and_business_goals_are_structured`
  raised `KeyError: 'outage_reduction_target_percent'` in earlier runs.
- **Status:** open if still present on a clean baseline run (verify; it was a
  pre-existing baseline failure, not introduced by any fix branch).
- **Severity:** low (metric label/extraction expectation; test-only signal).
- **Branch if fixed:** none.
- **Blocks internal pilot:** no.
- **Next action:** confirm on a clean `f692c04` run; if real, scope a focused
  metric-extraction fix branch (do NOT fold into unrelated branches).
- **Update:** re-confirmed pre-existing on a clean `f692c04` stash during the
  `feature/any-usecase-capability-router` work; still OPEN and deliberately NOT chased
  in that branch (excluded from its green run).

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
