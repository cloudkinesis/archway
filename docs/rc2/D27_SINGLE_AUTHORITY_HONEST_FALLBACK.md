# D27 — Single Classification Authority + Honest Fallback + One Fail-Closed Gate

**Status:** implemented on `feature/d27-single-authority-honest-fallback` (offline-verified; see §5b AS-BUILT). Live end-to-end proof pending Bedrock connectivity.
**Goal:** end the categorization treadmill *structurally* — not with one more keyword/guard/refiner, but by deleting the special-case generators and replacing them with four invariants and one universal gate. After D27, a never-coded use case can only do one of two **honest** things: be correctly classified by the LLM, or be flagged *unclassified / directional* — never confidently wrong.

This supersedes the per-intent guard approach (`_has_transactional_pricing_intent`, `867a8b3`) and the per-domain refiners (already removed). It does **not** change pricing math, SKU binding, compiler/verifier semantics, REQUIRED_ARTIFACTS, validation thresholds, or protected tags.

---

## 0. Why specs keep multiplying (the disease)

There are **two parallel classification authorities**:

1. **LLM / open-world** — `app/services/open_world_understanding.py`.
2. **Keyword categorizer + catalog-as-judge** —
   - `app/services/use_case_profile.py:77` `profile_use_case` → `_detect_domain:209`, `_rank_workload_families:269`. It even stamps `confidence="high"` (`use_case_profile.py:109`) on its guesses.
   - `app/services/pricing_driver_selector.py` `select_pricing_driver_family` — a hardcoded `if {families} & ...: return PricingDriverFamily.X` cascade.

Path 2 maps **infinite** open-world inputs onto a **fixed** catalog by keyword. For any input it wasn't coded for, it is wrong. Every prior spec added a special case *to path 2*. You cannot out-spec infinity → the treadmill is structural.

Two proven failures, **same disease**:

- **Food-delivery** (`867a8b3` era): LLM classified correctly ("dynamic pricing"), but path-2's family cascade re-squeezed it into `industrial_iot_streaming` → `1,036,800,000,000` monthly events. The plausibility finding fired at `warning` (`source_truth_pricing_compiler.py:836,842` → `cap_to_directional`), so it still shipped.
- **Reverse-logistics** (`sess_eca55d8c5a0f`): LLM call hit `EndpointConnectionError` (network down), returned no content → `accepted=False`, `fallback_used=True` (`open_world_understanding.py:252,270`). `synthesis.py:61` `profile = open_world.profile or profile_use_case(raw_use_case)` **silently** handed authority to path 2 → `financial_fraud_detection` → poisoned research/architecture/pricing/diagrams/client-pack. The failure was mislabeled `structured_output_invalid` ("did not validate against the lane schema") when it was a transport failure.

The architectural hole that makes honest failure impossible: `golden_convergence_orchestrator.py` consumes `accepted` / `fallback_used` / open-world authority **nowhere**. Readiness has no idea whether the classification came from the LLM or from a keyword guess.

---

## 1. The four invariants (the whole fix)

### INV-1 — Single authority
The open-world LLM understanding is the **only** source that assigns `domain`, `workload_families`, pricing-family, and architecture-pattern that **drive a deliverable**. The catalog is a *reference that must be positively justified*, never a judge.

### INV-2 — No silent fallback; honest "unclassified"
When the LLM authority is unavailable for **any** reason (network, schema-invalid, timeout, disabled, budget), the package enters an explicit `understanding_unavailable` state. It is **capped hard** and the **true** reason is surfaced. `profile_use_case` may **never** silently drive a full deliverable. Exactly one flag — `understanding_authoritative: bool` — is decided in one place and read everywhere downstream.

### INV-3 — Catalog applies only when positively justified
A catalog family (pricing driver, architecture pattern) is selected **only** when the LLM classification positively aligns with that family's declared signature. Otherwise → `GENERIC_DIRECTIONAL`, fail-closed (the `867a8b3` compiler change already makes that landing honest: `bind_quantities=False`, `allow_live_authority=False`). **Delete every per-intent guard.**

### INV-4 — One universal, domain-blind, fail-closed gate
Plausibility + internal-consistency (the D25 quantity graph, `source_truth_pricing_compiler.py:810` `_quantity_plausibility_findings`) caps readiness **unconditionally**. Physically-impossible quantities are `critical` (`cap_to_internal_only`), never `warning`. The convergence orchestrator consumes INV-2 and INV-4.

---

## 2. Change set (file:line anchored)

### 2.1 INV-2 — the silent-fallback site
**`app/services/synthesis.py:61`**
```python
profile = open_world.profile or profile_use_case(raw_use_case)   # ← the disease
```
Replace the `or` with an explicit branch:
- If `open_world.profile` present → use it; `understanding_authoritative = True`.
- Else (open-world enabled but unavailable) → build a **non-authoritative** profile (may still use `profile_use_case` for *interview scaffolding only*), set `understanding_authoritative = False`, and record the true reason from `open_world.trace.live_call` (e.g. `connectivity` vs `structured_output_invalid`).
- Carry `understanding_authoritative` and `understanding_unavailable_reason` onto the profile metadata so every downstream stage can read it (mirrors `synthesis.py:62-64` which already attaches the trace when `not open_world.profile`).

### 2.2 INV-2 — decide authority in ONE place
**`app/services/open_world_understanding.py`** (trace fields already exist at `:136-138` `enabled` / `accepted` / `fallback_used`).
Add a single derived property `understanding_authoritative = enabled and accepted and not fallback_used`. This is the only definition; nothing else recomputes it.

### 2.3 INV-2 — honest error taxonomy
**`open_world_understanding.py`** live-call assembly (the block that today sets `error_type="structured_output_invalid"` while `warnings` contain `EndpointConnectionError`). Classify transport failures (`EndpointConnectionError`, timeout, throttling) as `error_type="provider_unavailable"`, distinct from genuine `structured_output_invalid`. Retry transport failures with backoff; do **not** relabel them as schema failures. (This is what sent the diagnosis sideways.)

### 2.4 INV-2 + INV-4 — convergence consumes authority + plausibility
**`app/services/convergence/golden_convergence_orchestrator.py`** (today references neither).
- If `understanding_authoritative` is False → readiness is capped at `internal_only` (or a new `understanding_unavailable` cap), reason surfaced verbatim. A non-authoritative classification can **never** reach `workshop_ready`/`procurement_ready`.
- If any plausibility/consistency finding is `critical` → unconditional `cap_to_internal_only` (already the mapping at `source_truth_pricing_compiler.py:226`; INV-4 ensures impossible quantities are *graded* critical, see 2.6).

### 2.5 INV-3 — invert the family layer (delete guards)
**`app/services/pricing_driver_selector.py` `select_pricing_driver_family`.**
- Reframe each branch from "keyword/family membership matches → return catalog family" to "**does the LLM classification positively justify this family's signature?**". A family is returned only on positive justification from the authoritative understanding.
- Default (no positive justification) → `GENERIC_DIRECTIONAL`.
- **Delete** `_has_transactional_pricing_intent` and the `and not _has_transactional_pricing_intent(...)` hack on the industrial-IoT branch — unnecessary once the default is generic-unless-justified.

### 2.6 INV-4 — grade impossible quantities as critical
**`source_truth_pricing_compiler.py:810` `_quantity_plausibility_findings`.**
- The events/storage ceilings that today emit `warning` (`:836,:842`) must emit `critical` when the quantity is *physically impossible* (e.g. monthly events ≫ asset_count × cadence × period, storage ≫ per-asset ceiling × retention). Directional uncertainty stays `warning`; **impossibility is critical**. This closes the trillion-events-ships-as-warning path.

### 2.7 INV-1 — demote the keyword categorizer
**`app/services/use_case_profile.py:77` `profile_use_case`.**
- Keep it for **interview scaffolding / discovery only** when understanding is unavailable. It must never set `understanding_authoritative` and must not stamp `confidence="high"` (`:109`) on a fallback classification that surfaces to deliverables.

---

## 3. The guard that ends the treadmill

**`app/services/d25_convergence_eval.py`** (already exists, offline, domain-blind, deterministic). Add invariant assertions so the *class* is caught without live runs:

- **INV-2:** a scenario with `understanding_authoritative=False` must yield readiness ≤ `internal_only` and an honest reason — never a full classified deliverable.
- **INV-3:** a scenario whose authoritative classification doesn't positively justify any catalog family must land on `GENERIC_DIRECTIONAL` (not a wrong catalog family).
- **INV-4:** any scenario producing a physically-impossible quantity must yield a `critical` finding and `cap_to_internal_only` — asserted, not advisory.
- **Anti-treadmill meta-assertion:** grep-style test that fails CI if a new per-intent/per-domain guard or `_refine_<X>`/`_has_<X>_intent` function is added to the selector or profiler. New special cases become a *test failure*, by design.

---

## 4. What this explicitly does NOT change

Pricing math, SKU binding, `RATE_FILTER_RULES`/`UNIT_COMPATIBILITY_RULES`, compiler/verifier semantics, REQUIRED_ARTIFACTS, validation thresholds, governance/manifest, protected tags (`archway-v2-rc2-golden-baseline`, `archway-v2-post-rc2-claude-showcase`, D21 lane tags). D27 changes *who is allowed to classify* and *what happens when classification is unavailable or implausible* — nothing about how confirmed numbers are computed or bound.

---

## 5b. AS-BUILT (branch `feature/d27-single-authority-honest-fallback`)

Implemented and verified offline (full suite 750 passed). Key decisions/deviations from
the original draft, recorded so this spec stays the source of truth:

- **INV-2 taxonomy** — `LLMResult.transport_error` set in `bedrock_provider.py` by
  **exception class name** (`"connection"`/`"timeout"` substrings), never the message and
  never `ClientError` (so a wrong-model-id ValidationException stays a real error, not a
  masked "retry when online"). `live_bedrock_harness.py:222` reads the typed flag →
  `provider_unavailable` vs `structured_output_invalid`.
- **INV-2 authority** — `understanding_authoritative` defined once on
  `OpenWorldUnderstandingTrace` (`= enabled and accepted and not fallback_used`), mirrored
  onto the profile, serialized through `profile_to_metadata`. `synthesis.py` replaces the
  silent `or` with an explicit branch reading the trace flag.
- **Attempted-vs-disabled split (important).** The convergence cap fires only when the
  open-world lane was **enabled and attempted but failed** (non-None
  `understanding_unavailable_reason`). Disabled-by-config deterministic offline mode leaves
  the reason `None` and is governed by the existing readiness gates — otherwise the entire
  offline golden baseline would collapse to `internal_only`. This is the surgical scope:
  it fixes the live network-drop case without nuking offline.
- **Selector is NOT gated on `understanding_authoritative`.** The authority gate lives at
  the convergence layer (where it belongs); gating the selector would force every
  deterministic run to GENERIC and break goldens + the "supported workload reaches its
  family" guard. The food-delivery fix comes entirely from carrying the LLM families
  faithfully in `_families_from_understanding` (proven: food-delivery → GENERIC, healthcare
  → specialized).
- **INV-4** — `telemetry_monthly`/`direct_event_monthly` already exist at the call site
  (compiler ~:543-544); threaded as a single boolean `events_from_confirmed_input`
  (default True = safe). No magic ceiling.
- **Anti-treadmill test is a RATCHET.** Two legacy `_has_*_intent` guards on the
  deterministic path predate D27; they are frozen in a baseline that may only shrink. New
  guards fail CI. Removing the legacy pair is a separate follow-up (offline golden churn).
- **Deferred (not needed for the fixes):** `_detect_domain` scored-ranking tiebreak and
  dropping `confidence="high"` on fallback — deterministic-path polish with golden-churn
  risk; left for a focused follow-up branch.

### Verification boundary (honest)
- **Verified offline now:** INV-2 honest fallback + taxonomy, INV-4 gate, INV-3 family
  routing (food-delivery → GENERIC; specialized families reachable), the ratchet, full
  suite 750 green.
- **Pending live (needs Bedrock connectivity):** that a real network-up food-delivery run
  emits `workload_family_candidates=[open_world_other]` and lands on GENERIC end-to-end;
  that a real network-drop run produces the honest `understanding.unavailable` cap in a
  live session. The code paths are unit-proven; the live end-to-end proof waits for the
  network. Also fix `.env` `ARCHWAY_BEDROCK_MODEL_ID` → `us.amazon.nova-pro-v1:0` before
  the live run (separate latent landmine, not changed on this branch).

## 5. Acceptance (how you know the treadmill is dead)

1. Network down → reverse-logistics run produces an **honest** "understanding unavailable (connectivity) — retry when online," capped `internal_only`, **not** a polished `financial_fraud_detection` package.
2. Food-delivery → either correctly classified (LLM authoritative) or `GENERIC_DIRECTIONAL`; the trillion-events quantity is graded `critical` and cannot ship.
3. A brand-new never-coded use case with the network up → correctly classified by the LLM, catalog only applied where positively justified.
4. Adding a new keyword guard to the selector/profiler **fails CI** (§3 meta-assertion).
5. No new `_refine_*` / `_has_*_intent` functions exist anywhere.
