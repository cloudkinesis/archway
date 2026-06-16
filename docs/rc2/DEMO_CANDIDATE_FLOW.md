# Spec — `feature/demo-candidate-flow`

**Status:** IMPLEMENTED — review candidate on `feature/demo-candidate-flow`.
**Date:** 2026-06-16
**Baseline:** `master` @ `caa8234` — includes D23 open-world understanding + the domain-refiner removal. **✓** [B1]
**Relates to:** D21 (agentic proposal lanes under deterministic authority), D22 (live Bedrock execution), D23 (open-world understanding + questions), the `archway-review-lens` standing rule (no hardcoding; LLM proposes, deterministic validates).

> **Anti-hallucination rule.** Every "the code currently does X" claim is tagged **✓** with a file:line in §8, verified against the working tree on 2026-06-16. Every "we will build Y" is tagged **→**. Re-confirm anchors at build time; line numbers drift. This document deliberately under-promises: see §3 for what it does **not** do.

---

## 1. Why this branch exists (the gap it closes)

After D23, a **novel** use case (one outside the ~14 catalog domains) gets a smart open-world **understanding and questions**, and then a **thin, generic dossier**, because the downstream pipeline is still catalog-bound: `selected_patterns(profile)` falls back to the generic `web_api_application` pattern when nothing matches **✓** [B8], producing generic architecture, pricing, and diagrams.

Meanwhile, the D22 agentic lanes **already produce a typed, model-proposed candidate** for architecture, pricing dimensions, diagram views, narrative, and reviewer findings — but those candidates are written **audit-only** (`raw/` + `audit_pack/`) and never reach the customer-facing `client_pack/`. **✓** [B2][B11]

**This branch surfaces those labeled candidates into `client_pack/` for novel use cases**, so the tool produces a *useful, honest* dossier for any legitimate use case — not a generic template. It is the "demo-candidate-flow" milestone: the front (D23) and the back (catalog) get bridged by labeled candidates.

---

## 2. The design: two-tier client-facing output

For each dossier, decide per the **novelty signal** and the **candidate availability**:

```
KNOWN domain (catalog matched a real pattern)        → client_pack = deterministic (unchanged)
NOVEL domain (catalog fell to web_api_application)   → client_pack = LABELED candidate surfacing
   AND a live candidate exists (live_demo + enabled)
NOVEL domain, no live candidate (offline/disabled)   → client_pack = deterministic generic floor (unchanged,
                                                        honestly thin) — no dead-end
```

**Novelty signal (deterministic, domain-blind):** the architecture used the generic fallback. Detect via `profile.primary_family == "web_api_application"` **✓** [B9] / `selected_patterns` returning only the `web_api_application` pattern **✓** [B8]. This is a structural signal ("the catalog had no specific match"), **not** a per-domain check — no domain names appear in the selection logic (review-lens requirement).

**Candidate availability:** the architecture/pricing/diagram/narrative/reviewer lanes return a real (non-disabled) proposal only when `enable_agentic_*` is true and `agentic_mode == "live_demo"`; otherwise they return a disabled-shaped trace **✓** [B2]. So candidate surfacing activates exactly when there is a live model proposal to show.

When novelty + live-candidate both hold, `client_pack/` renders the candidate content (architecture components/flows/controls, pricing dimensions + drivers, recommended diagram views, narrative) **clearly labeled** as candidate, directional, and needing human review, and demotes the generic deterministic output to an "automated baseline" note. Otherwise `client_pack/` is unchanged. The literal machine token remains out of client prose; raw provenance stays in `raw/` and `audit_pack/`.

---

## 3. Explicit scope boundary — what this branch does NOT do

To avoid over-scoping (and the mistakes that come with it), the following are **deferred and stated plainly**:

1. **No native diagram rendering of candidate architectures.** The candidate is `ArchitectureCandidateProposal` (components/flows/controls) **✓** [B3]; the diagram compiler renders an `ArchitectureSpec` **✓** [B7]. A candidate→`ArchitectureSpec` adapter + compiler validation + fallback handling is its own risk surface and belongs to **D25 (open-world architecture)**. For novel domains, **diagrams remain the deterministic-rendered baseline**, and the candidate's recommended views are surfaced as a **labeled "proposed views (not yet natively rendered)"** section with an honest disclosure. No fake "rendered" claim is ever made for a candidate view (the D21 diagram rule).
2. **No change to pricing math, SKU binding, the deterministic pipeline for known domains, the diagram compiler, readiness authority, governance, manifest/verifier semantics, or `REQUIRED_ARTIFACTS`.**
3. **No new hardcoding.** The candidate flow surfaces whatever the lanes proposed; it contains **zero per-domain branches**. The only new decision is the structural novelty signal (§2), which names no domain.
4. **No promotion of readiness.** Candidate content is labeled; `model_proposed` provenance can never unlock a readiness tier (D21) **✓** [B12]; the architecture candidate stays `human_review_required` + `procurement_cap` **✓** [B3].

**Honest statement to the user — what "works correctly" means after this branch:** any legitimate use case produces a **complete, honest, useful** dossier. Known domains: full deterministic dossier (as today). Novel domains (live): real model-proposed architecture/pricing/views, clearly labeled directional/candidate, never a generic stub, never a dead-end. **Bespoke novel diagrams** (candidate rendered to native views) come in **D25**.

---

## 4. Implementation

### 4.1 New: candidate-flow selector (deterministic, domain-blind) → (build)
A small service, e.g. `app/services/agentic/candidate_client_flow.py`, that given (profile, architectures, the five lane traces) returns a typed `ClientFacingPlan`:
- `tier`: `deterministic` | `candidate` (per §2).
- `reason`: e.g. `"catalog matched pattern <id>"` or `"no catalog match; surfacing model-proposed candidate"`.
- The candidate payloads to render (architecture components/flows/controls, pricing dimensions, proposed views, narrative) **only when `tier == candidate`**.
No domain names; decision is purely (novelty signal) × (candidate availability).

### 4.2 Modify: `client_pack` renderers to accept the plan → (build)
Thread the `ClientFacingPlan` into `client_pack_files` **✓** [B10] and have each section render deterministic-or-candidate:
- `_architecture_summary` **✓** [B10]: candidate components/flows/controls with candidate/directional wording and the human-review/procurement caveat.
- `_pricing_summary` **✓** [B10]: candidate pricing dimensions + drivers; every quantity labeled `assumed`/`not_estimated` per the binder; **no fabricated totals** (reuse the existing directional/readiness wording).
- `_diagrams_index` **✓** [B10]: deterministic rendered diagrams + a labeled "proposed views (not yet natively rendered)" list from the diagram-plan candidate.
- `_risks_and_gates` **✓** [B10]: include the reviewer candidate findings (additive, labeled), and the "to advance beyond candidate" gates (human review, evidence, driver confirmation).
- Front matter (`START_HERE` / executive memo): readiness tier reflects candidate status (it cannot exceed `demo_ready` for a model-proposed architecture — gate via existing `compute_readiness_tier` + the procurement cap) **✓** [B12].

### 4.3 Reuse (do not rebuild)
The five D22 lane builders and their proposals **✓** [B2][B3][B4][B5][B6]; the readiness tiers + labels; the artifact linter; the client/audit pack split; the export flow. The candidates already exist in every export — this branch consumes them client-side; it does not change how they are produced.

### 4.4 audit_pack and raw — unchanged
The full candidate traces stay in `raw/` + `audit_pack/` exactly as today **✓** [B11]. `client_pack` shows the labeled customer view; the audit pack remains the provenance record (prompt/response hashes, validation issues, rejected items).

---

## 5. Trust-spine invariants (must hold; tested)

1. **Known domains are byte-unchanged.** A known-domain dossier (Legal/Healthcare/Telecom golden) renders identically — the candidate flow is inert when the catalog matched.
2. **No fake certainty.** Every candidate claim in `client_pack` carries a human-readable label (`candidate` / `directional` / `not estimated` / `needs review`).
3. **No fake "rendered."** A candidate diagram view is never presented as rendered unless the compiler ledger says so (it won't, this branch — they are "proposed, not yet natively rendered").
4. **model_proposed cannot unlock readiness; candidate architecture stays human-review + procurement-capped.** **✓** [B12][B3]
5. **No client-pack machine leakage.** `client_pack` still passes the artifact linter with 0 findings (no `model_proposed`, `AgentProposal`, `prompt_hash`, provider names in client prose) **✓** [B13] — the candidate is rendered in business language; raw provenance stays in audit/raw.
6. **No dead-ends.** Every dossier (known, novel-live, novel-offline) is complete and exportable; verifier VALID; the outcome is solution / directional-diagnostic / unsupported-refusal.
7. **No new hardcoding.** `grep` for per-domain branches in the new selector and the modified client_pack returns nothing; the novelty signal names no domain.

---

## 6. Tests (→)

- **Known-domain non-regression:** with `tier == deterministic`, `client_pack` is unchanged (snapshot/assert the three goldens render identically; verifier VALID, linter 0).
- **Novelty selector (domain-blind):** a profile with `primary_family == "web_api_application"` + a live candidate → `tier == candidate`; a profile that matched a real pattern → `tier == deterministic`. Assert the selector references no domain string.
- **Candidate surfacing:** with a mocked live architecture/pricing/diagram candidate, `client_pack` renders the candidate components/dimensions/views, each **labeled**, and the linter returns **0 findings** (no machine vocabulary leaks).
- **No fake certainty / no fake rendered:** candidate diagram views appear as "proposed, not yet natively rendered"; no view claims rendered without the compiler ledger.
- **Readiness cap:** a novel candidate dossier cannot exceed `demo_ready`; `model_proposed` does not unlock readiness; architecture candidate stays `human_review_required`.
- **No dead-end / completeness:** novel-live, novel-offline, and known all produce a complete exportable package; verifier VALID.
- **Audit unchanged:** `raw/` + `audit_pack/` candidate traces are byte-identical to pre-branch for the same inputs (the producer is untouched).

---

## 7. Validation (→)

```
.venv/bin/python -m pytest -q
.venv/bin/python scripts/rc2_validate.py --profile golden --frontend --allow-missing-optional-tests
cd frontend && npm run build
.venv/bin/python scripts/d23_eval_battery.py            # fixture
# live, refiners-disabled, with a NOVEL use case through the full export, confirm:
#   - client_pack shows labeled candidate architecture/pricing/proposed-views
#   - linter 0 findings, verifier VALID, no dead-end
```
Goldens (Legal/Healthcare/Telecom): VALID, 0 missing, 0 mismatched, linter 0, client-leaks 0 — **unchanged**, proving known-domain non-regression.

---

## 8. Verified anchors (confirmed 2026-06-16)

| Tag | Claim | Location |
|---|---|---|
| B1 | master includes D23 + refiner removal | `git log` — `caa8234`, `35dd3ef`, `836e3b4` |
| B2 | candidate lanes audit-only; live only when `enable_agentic_*` + `agentic_mode=="live_demo"`; else disabled-shaped | `app/services/agentic/architecture_candidate_agent.py:427–429` (same pattern in pricing/diagram/narrative/reviewer agents) |
| B3 | `ArchitectureCandidateProposal` (candidate_components/flows/controls, `human_review_required`, `procurement_cap`, `provenance="model_proposed"`) | `app/services/agentic/architecture_candidate_agent.py:105` (+ component/flow at :40,:53) |
| B4 | `PricingDimensionProposal` (service/usage-dimension/driver candidates) | `app/services/agentic/pricing_dimension_agent.py:78` (+ :31,:40,:58) |
| B5 | `DiagramViewPlanProposal` / `DiagramViewCandidate` | `app/services/agentic/diagram_planning_agent.py:47` (+ :22) |
| B6 | narrative / reviewer proposals | `app/services/agentic/narrative_agent.py:40`, `app/services/agentic/reviewer_agent.py:58` |
| B7 | compiler renders `ArchitectureSpec` (not the candidate) | `app/models/domain.py:593`; `app/services/diagram_compiler_adapter.py:27,30` |
| B8 | `selected_patterns` falls to generic `web_api_application` | `app/services/pattern_catalog.py:448,454` |
| B9 | `primary_family` / generic fallback signal | `app/services/use_case_profile.py:41–42` |
| B10 | client_pack render functions modified | `app/services/client_pack.py:58 (client_pack_files), :241 (_architecture_summary), :340 (_pricing_summary), :418 (_risks_and_gates), :479 (_diagrams_index)` |
| B11 | export invokes candidate lanes → `raw/` + `audit_pack/`, and now threads traces into the labeled client renderer | `app/services/export_package.py:626–683` (+ audit_pack agentic-*.md writers) |
| B12 | readiness tiers; `model_proposed` cannot unlock readiness | `app/services/customer_readiness.py` (`compute_readiness_tier`); `app/services/agentic/provenance.py` (`can_unlock_readiness`) |
| B13 | artifact linter gates client_pack (0 findings) | `app/services/artifact_linter.py` |

---

## 9. Open questions for review

1. **Default for known-domain + live-candidate:** show deterministic only (recommended — the catalog is authoritative there), or also append a small "alternative candidate (audit)" pointer? Recommend deterministic-only to avoid confusing the customer view.
2. **Selector home:** new `candidate_client_flow.py` (recommended, keeps `client_pack.py` lean) vs inline in `client_pack_files`.
3. **Readiness ceiling for novel candidates:** confirm `demo_ready` is the correct cap (not `internal_only`) given the candidate is validated (services real, facts preserved) but human-review-pending.
4. **Pricing for novel domains:** when the binder cannot bind any dimension, the summary is `not_estimated` with the proposed dimensions listed — confirm this reads honestly and is not mistaken for "no pricing."

---

## 10. Definition of done

- A novel, never-seen use case run live, refiners off, produces a `client_pack` with **real labeled candidate** architecture, pricing dimensions, and proposed views — not a generic stub — and never a dead-end.
- Known-domain goldens render **identically** (non-regression), verifier VALID, linter 0, client-leaks 0.
- `client_pack` passes the artifact linter (0 findings); no `model_proposed`/provider/hash leakage in client prose.
- No new hardcoding (selector + client_pack contain no per-domain branch); the novelty signal names no domain.
- Full suite green; golden harness READY; frontend build PASS; D23 live eval still 12/12.
- The deferred boundary (native candidate diagram rendering = D25) is stated in the PR.

---

*Spec authored 2026-06-16. ✓ anchors verified at draft time (§8); → items are targets. Re-confirm at build time. This branch surfaces labeled D22 candidates into the customer-facing pack for novel use cases; it changes no pricing math, compiler, readiness, or verifier authority, introduces no new domain logic, and defers native candidate-diagram rendering to D25.*
