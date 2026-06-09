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

## D10. SKU pricing pilot is SUPPLEMENTAL and FLAG-GATED
- The SKU-backed pricing pilot (`feature/sku-pricing-source-truth-pilot`) attaches
  a supplemental `sku_pricing_pilot` trace to pricing metadata. It must NOT replace
  the heuristic/source-truth totals (`low/expected/high`) and must NOT promote the
  global `headline_safe` / `procurement_ready`. Pilot readiness is exposed only via
  the separate `sku_pilot_procurement_ready`.
- Gated by `ARCHWAY_ENABLE_SKU_PRICING_PILOT` (default false). With the flag off,
  pricing behavior is byte/behavior-equivalent to baseline.
- Snapshot authority: a `static_fixture` snapshot is NEVER authoritative. Only a
  `local_cache` (or `price_list_api` / `mcp`) snapshot with valid upstream
  provenance (upstream source + source hash + region + rates with SKU/price
  dimension) may unlock pilot-scoped procurement-ready line items — and even then
  only when every required line binds exactly with a confirmed quantity.
- Missing/ambiguous/unit-mismatch binding fails closed; non-authoritative or
  unconfigured snapshots yield `skipped`/`failed_closed`, never readiness.

## D11. Official snapshot builder must hash RAW official offer bytes
- The official AWS Price List snapshot builder
  (`feature/sku-pricing-official-snapshot-builder` @ `b92b98f`) must compute
  `source_hash` (and per-file `source_file_hashes`) over the **raw official
  offer-file bytes**, NOT over a hand-reduced intermediate. Authority comes from
  the official source, not from a transformed file — otherwise `local_cache`
  authority is provenance theater.
- The builder ingests operator-provided official offer files from local disk
  (offline; no runtime network, no AWS credentials), maps them deterministically
  to Archway dimension keys via EXACT usagetype matching (region-prefix aware), and
  fails closed on ambiguity / unit mismatch / region mismatch / unclear tier /
  free-tier-only / non-USD. It splits rate authority (`rate_authoritative`) from
  quantity confidence (`quantities_confirmed`); assumed quantities can never reach
  `sku_pilot_procurement_ready` (reinforces D10).
- Validated 2026-06 against the real us-east-1 offer files for the supported
  services: real offer codes differ from friendly names (SQS = `AWSQueueService`,
  EventBridge = `AWSEvents`); the builder maps 9 of 10 dimensions, with EventBridge
  intentionally unsupported (see KNOWN_ISSUES I10).

## D12. Verifiable solution dossier is the artifact truth spine
- `dossier_manifest.json` (branch `feature/verifiable-dossier-sku-export-ux` @ `91ad37d`)
  is the CANONICAL export trust spine. Every export artifact, the SKU pilot trace,
  pricing provenance, readiness gates, and the UI trust state must map back to the
  manifest — no new artifact or UI panel is allowed that does not.
- The manifest records a deterministic, content-hashed artifact inventory (stable
  canonicalization: sorted keys, UTF-8, normalized newlines, SHA-256) and excludes
  itself from its own inventory (no self-recursion).
- The TrustPanel RENDERS trust metadata only; it must not invent trust state.
  Verification must NOT be inferred from manifest presence alone — "verified" is shown
  only when an actual `verify_solution_dossier.py` result is supplied.
- SKU pilot readiness (`pricing.sku_pilot`) stays SEPARATE from global readiness
  (`pricing.global`); the dossier never promotes global `headline_safe`/
  `procurement_ready`, and assumed quantities can never read procurement-ready
  (reinforces D10/D11).
- Authoritative SKU rates must carry `upstream_source` + `version_hash`
  (`provenance_status: complete`); when missing, `provenance_status: partial` and the
  verifier warns (fails under `--strict`).
- The dossier is a faithful REPORTER of pricing readiness, not its enforcer:
  enforcement lives in the pricing fail-closed branches, which are a prerequisite for
  a trustworthy `pricing_headline_safe` (see MERGE_PLAN + KNOWN_ISSUES).
