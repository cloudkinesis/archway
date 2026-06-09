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

## I3. Audit-log robustness (`read_session_logs`)
- **What:** `app/core/logging.py` `json.loads(line)` over `audit.jsonl` has no
  per-line guard; a single corrupt/interrupted line can 500 `/diagnostics`,
  `/export`, and hydration. Append writes are unlocked.
- **Status:** open (not fixed on any branch).
- **Severity:** medium (availability of diagnostics/export/hydration).
- **Branch if fixed:** none.
- **Blocks internal pilot:** no (low probability locally), but recommended.
- **Next action:** focused branch — wrap line parsing in try/except and skip bad
  lines; consider write locking. Out of scope for the merged fix branches.

## I4. MCP URL allowlist / token egress
- **What:** `aws_docs_mcp_url` / `aws_pricing_mcp_url` are taken from env and
  POSTed to with the Bearer token attached, with no hostname allowlist
  (`aws_research_tools.py`). Only the web fallback results are allowlisted.
- **Status:** open.
- **Severity:** low (operator-trust; config-controlled, local-first).
- **Branch if fixed:** none.
- **Blocks internal pilot:** no (pilot does not require live MCP).
- **Next action:** add an optional hostname allowlist for MCP endpoints before
  any networked/multi-user deployment.

## I5. Healthcare diagram crossings / placement QA
- **What:** domain-specific diagram placement/crossing QA findings independent of
  icon embedding.
- **Status:** open.
- **Severity:** low-medium (presentation quality, not correctness; reported, not
  masked).
- **Branch if fixed:** none.
- **Blocks internal pilot:** no.
- **Next action:** track against the D2 compiler view catalog; ensure missing/
  degraded views are reported with reasons (they are) rather than silently dropped.

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
