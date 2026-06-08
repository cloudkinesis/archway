# RC2 Decisions Log

Settled decisions for Archway RC2. These are intended to stop re-litigating
questions that have already been investigated and resolved. If a decision needs
to change, update this file with the new rationale and date — do not silently
contradict it in a branch.

Baseline: `master` @ `f692c04`.

---

## D1. The "broken regex pair" was a FALSE POSITIVE — do not chase it
- A round-1 review claimed `app/services/use_case_profile.py` had a broken
  double-backslash (`\\d`) regex at lines ~408-409.
- Verified against the actual bytes on baseline: those lines are not regex
  patterns, the real metric regexes live in `app/services/metric_extractor.py`
  and use correct single-backslash `\d`/`\s` with multiple fallbacks, and both
  extractors capture `refresh_cadence_minutes` / `scheduled_surgeries_per_day`.
- Root cause of the false report: a display/escaping artifact that propagated
  into review docs and a second tool's report.
- **Decision:** there is no regex bug. Do not "fix" it; do not re-flag it.

## D2. Pricing headline safety must FAIL CLOSED
- A missing `pricing_can_be_displayed_as_headline` flag must mean "not
  headline-safe." Headline pricing is shown only when explicitly proven safe.
- Applies to every presentation/export surface.
- Status: presentation (`ResearchViewModel`) already fail-closed on baseline;
  `PricingSanityReview` default hardened on `fix/pricing-headline-fail-closed`;
  export markdown hardened on `fix/export-pricing-headline-fail-closed`.

## D3. Directional pricing is acceptable; procurement-ready is NOT the default
- Directional / assumption-backed / heuristic pricing may be shown with caveats.
- Procurement-ready is a higher bar requiring confirmed drivers, usage
  dimensions, and SKU/rate binding. It is not expected by default and must never
  be asserted by default. No branch may make a scenario procurement-ready as a
  side effect.

## D4. The Discovery Planner is ADVISORY only
- It proposes domain candidates, drivers, and next-best interview questions.
- It does not own architecture validation, pricing safety, governance
  enforcement, diagram planning, procurement readiness, or customer-ready status.
- On low confidence or conflict with deterministic classification, it must mark
  ambiguity and ask a clarification, not silently pick a family.

## D5. The domain-pack registry is FEATURE-FLAGGED and NOT a full migration yet
- Gated behind `ARCHWAY_USE_DOMAIN_PACK_REGISTRY` (default OFF).
- Phase 1 = read-only/delegating resolution + advisory diagnostics.
- Phase 2A = advisory pricing-driver metadata (delegating; parity-preserving).
- With the flag off, behavior is exactly baseline. With it on, only additive
  diagnostics appear. Logic has NOT been moved out of the core services yet.

## D6. Diagrams must render through the existing D2 compiler
- All diagram output goes through `DiagramCompilerAdapter` to the external D2
  compiler. No internal shortcut renderer is permitted.

## D7. The LLM may propose; the deterministic pipeline owns safety
- An LLM (when configured) may propose discovery questions / semantic review.
- All safety-bearing decisions — pricing headline safety, governance
  enforcement, procurement/customer readiness, diagram QA — remain owned by the
  deterministic pipeline and core gates, never by model output.

## D8. Bidirectional diagram sync is NOT near-term
- Editing D2 in the UI and propagating back to architecture specs inverts the
  one-way spec -> compiler -> diagram flow and risks the determinism guarantee.
- Treat as a future research spike, not an RC2/near-term item.

## D9. Internal pilot requires SANITIZED use cases only
- Until auth and broader hardening exist, the internal pilot must use sanitized,
  non-sensitive use cases. No real customer PII/PHI/secrets in pilot sessions.
- The app remains local-first with no endpoint auth; it must never be exposed on
  a public/`0.0.0.0` interface without an auth layer.
