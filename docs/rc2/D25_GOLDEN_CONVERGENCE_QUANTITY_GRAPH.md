# Spec — `feature/d25-golden-convergence` (the golden-state fix)

**Status:** SPEC — review candidate. No code yet.
**Date:** 2026-06-17
**Branch base:** `feature/d25-open-world-convergence-quality-gates` (negation/profile-authority gate already landed; this spec is the next slice on top).
**Goal:** make any legitimate use case export a **golden** package — *complete, honest, internally consistent, and with plausible numbers*. Golden does **not** mean procurement-grade pricing or perfect architecture; it means **nothing in the package contradicts anything else and no number is absurd.**

> **Anti-hallucination rule.** Every defect below is **PROVEN** — reproduced by running the actual code on the real failing package (`sess_e5b32ba58635`, railway bridge/tunnel monitoring). Code locations are file:line, verified 2026-06-17. Every fix is **domain-blind** by construction (semantic types, not per-domain formulas) — the `archway-review-lens` rule applies.

---

## 1. Evidence — what the real exported package actually contained

Use case: *"monitor 1,850 bridges/tunnels, vibration sensors every 5s, 1.5 KB/event, acoustic clips, quarterly drone images, retain 18 months / 10 years."* The classification was **correct** (industrial IoT streaming ML — the negation/authority fix works). But the package was **not golden**, for reasons code proves:

### Defect A — Absurd derived quantities (PROVEN by reproduction)
Running `_generic_quantity_context` (`source_truth_pricing_compiler.py:318`) on the package's own canonical facts reproduces the client-pack numbers exactly:
```
generic monthly_events    : 21,578,400,000      (client pack showed this)
generic monthly_inferences: 19,180,800,000
generic storage_gb_month  : 40,459,500,000 GB-month  ( = 40.5 EXABYTES )

real telemetry base (1850 × 86400/5 × 30) : 959,040,000
→ monthly_events is 22.5× the real event stream
→ storage is 40.5 exabytes for a railway monitoring system
```
**The source-truth line items had the CORRECT number** (`raw/pricing.json`: *"959,040,000 monthly events"*). So two pricing computations exist and **disagree by 22.5×** — a convergence failure, and the client pack shows the wrong one.

**Root cause (PROVEN in code):** the quantity graph composes **semantically incompatible** quantities because facts are captured *untyped* (`explicit_quantity_bridges_1=1850`, `explicit_quantity_seconds_2=5`, `explicit_quantity_images_per_bridge_10=20` — raw noun+number, no type):
- `source_truth_pricing_compiler.py:358`: `monthly_images = (monthly_base) × image_per_item` — multiplies the **959M event stream** by 20 (images-per-bridge) → **19.18 B images/month**. Real drone images ≈ 1,850 × 20 ÷ 3 months ≈ 12,333/month. Off by ~1.5 million×. `monthly_inferences` then = `monthly_images` → 19.18 B inferences.
- `monthly_events = monthly_direct + monthly_base + monthly_base×per_item + hourly×720` — **sums distinct event types** as if they were one stream → the 22.5× inflation.
- `storage_gb_month = monthly_images × mb_per_image / 1024 × retention_months` — compounds the already-wrong image count with payload and retention → 40.5 exabytes.

### Defect B — One storage formula applied to every storage service (PROVEN in code)
`source_truth_pricing_compiler.py:295`: every storage-ish service reads the **single** `generic["storage_gb_month"]`. The package showed **S3 and DynamoDB with the identical `40,459,500,000 GB-month`** — DynamoDB is not an image store; the image-retention formula has no business there.

### Defect C — Client prose dumps raw scaffolding (PROVEN in artifact + code)
`client_pack/02-solution-brief.md` and `03-architecture-summary.md` contain the verbatim user input *"Not legal, not document search, not RAG, not chatbot, not field-service dispatch…"* and full *"Synthesis interview note: … Answer: …"* transcripts. Source: `synthesis.py:283` appends `"\n\nSynthesis interview note: {prompt} Answer: {text}"` onto `refined_problem_statement`, which `client_pack._solution_brief` (`client_pack.py:234`) renders verbatim into the executive view.

### What is already fixed (do not re-touch)
Negation/profile-authority (`domain=legal` gone), `generic_not_estimated` honesty (no fake headline range), `live_agent_calls.json` populated, reviewer↔deterministic reconciliation. Those hold; this spec builds on them.

---

## 2. Definition of golden (the bar this spec must hit)

For **any** legitimate use case, the exported package must satisfy **all**:
1. **Plausible quantities** — no derived quantity is physically absurd (no exabytes of storage for 1,850 assets; no 19 B drone images).
2. **Internal consistency** — the generic-derivation quantities reconcile with the source-truth line items (no 22.5× divergence); selected ∩ excluded = ∅; architecture has no excluded-family service; prose carries no excluded vocabulary.
3. **Type-correct composition** — events, images, inferences, and storage are each computed from the *right* driver (asset count × cadence; asset count × per-asset multiplier; data-class size × retention), never by multiplying incompatible quantities.
4. **Per-service correctness** — no two services share an identical misapplied formula; storage is computed per data class, not one global number.
5. **Executive-readable prose** — no raw "not X" negation lists, no verbatim interview transcripts in `client_pack`; Q&A is summarized.
6. **Honest where unbound** — still `not_estimated`/directional when SKU/rate binding is missing — but with *plausible* quantities and clear missing bindings.
7. **No dead-end, verifier VALID, linter 0, no machine-token leakage.**

---

## 3. The fixes

### 3.1 Typed quantity graph → (build — the keystone, domain-blind)
Replace untyped fact bucketing with **semantic typing**. Each extracted quantity fact is classified into a closed, **domain-blind** type set:
```
asset_count          (1850 bridges)               — the multiplier base
cadence_seconds      (every 5s)                    — rate, NOT a volume
payload_bytes        (1.5 KB/event, 18 MB/image)   — size, per data class
per_asset_multiplier (20 images / bridge / period) — a SEPARATE event/data stream
period               (per day / quarter / month)   — normalizes a multiplier
retention_duration   (90 days / 18 mo / 10 yr)     — duration, per data class
```
Classification is by **unit/shape**, not domain noun (`*_per_<noun>` is a per-item multiplier; `<n> seconds` is a cadence; `<n> KB|MB` is a payload; `<n> months|years` is retention). The type set names **no domain**.

Then compose with **type-correct arithmetic**, one stream per data class:
```
telemetry_events/month   = asset_count × (seconds_per_month / cadence_seconds)        # NOT summed with multipliers
per_asset_stream/month   = asset_count × per_asset_multiplier / period_in_months       # e.g. drone images
inferences/month         = the actual scoring driver (events or windows), NOT images×events
storage_gb_month[class]  = Σ_class( item_count[class] × payload_bytes[class] × retention_months[class] ) / 1024^2
```
**Invariant:** the graph never multiplies a *volume* by another *volume*, and never sums two different *streams* into one. A unit-test asserts each composed quantity's units are dimensionally valid.

### 3.2 Per-data-class storage, per-service dimension → (build)
`storage_gb_month` becomes a **map by data class** (raw telemetry / images / scored evidence), each with its own size × retention. Service-dimension mapping (`:295`) selects the data classes a service actually stores — S3 (object/evidence), DynamoDB (state/dedupe, *not* image retention). DynamoDB must never inherit the image-retention number.

### 3.3 Plausibility / sanity gate → (build — the artifact-level check the eval was missing)
A deterministic, domain-blind gate over the derived quantities, run before they reach any artifact:
- `telemetry_events/month` ≤ `asset_count × (seconds_per_month / min_plausible_cadence)` (catch the 22.5×);
- `storage_gb_month` flagged if it implies an implausible per-asset footprint (e.g. > N TB per asset);
- no two services with byte-identical derived quantity + formula;
- any quantity failing the gate is **dropped to `not_estimated` with the reason**, never shown as a confident number.
This is "honest beats absurd": an unbindable quantity is fine; an absurd one is not.

### 3.4 Convergence reconciliation: generic ↔ source-truth → (build)
Before export, the generic-derivation quantities must **reconcile** with the source-truth line-item quantities (`raw/pricing.json`). If they diverge beyond a tolerance (the 22.5× case), it is a **blocker** — the package cannot present a quantity the two computations disagree on. Prefer the source-truth value; if only the generic exists, it must pass the plausibility gate (§3.3).

### 3.5 Client prose hygiene → (build)
- `synthesis.py:283`: stop concatenating raw `"Synthesis interview note: … Answer: …"` onto `refined_problem_statement`. Keep the structured Q&A in `raw/`/brief metadata; render a **summarized** version in client prose.
- `client_pack._solution_brief`: render a clean problem statement; **strip** the `"not X, not Y…"` negation tail (it belongs in exclusions metadata, not exec prose) and any `"Synthesis interview note:"` text.
- Linter: add a client-prose rule that fails on `"Synthesis interview note:"`, a `"not <word>, not <word>"` run, or a raw-driver dump.

---

## 4. What must NOT change / must stay domain-blind
- No per-domain quantity formulas (no `if railway: …`, no `if images: domain==`). The type set and arithmetic name **no domain** (review-lens, mechanically grepped in acceptance).
- The negation/authority gate, `generic_not_estimated` honesty, reviewer reconciliation, `live_agent_calls` capture — unchanged.
- Pricing math for the **known** 14 catalog domains — the goldens (Legal/Healthcare/Telecom) must stay VALID/0-mismatch (non-regression).
- Manifest/verifier semantics, `REQUIRED_ARTIFACTS` — untouched.

---

## 5. The brutal eval battery (artifact-level, the real proof)
Structural green (verifier VALID, tests pass) did **not** catch 40 exabytes — so the battery must assert on **content**. Run ~10 never-coded scenarios (railway, museum conservation, port customs, space-debris, clinical-trial logistics, mining tailings, smart-building, marine-insurance, carbon-MRV, vertical-farming). Each must satisfy, automatically:
- **Plausibility:** every derived quantity within sane bounds (storage not in exabytes; events ≤ asset_count × max_rate; inferences not = images×events).
- **Convergence:** generic-derivation quantities reconcile with source-truth line items (no >2× divergence).
- **Consistency:** no family in both selected+excluded; no excluded-family service; no excluded vocabulary in prose.
- **Prose:** no `"Synthesis interview note:"`, no `"not X, not Y"` dumps in `client_pack`.
- **Completeness/honesty:** no dead-end; pricing honest (`not_estimated` allowed, absurd not); verifier VALID; linter 0; `live_agent_calls` non-empty when a provider ran.
A scenario passing all of these *is* golden.

---

## 6. Verified anchors (confirmed 2026-06-17)

| Tag | Claim (proven) | Location / evidence |
|---|---|---|
| C1 | generic derivation produces 21.6B events / 19.18B inferences / 40.5 EB — reproduced on real package facts | `_generic_quantity_context` `source_truth_pricing_compiler.py:318` (run output above) |
| C2 | `monthly_images = monthly_base × image_per_item` multiplies event stream by per-asset count | `source_truth_pricing_compiler.py:358` |
| C3 | `monthly_events` sums base + base×per_item + hourly×720 (incompatible streams) | `source_truth_pricing_compiler.py:~345–352` |
| C4 | single `generic["storage_gb_month"]` → all storage services (S3 == DynamoDB) | `source_truth_pricing_compiler.py:295` |
| C5 | source-truth line items had the correct 959,040,000 (the divergence) | package `raw/pricing.json` line items |
| C6 | facts captured untyped (`explicit_quantity_<noun>_<n>`) — no semantic type | package `raw/pricing.json` `metadata.canonical_facts` (20 facts) |
| C7 | prose dump: interview notes appended to problem statement, rendered verbatim | `synthesis.py:283` → `client_pack.py:234 (_solution_brief)` |
| C8 | negation/authority + `generic_not_estimated` already fixed (do not re-touch) | `use_case_profile.reconcile_profile_constraints`, `_compile_generic_not_estimated` `source_truth_pricing_compiler.py:137` |

---

## 7. Acceptance / definition of done
- Re-running the **railway** facts through `_generic_quantity_context` (or its successor) yields **plausible** quantities (telemetry ≈ 959M/month, drone images ≈ ~10⁴/month, storage in TB not exabytes) — proven by a test that loads these exact facts and asserts bounds.
- S3 and DynamoDB no longer share an identical storage number.
- `client_pack` contains no `"Synthesis interview note:"` and no `"not X, not Y"` negation run (linter-enforced).
- Generic ↔ source-truth quantities reconcile (no >2× divergence) or the package degrades to honest `not_estimated`.
- The 10-scenario brutal battery passes the artifact-level assertions (§5).
- Goldens (Legal/Healthcare/Telecom) unchanged; full suite green; frontend PASS; verifier VALID; linter 0.
- `grep` for per-domain branches in the new quantity-graph code returns nothing (domain-blind).

---

*Spec authored 2026-06-17. All defects PROVEN by reproduction on `sess_e5b32ba58635`; anchors at §6. The fix is a typed, domain-blind quantity graph + plausibility/convergence gates + prose hygiene — it changes no classification, manifest, or verifier authority and introduces no per-domain logic. This is the slice that turns "completes end-to-end" into "golden."*
