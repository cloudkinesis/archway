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
