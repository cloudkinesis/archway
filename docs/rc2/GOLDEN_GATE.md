# RC2 Golden Gate

The acceptance bar before Archway may be called "Golden" (release-grade for the
intended honest-directional scope). Every item must pass or be explicitly
documented as an accepted known exception. This gate is verification, not a
promise of procurement-grade pricing (see DECISIONS D3).

---

## Build & test
- [ ] **Full backend suite** passes, OR every failure is documented in
      KNOWN_ISSUES with a status and a "does not block" justification. The two
      pre-existing failures (citation coverage I1, utility metric I2) must be
      triaged — fixed or formally quarantined — not silently tolerated.
- [ ] **Frontend build** (`cd frontend && npm run build`, i.e. `tsc -b && vite build`)
      passes with no type errors.

## Functional baselines
- [ ] **RC2 discovery baseline matrix** runs for the curated scenarios and
      classification matches expectations (no misrouting).
- [ ] **Golden export validation** completes for **legal**, **healthcare**, and
      **telecom**: pipeline runs end-to-end and an export zip is produced.

## Trust & honesty invariants
- [ ] **No cross-domain leakage** — healthcare vocabulary/pricing/views do not
      appear in telecom/media/generic/legal outputs, and vice versa
      (anti-drift suite green).
- [ ] **No raw `ev_*` evidence ids in the default UI** — evidence is shown with
      readable source labels; raw ids only in debug/appendix surfaces.
- [ ] **Pricing headline-safe only when proven** — missing/unknown safety flag
      renders as withheld/directional, never as a confident headline, on every
      surface (view model, export). Fail-closed (DECISIONS D2).
- [ ] **Export package quality artifacts present or explicit** — convergence,
      build status, customer readiness, quality findings, repair plan are either
      present or carry an explicit status (present/skipped/deferred/
      not_applicable/failed). No vague event-loop warnings; no repeated
      "missing optional artifact" noise.
- [ ] **Diagrams rendered or degraded WITH reasons** — every requested/semantic
      view is rendered through the D2 compiler or reported as missing/degraded
      with a concrete reason. No silent drops.

## State & governance integrity
- [ ] **No stale architecture revisions** — re-generating architecture appends a
      new active revision; diagrams compile from the active (newest) revision,
      never stale specs.
- [ ] **No unsafe effectful flows without governance** — create/update/delete/
      writeback/external-write/block/network-change flows receive typed
      governance controls (typed-metadata detection with string fallback), or are
      downgraded to recommendation/queue-for-review. No silent pass.

## Posture
- [ ] **Stabilization integration branch reviewed by Codex or a human reviewer
      before merge to master.** The Golden Gate is not only runtime behavior; a
      merge-review checkpoint is required before master is declared Golden.
- [ ] Domain-pack registry flag default OFF; flag-off behavior == baseline.
- [ ] No endpoint exposed beyond local; internal pilot uses sanitized use cases
      only (DECISIONS D9).
- [ ] DECISIONS.md and KNOWN_ISSUES.md are current and not contradicted by the
      shipped state.

---

## RC2 rehearsal result — 2026-06-10 (`integration/rc2-golden-rehearsal @ ee534db`)

Gate measured on the rehearsal branch (15 `--no-ff` merges of all reviewed branches
off `f692c04`; see BRANCH_LEDGER + MERGE_PLAN "RC2 golden rehearsal — COMPLETED"):

| Gate item | Result |
|---|---|
| Full backend suite | **363 passed, 2 failed** — only the documented known failures **I1** (e2e citation coverage) + **I2** (`outage_reduction_target_percent`); zero new failures. I1/I2 remain OPEN, accepted as known exceptions for the rehearsal (not yet triaged-fixed/quarantined — the checklist item above is therefore not fully closed). |
| Frontend build | **PASS** (`tsc -b && vite build`). |
| RC2 validation harness | focused **READY**; stabilization+frontend **READY** (62 passed); golden+frontend **READY_WITH_KNOWN_ISSUES** (363 passed / 2 known / 0 new) — anti-laundering headline behaving as designed. |
| Golden export validation | **legal / healthcare / telecom all PASS** end-to-end (zero blockers; export zips produced). WARN statuses were honest by-design signals only: info-level enrichment diagnostics and directional, not-procurement-ready pricing (D3). |
| Dossier verifier | **VALID on all three packages** (89/85/75 artifacts checked; 0 mismatched, 0 missing; SKU pilot honestly recorded absent — flag off). |
| Healthcare diagram crossing gate | **PASS** — 0 `too_many_edge_crossings` in exported QA; threshold unchanged at 8; clinical semantic groups present; no IoT leakage in the healthcare architecture (IoT strings only in the cross-scenario `golden_regression_summary.json` baseline). |
| Pricing fail-closed | **PRESERVED** — `headline_safe=False` / `procurement_ready=False` in manifests; `get(..., False)` defaults intact through every conflict resolution. |
| Audit / MCP honesty payloads | **PRESERVED** — `audit_log` + `mcp_security` both exported. |
| Docs currency | Control plane current through `docs/rc2-decision-log` (D17, I15, Stage 6 ordering) merged into the rehearsal. |
| No secrets / artifacts | No tokens/secrets in exports; no generated artifacts committed. |

Remaining for full Golden: Codex/human review of `integration/rc2-golden-rehearsal`
(Posture checkpoint above), and the I1/I2 triage decision (fix or formally quarantine).

**Follow-up (post-rehearsal):** BOTH previous known full-suite failures now have fix
branches:
- **I1** → `fix/utility-grid-e2e-citation-determinism @ 6081c76` (test-only: pins
  evidence sources off for a deterministic offline run; asserts the anti-RAG
  classification invariant directly; product behavior was not wrong).
- **I2** → `fix/utility-metric-structuring @ 1138849` (profile metric alias restored;
  structured-extractor key unchanged).

Once both are merged into an `integration/rc2-golden-rehearsal-v2` candidate (alongside
the rehearsal stack + hygiene branch), **the full suite is expected to go GREEN for the
first time**, which would close the "Full backend suite" checklist item above. The
`ee534db` rehearsal result above is UNCHANGED — it predates these fixes and is NOT
retroactively green. Remaining for full Golden after that: the Codex/human review
checkpoint (Posture).
