# RC2 Merge Plan

Proposed order to bring reviewed fixes onto `master`. Nothing here is executed by
this doc; it is the recommended sequence and the review gate. All merges should be
`--no-ff`, after a full-suite run (see GOLDEN_GATE.md) and Codex review.

---

## Stage 1 — Stabilization (five fixes via the integration branch)
Merge order (already validated together on `integration/rc2-stabilization-claude`):
1. `fix/architecture-revision-lifecycle` (`332df7c`)
2. `fix/synthesis-completion-loop` (`bbc9df2`)
3. `fix/export-quality-artifacts` (`0dbe9e9`)
4. `fix/job-manager-lifecycle` (`3556efa`)
5. `fix/typed-effectful-flow-detection` (`8dafe82`)

Recommended path: review and merge the **integration branch** `a23e676` as the unit
(it is exactly these five, `--no-ff`, conflict-free), OR merge the five individually
in the same order. Run the full backend suite + frontend build on the result.

## Stage 2 — Pricing headline fail-closed
6. `fix/pricing-headline-fail-closed` (`f39852b`)
7. `fix/export-pricing-headline-fail-closed` (`439b73b`)

Caveat: branch 7 was built off baseline and also edits `export_package.py`, which
Stage 1 branch 3 (`fix/export-quality-artifacts`) also edits. Expect a possible
conflict in `_pricing_markdown` / surrounding code. Resolution rule: keep the
loop-safe collection + quality-artifact status from branch 3 AND the fail-closed
default (`get(..., False)`) from branch 7. Re-run `tests/test_export_package.py`
and `tests/test_export_quality_artifacts.py` after resolving.

## Stage 3 — Audit / MCP hardening (only if completed and reviewed)
8. `fix/audit-log-robustness` (`db77e0c`, off baseline `f692c04`) — crash-safe audit
   JSONL reader + recursive redaction; malformed logs degrade with structured
   warnings (KNOWN_ISSUES I3 FIXED). READY_FOR_CODEX_REVIEW.
   - Edits `app/services/export_package.py` (adds an `audit_log` payload) — **expect a
     conflict with the dossier/export branch (Stage 4 item 14) and any export-quality
     branch**; resolve by PRESERVING BOTH the `audit_log` payload and the dossier
     manifest / SKU trace exports.
9. `fix/mcp-url-allowlist` (`b6a51d7`, off baseline `f692c04`) — MCP endpoint trust
   boundary: untrusted external MCP hosts are blocked and never receive credentials;
   localhost/private allowed by default; `.api.aws` trusted; explicit allowlist /
   external opt-in supported (KNOWN_ISSUES I4 FIXED, DECISIONS D14). READY_FOR_CODEX_REVIEW.
   - Touches `app/core/config.py`, `app/api/routes.py`, `app/services/export_package.py`,
     `app/services/mcp_http.py`. **Expect conflicts with the audit branch (item 8) and
     the dossier/export branch (Stage 4 item 14)** — all add raw payloads in
     `export_package.py` and edit `routes.py`. Resolve by PRESERVING the `mcp_security`
     diagnostics/export payloads ALONGSIDE the `audit_log` payload and the dossier
     manifest / SKU trace exports.
Neither blocks the internal pilot; merge when ready.

## Stage 4 — SKU-backed pricing stack (stacked; merge bottom-up, after Codex review)
This is a dependency chain — review/merge in order, each onto the previous:
10. `feature/sku-backed-pricing-foundation` (`9b168d7`) — standalone SKU foundation; no live impact.
11. `feature/sku-pricing-local-cache-adapter` (`efe0849`, on `9b168d7`) — provenance-gated local-cache adapter; no live impact.
12. `feature/sku-pricing-source-truth-pilot` (`c301362`, on `efe0849`) — supplemental flag-gated pilot trace (legal/document RAG only).
13. `feature/sku-pricing-official-snapshot-builder` (`b92b98f`, on `c301362`) — offline official AWS Price List snapshot builder; raw-byte provenance (D11); splits rate authority from quantity confidence; EventBridge unsupported (I10). No live impact (flag-gated; builder/CLI run manually).
14. `feature/verifiable-dossier-sku-export-ux` (`91ad37d`, on `b92b98f`) — verifiable dossier manifest + SKU pilot trace export + verifier/diff scripts + read-only TrustPanel (DECISIONS D12). Additive; no live pricing change.

Notes:
- All five are standalone/flag-gated; with `ARCHWAY_ENABLE_SKU_PRICING_PILOT` off (default) there is no live pricing change even after merge.
- Do NOT merge the pilot (12) without its bases (10, 11); the official builder (13) without 10–12; or the dossier (14) without 10–13 — each imports the previous.
- The pilot must remain supplemental: it must not promote global `headline_safe`/`procurement_ready` (DECISIONS D10); the builder reinforces this by splitting `rate_authoritative` from `quantities_confirmed` (D11); the dossier keeps `pricing.sku_pilot` separate from `pricing.global` (D12).
- **Merge the pricing fail-closed branches BEFORE or ALONGSIDE the dossier (14):** the dossier REPORTS the legacy global `headline_safe` and does not enforce it. Without the fail-closed gates merged, the manifest could echo `pricing_headline_safe=true` for directional pricing (see `docs/dossier_integration_notes.md` + KNOWN_ISSUES).
- **Expect a possible conflict in `app/services/export_package.py`** with the export-quality artifacts branch (both edit `generate()`). Resolve by PRESERVING BOTH: keep the export-quality markdown/raw artifacts AND the dossier manifest + SKU trace exports (the dossier insert is an additive block before the zip step).
- UI/export now surface the SKU pilot trace + trust state (KNOWN_ISSUES I9 resolved for surfacing); product-level pricing replacement remains out of scope.

## Stage 5 — Any-usecase capability routing (merge AFTER the Discovery Planner pipeline, BEFORE final validation gates)
15. `feature/any-usecase-capability-router` (`445c6de`, off baseline `f692c04`) — deterministic `CapabilityRouter` (supported/directional/discovery_needed/unsupported_or_blocked) consuming the existing DiscoveryPlanner as an advisory, quarantined model prior (DECISIONS D15). Frontier prior OFF by default. READY_FOR_CODEX_REVIEW.

Notes:
- Sequence: merge after the Discovery Planner / synthesis pipeline exists (it does in baseline) and BEFORE final validation/readiness gates — the router's status + `safe_to_generate_*` flags should be available to those gates.
- **Conflict risks** in `app/services/discovery_planner.py`, `app/services/synthesis.py`, `app/services/use_case_profile.py`, and `app/core/config.py` (the discovery/profile pipeline is also touched by domain-pack branches).
- During merge, PRESERVE: (a) the **model-prior quarantine** (model influence limited to questions + generic fallback candidate; deterministic anchor in `_merge_plan`), and (b) the **pricing-driver leakage fix** (`discovery_plan.pricing_drivers` is deterministic-only and must not be re-opened to model output). Keep the flag default-off and the deterministic-known dominance gate intact.
- Additive metadata only (`profile.capability_decision`); no pricing/architecture/governance/diagram behavior change.

## Stage 6 — Diagram platform + quality (internalize compiler FIRST, then lane adapters; BEFORE final validation / golden export)
16. `chore/internalize-diagram-compiler` (`4368266`, off baseline `f692c04`) — vendors
    `archway_diagram_compiler` into `packages/archway_diagram_compiler/` (working-tree
    snapshot at external HEAD `c9a8031`; provenance in SOURCE.md; DECISIONS D17). Default
    runtime imports the internal package; `ARCHWAY_DIAGRAM_COMPILER_PATH` becomes an
    explicit debug override only. Migration-only; no compiler logic or thresholds changed.
    READY_FOR_CODEX_REVIEW.
17. `fix/healthcare-diagram-crossings` (`8d07ac0`, off baseline `f692c04`) — reusable
    `DomainLaneModel` framework + healthcare OR lane adapter; the production logical
    service-flow diagram passes the unchanged 8-crossing gate (14 → ≤8) without weakening
    QA (DECISIONS D16). Generic lane fallback unchanged. READY_FOR_CODEX_REVIEW.

Notes:
- **Order within Stage 6: merge the internalize-compiler branch (16) BEFORE the healthcare
  lane adapter (17)** — the lane adapter depends on compiler behavior (the
  `semantic_archway` lane machinery) that is now vendored internally; merging 16 first
  means every later diagram fix is validated against the in-repo compiler source, not an
  external path.
- Sequence overall: merge AFTER core discovery/pattern changes (Stage 5 + any domain-pack
  work, which also touch `pattern_catalog.py`) and BEFORE the final golden export
  validation / integration rehearsal — so the cleaner diagrams are what the golden export
  validates.
- **Conflict risk (16):** `app/services/diagram_compiler_adapter.py`, `app/core/config.py`,
  `.env.example`, `.gitignore` (config.py is also touched by the capability-router, SKU
  pilot, and MCP branches). Resolve by PRESERVING the internal default import +
  `compiler_source` reporting, the explicit-external-override-only semantics, the
  SOURCE.md provenance, and the unchanged threshold.
- **Conflict risk (17):** `app/services/pattern_catalog.py` (also edited by Stage 1 item 5
  `fix/typed-effectful-flow-detection` and the capability-router / domain-pack branches)
  and the new `app/services/lane_planner.py`. Resolve by PRESERVING the `DomainLaneModel`
  framework + healthcare adapter AND the healthcare governance detail-only routing.
- Do NOT loosen the compiler thresholds (`logical_edge_crossing_max` stays 8). The
  compiler is now vendored internally (D17); the external repo is no longer a runtime
  dependency and must not be reintroduced as one.
- No generated SVG/PNG/D2/export artifacts may be committed; `.tools/d2/d2` stays
  gitignored (KNOWN_ISSUES I15).

## Deferred — not in this RC2 stabilization line
- `experiment/domain-pack-interface` (`fe886af`) — DEFER until Codex review.
- `feature/domain-pack-phase2-pricing-drivers` (`20eea81`) — DEFER until Codex review.
- Frontend modularization (KNOWN_ISSUES I6) — DEFER post-stabilization.
- Bidirectional diagram sync (DECISIONS D8) — not near-term.

---

## Codex review checklist (per branch, before merge to master)
- [ ] Diff scope matches the branch's stated purpose; no unrelated files.
- [ ] No pricing numbers / families / rate-binding / source-truth math changed
      (unless that is the branch's explicit purpose).
- [ ] No safety gate relaxed: governance, headline safety, procurement/customer
      readiness, diagram QA remain owned by the deterministic pipeline.
- [ ] Fail-closed defaults preserved (no `get(flag, True)` reintroduced).
- [ ] Tests: the branch's focused tests pass; no new failures vs. baseline; the
      two known pre-existing failures (KNOWN_ISSUES I1/I2) are unchanged.
- [ ] Frontend build passes if any `frontend/` file changed; type changes additive.
- [ ] Domain-pack flag remains default OFF; flag-off behavior == baseline.
- [ ] Conflicts (esp. `export_package.py` in Stage 2) resolved per the rule above
      and re-tested.
- [ ] DECISIONS.md not contradicted; if it is, the decision is updated with rationale.
- [ ] Rollback command recorded (`git revert -m 1 <merge>`).
