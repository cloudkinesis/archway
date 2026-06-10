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

## D13. Audit logs are non-blocking diagnostic evidence
- Audit logs (`audit.jsonl`) are diagnostic EVIDENCE, not a control-plane gate.
- A corrupt / partially-written / unreadable audit log must NEVER block export,
  diagnostics, session hydration, dossier generation, or readiness — the flow always
  produces an honest package (fixed by `fix/audit-log-robustness` @ `db77e0c`).
- Audit degradation is WARNING-LEVEL: malformed/non-object lines are skipped with
  structured warnings and a `degraded`/`unreadable` status surfaced in export, but it
  is never a blocker. (This aligns with the product rule: always produce an honest
  package; never fake success; never leave the user empty-handed.)
- Audit data is recursively REDACTED before it is logged, persisted, read, or
  exported; secrets/tokens/keys never leak through audit evidence, and innocent keys
  are preserved (allowlist) to avoid over-redaction.
- Exception: a FUTURE explicit compliance mode could require audit completeness and
  promote audit degradation to a blocker. No such mode exists today; do NOT invent one
  in the hardening branch.

## D14. MCP endpoints are privileged trust boundaries
- MCP endpoints are privileged integration points (fixed by `fix/mcp-url-allowlist`
  @ `b6a51d7`). Credentials (bearer/API tokens) must NEVER be sent to an untrusted or
  arbitrary external MCP host.
- localhost and private-network endpoints are trusted by default
  (`ARCHWAY_MCP_ALLOW_LOCALHOST` / `ARCHWAY_MCP_ALLOW_PRIVATE_NETWORK`).
- `.api.aws` (AWS-managed MCP) is trusted by default to preserve existing AWS-managed
  MCP behavior — the one built-in external suffix allowlist.
- Any other external MCP host is BLOCKED unless explicitly allowlisted
  (`ARCHWAY_MCP_ALLOWED_HOSTS`, exact host match) or external opt-in is enabled
  (`ARCHWAY_MCP_ALLOW_EXTERNAL=true`). Unsupported schemes, malformed URLs, and
  URLs with embedded credentials are blocked.
- When an endpoint is untrusted the client fails closed (no token, no call) and the
  existing fallback (official web / heuristic / snapshot) continues — MCP safety must
  never change pricing/research ranking, only whether the unsafe call is attempted.
- Diagnostics/export surface a token-safe `mcp_security` status with a sanitized URL
  (scheme+host+port+path only); tokens and query strings are never logged or exported.

## D15. Any-usecase handling contract
Implemented by `feature/any-usecase-capability-router` @ `445c6de`.
- Archway must classify EVERY normal use case into exactly one of:
  `supported` / `directional` / `discovery_needed` / `unsupported_or_blocked`.
- The frontier/model prior is ADVISORY ONLY.
- The EXISTING `DiscoveryPlanner` (via `ModelRouter`) is the model-prior layer — do NOT
  create a parallel prior subsystem and do NOT add a new external model client/egress.
- The deterministic `CapabilityRouter` owns the FINAL status; the model prior can never
  set it.
- The model prior CANNOT drive pricing quantities, architecture service selection,
  readiness, governance, citations, or diagrams. Its influence is quarantined to
  interview questions + a generic fallback-family CANDIDATE only (validated against an
  allowlist). Model-provided pricing-driver names no longer flow into pricing selection.
- Deterministic-known classifications DOMINATE: when deterministic is high-confidence
  with a known family + domain, the model prior is not consulted.
- Unsafe/abusive use cases (phishing, credential/data theft, malware/ransomware/botnet,
  bypassing security, evading detection, DDoS, etc.) must be `unsupported_or_blocked`
  with `expected_artifact_level=unsupported_explanation` and
  `safe_to_generate_{architecture,pricing,diagrams}=false`. Defensive security products
  are NOT blocked.
- Sensitive unknown inputs (secret/credential VALUES, or explicit PHI/PII markers like
  PHI/HIPAA/patient record/MRN/diagnosis) SKIP the model prior and continue with the
  deterministic fallback — the use case is not blocked.
- The frontier prior is OFF by default (`ARCHWAY_ENABLE_FRONTIER_DOMAIN_PRIOR=false`,
  per-session cap `=1`); default behavior is fully deterministic and reproducible.

## D16. Diagram quality uses domain-aware lane adapters without loosening compiler gates
Implemented by `fix/healthcare-diagram-crossings` @ `8d07ac0`.
- The external diagram compiler's crossing/readability QA gates remain AUTHORITATIVE
  (`logical_edge_crossing_max = 8`, etc.). Archway improves the semantic PLACEMENT inputs
  it feeds the compiler; it must NOT weaken QA thresholds or suppress warnings to pass
  (reinforces D6).
- `DomainLaneModel` (`app/services/lane_planner.py`) is the adapter point for
  domain-specific lane placement: it maps a domain's components onto the
  compiler-recognized semantic lanes in the correct flow order, while preserving friendly
  semantic-group names for the dossier/metadata. Every lane MUST map to a recognized
  compiler lane label — no one-off, per-use-case string hacks.
- Healthcare OR is the FIRST adapter. Unknown / non-specialized domains keep the GENERIC
  lane fallback unchanged (behavior byte-identical to baseline).
- Dense governance / audit / observability fan-out may be moved to detail-only / sidecar
  views ONLY when the flows are PRESERVED and metadata records the detail-only route
  (`logical_detail_only`) — never silently dropped.
- A diagram that cannot pass must degrade HONESTLY (report the QA finding / missing view
  with a reason), not hide warnings.
