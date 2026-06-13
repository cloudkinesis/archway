# D22 — Live Bedrock Agentic Demo (branch spec v3, review candidate)

**Branch:** `feature/d21-live-bedrock-agentic-demo`
**Status:** SPEC v3 — review candidate. No code yet. The *live-execution* milestone of D21: it adds the engine to the cage D21 built, **and the product UI/API path to drive it.**
**Date:** 2026-06-13
**Changes from v2 (8 Codex precision fixes):** `off` mode preserves disabled/control-plane traces for verifier compatibility, default mode is `audit` (§4); misconfiguration is setup-required, not session-abort (§4); `token_usage` is not mandatory for "real" (§2,§7); promise scoped to non-sensitive/configured cases (§1); interactive ambiguity contract added (§13a); first-UI bar decided as minimal+expandable (§13); live_demo gets a *separate* sensitivity profile, D7/D15 untouched (§9); staged in-branch phases A–E (§5).
**Changes from v1 (22 Codex amendments):** async bridge reuse (§11), value-level PHI screening (§9), frozen `REQUIRED_ARTIFACTS` + additive artifact contract (§17), UI scope (§13), API/export-path integration (§12), `LiveCallAudit` schema (§6), outcome-specific artifacts (§17), no-dead-end invariant (§2), demo-ready definition (§19).
**Relates to:** D21, D7/D15, Branch-4 readiness tiers.

> **Anti-hallucination rule (same as D21).** Every "already exists" claim is **✓** with a file:line in §20. Every "must build" is **→**. Re-confirm anchors at build time.

---

## 1. The honest promise

A user enters any AWS-oriented use case **in the app**. For any **non-sensitive, live-demo-configured** use case, Archway **makes real Bedrock calls** to resolve ambiguity, ask or assume missing facts, synthesize research, propose pricing dimensions, propose an architecture candidate, and plan diagrams. For blocked or misconfigured cases (sensitive values, budget exhausted, Bedrock not set up), Archway **records why live calls were skipped and still completes a package.** Either way, **deterministic gates validate, downgrade, or reject** each proposal, and a complete package always comes out (`client_pack/` + `audit_pack/` + `raw/`), viewable and downloadable in the app.

Two sentences govern everything:
> **Archway always completes the journey. Archway never fakes certainty.**

Out of scope this branch (deferred, stated so nobody assumes otherwise): live web/AWS-Docs browsing (Research is Option A only, §15), procurement-grade pricing for novel services, and autonomous/approved architecture.

---

## 2. Governing invariant: no dead-ends, no fake-live

**Every submitted use case completes with artifacts. No session ends at "invalid / cannot continue / no package."** The outcome is always exactly one of:
1. **Solution package** — mapped/pattern-backed, deterministic gates pass.
2. **Directional / diagnostic package** — coherent but gates not fully met; assumptions, missing facts, not-estimated pricing, candidate architecture, repair plan, diagram fallback notes.
3. **Unsupported / refusal package** — unsafe, non-AWS, impossible, or underspecified; a finished explanation of *why*, what would make it supportable, safe alternatives, and an audit trace — **no fake architecture/pricing.**

Applied to live calls:
- A failed live call (throttle/timeout/malformed) **downgrades that lane** and is recorded; the package still completes. Never aborts, never silently substitutes a fixture.
- A trace claiming `provider: bedrock` must carry real `model_id` + `response_hash` + `duration_ms` + `prompt_hash` + `validated/status`, or it cannot claim live. `token_usage` is recorded **when Bedrock returns it**; if absent, a `token_usage_unavailable` warning is recorded (not a failure) (§7).
- Every D21 guardrail holds **identically** in live mode — live reuses the audit-mode validators; it never gets a looser path.
- **No UI state may terminate at** `invalid` / `cannot continue` / `unsupported` / `failed`. It must always continue to a diagnostic / refusal / assumption-led / repair-plan package the user can export (§13).

---

## 3. Confidence-tiered artifacts (not "any use case gets full artifacts")

- Any **legitimate** AWS-oriented use case gets complete artifacts.
- Unsafe / non-AWS / impossible / underspecified use cases get **diagnostic or refusal** artifacts.
- Not every use case gets procurement-ready pricing. Not every use case gets approved architecture. Not every diagram candidate becomes rendered truth.

"Complete" means *the package is whole and honest*, not *everything is green*.

---

## 4. New mode switch → (must build)

`ARCHWAY_AGENTIC_MODE = off | audit | live_demo` (existing env convention **✓** [B1]). **Default = `audit`** — this preserves today's export shape (the golden packages already carry disabled/raw D21 traces; the verifier artifact counts depend on them). Changing the default would alter the frozen golden counts.

| Mode | Behavior |
|---|---|
| `off` | No live calls and no enabled agent proposals. **Existing disabled/control-plane D21 traces may still be emitted** so the verifier/golden artifact counts stay intact. **✓** [B2] Do not drop those artifacts. |
| `audit` | Current D21 default: deterministic disabled/fixture providers write raw+audit traces. **✓** [B2] |
| `live_demo` | Real Bedrock-backed providers for flag-enabled lanes; output passes deterministic gates; `client_pack` gets gated narrative only after approval; `raw/`+`audit_pack/` always carry full provenance. |

**Setup-required, not session-abort (must build — resolves the §2 no-dead-end tension):** in `live_demo`, if `bedrock_model_id` is unset **✓** [B3] or `llm_provider != "bedrock"` **✓** [B4], the **live run is setup-required**: no Bedrock call is attempted, and the session **continues in deterministic/audit mode to a complete diagnostic package.** It does not abort the session. The message is:
```
Live agentic demo unavailable: ARCHWAY_BEDROCK_MODEL_ID is not configured (llm_provider must be 'bedrock').
Continuing in deterministic mode; a diagnostic package will still be generated.
```
The UI renders this as a **setup-required banner**, distinct from "use-case invalid" (§13). Never fall back to a fixture while *claiming live*. Tests pin both (§18).

---

## 5. One shared live-provider harness, then 8 templates → (key decision)

Do not write 8 Bedrock integrations. The per-lane `Protocol` pattern exists **✓** [B5]. Build one harness every lane calls:
```
live_call(task_type, prompt_messages, response_schema, *, session_id, lane) ->
  1. sensitive-VALUE screen (§9) — if blocked, SKIPPED LiveCallAudit (no Bedrock call)
  2. budget check (§10) — if over ceiling, NOT_ATTEMPTED LiveCallAudit
  3. _collect_async( ModelRouter().complete(task, messages, response_schema=...,
       temperature=0, max_tokens=settings.bedrock_max_tokens,
       timeout_seconds=settings.bedrock_timeout_seconds) )   ✓ [B6][C1]
  4. on exception after settings.bedrock_retry_count -> FAILED LiveCallAudit, downgrade lane
  5. structured parse-or-reject (§8) — malformed -> REJECTED LiveCallAudit
  6. emit LiveCallAudit (§6) into raw + llm_telemetry_store   ✓ [B7][B8]
  7. return parsed proposal to the lane's deterministic validator
```
One integration × 8 prompt templates + 8 response schemas + 8 validators.

**Verified wiring gotcha (must handle):** `ModelRouter.complete` routes to Bedrock only when `task.task_type in SONNET_TASKS` **✓** [B9]. Reusable existing members: `discovery_planner`, `deep_use_case_understanding`, `research_synthesis`, `pricing_filter_discovery`, `service_decision_reasoning`. Lanes without a match (architecture, diagram, narrative, reviewer) **must add a new `LLMTaskType` AND add it to `SONNET_TASKS`** — else `complete()` silently returns the deterministic empty result and never calls Bedrock. A test asserts every live lane's task type is in `SONNET_TASKS`.

**Staged build order in-branch (checkpoints, same branch):**
```
Phase A: shared harness + use-case-analyst lane LIVE (prove call→parse→validate→audit→client-gate + ambiguity §13a)
Phase B: pricing-dimension lane LIVE
Phase C: research, architecture, diagram lanes LIVE
Phase D: narrative, reviewer lanes LIVE
Phase E: UI surfaces + the manual live app-path run (§18)
```
Each phase is independently testable; do not wire all seven lanes blind.

---

## 6. `LiveCallAudit` shared schema → (must build)

Every live lane trace embeds one `LiveCallAudit` (fields map mostly to `LLMResult` **✓** [B7]):
```
provider        (LLMResult.provider, "bedrock" when live)
model_id        (LLMResult.model_id)
task_type       (the LLMTaskType used)
duration_ms     (LLMResult.duration_ms)
token_usage     (LLMResult.token_usage, when returned)
retry_count     (LLMResult.retry_count)
validated       (schema parse success)
prompt_hash     (hash_payload(messages))   ✓ [B10]
response_hash   (hash_payload(text))       ✓ [B10]
status          accepted | downgraded | rejected | skipped | failed | not_attempted
error_type      (on failed/rejected; else null)
skip_reason     (on skipped; e.g. "sensitive_value:ssn")
budget_state    (calls_used / max; on not_attempted: "budget_exhausted")
```
Written to `raw/live_agent_calls.json` (additive, §17).

---

## 7. Definition of "real" + response-hash honesty

A `live_demo` package is real iff ≥1 `LiveCallAudit` has `provider="bedrock"` with non-empty `model_id`, `response_hash`, `duration_ms`, `prompt_hash`, and a real `status`. `token_usage` is recorded **when Bedrock returns it**; when absent, a `token_usage_unavailable` warning is recorded and the trace is **still valid as real** (some models/paths omit usage). A deterministic check + test enforces this, and that **no fixture trace is ever labeled live** (§18).

**Response-hash meaning (state in spec + UI help):** live Bedrock is *not* byte-reproducible, even at temperature 0. `response_hash` is an **audit fingerprint of this run**, not a reproducibility key. The reproducible part in live mode is the *deterministic gates*; model proposals are recorded, not replayable. No test asserts equal `response_hash` across live runs.

---

## 8. Structured-output parse-or-reject → (must build — #1 thing that breaks real LLM demos)

Each call passes a Pydantic `response_schema` **✓** [B6] with `bedrock_enable_structured_output` **✓** [B19]. Then: valid parse → lane validator; malformed/empty/invalid → **`rejected`** `LiveCallAudit` with the response hash + parse error; **package continues. No crash. No silent drop. No fallback fixture pretending success.** A malformed-response test pins this per lane.

---

## 9. Sensitive-VALUE screening before any Bedrock call → (must build — refined per code)

Live mode sends user text to AWS, so screen before any `complete()`. **Add a SEPARATE `live_demo` sensitivity profile — do not alter the existing D7/D15 frontier-prior `_SENSITIVE_PATTERNS` behavior** **✓** [B20][C3] (avoids regressing the shipped model-prior path). The existing screen already does the right *value-level* thing for HCM/spaces/banking (bare topic words deliberately don't trip); its PHI patterns, however, trip on bare regulatory/domain words (`\b(PHI|HIPAA)\b`, `\bdiagnosis\b`) **✓** [C3] — too aggressive for a healthcare live demo. The new `live_demo` profile:
```
BLOCK actual values:  SSN, MRN + number, account numbers + digits, AKIA keys,
                      private keys, bearer/credential assignments, IBAN-format values.
ALLOW domain words:   HIPAA, PHI, diagnosis, hospital, claims, patient (as topic words).
```
This applies the value-level philosophy HCM/banking already use to PHI, scoped to live_demo only. It does **not** weaken security — a regulation name is a topic descriptor, not sensitive data. If a real value is detected, the lane returns a `skipped` `LiveCallAudit` (no Bedrock call) and the package still completes deterministically. Test: a healthcare use case containing "HIPAA/diagnosis/patient scheduling" (no real PHI values) makes live calls; the same text with an SSN value is skipped; **the D7/D15 model-prior screen is unchanged (its tests still pass identically).**

---

## 10. Per-call failure + per-run budget → (must build — no dead-ends for live)

- **Per-call failure:** after `settings.bedrock_retry_count` retries **✓** [B21], a failing call yields `failed` `LiveCallAudit` and downgrades that lane; package completes with what succeeded.
- **Per-run budget:** add `ARCHWAY_AGENTIC_MAX_BEDROCK_CALLS` (demo default e.g. 24). Over budget → remaining lanes `not_attempted` (budget); the UI shows "budget exhausted"; package still completes.
- Outcome always lands on solution / diagnostic / refusal — never a crash.

---

## 11. Async bridge → (reuse, do not build — verified)

`generate()` is sync **✓** [C1] and `ModelRouter.complete` is async **✓** [B6]. A loop-safe bridge already exists: `_collect_async` (export path, "avoids nested-loop hacks, never unsafe run on a running loop") **✓** [C1] and `_run_async` (ThreadPoolExecutor) **✓** [C2]. Live calls in export/session flows **route through these**; no new event-loop machinery, no nested-loop hacks, no silently-skipped call because a loop is running. A test asserts a live call completes whether or not an event loop is already running.

---

## 12. Application-path integration → (must build — not a CLI-only proof)

`scripts/d21_live_demo_run.py` is for the manual acceptance run only. The demo must work through the **real product path**:
- `ExportPackageService.generate` emits live `LiveCallAudit` traces when `agentic_mode == live_demo`. **✓** [B22 export hook]
- The existing backend/API/session/export flow drives it (create session → run live agentic discovery/research → architecture → diagrams → export → view/download).
- The UI can start or display a `live_demo` run.
No agent output bypasses the export/gate pipeline. Live mode is a *mode of the existing flow*, not a side channel.

---

## 13. UI scope → (must build)

**First UI bar (decided): minimal + expandable detail.** Ship the required strip first; the full per-lane panel can follow.

Required first UI (must build):
- **Agentic mode badge:** Off / Audit / **Live Bedrock Demo**; Bedrock model id.
- **Bedrock setup status** (configured / setup-required).
- **Per-lane status row:** queued → calling Bedrock → validating response → accepted / downgraded / rejected / skipped-sensitive / failed-but-continuing / budget-exhausted.
- **Outcome classification:** solution / directional-diagnostic / unsupported-refusal.
- **Assumptions / gaps summary.**
- **Export package button — always available after completion.**

Expandable-later: full per-lane panel (pricing confidence state, architecture review state, diagram render/fallback state, export readiness state, evidence/research gaps detail).

**No dead-end UI rule:** the user can always reach an exportable package. No screen terminates at invalid/failed/unsupported without a continue-path to a diagnostic/refusal/assumption-led/repair package. Client-facing UI shows none of: raw prompt, raw response, `AgentRun`, `AgentProposal`, `model_proposed`, `prompt_hash`, `response_hash`, provider names (those are audit/raw only).

### 13a. Interactive ambiguity handling → (must build)

The "ask or assume" promise needs a concrete interaction contract:
```
If missing facts are CRITICAL:   UI presents focused questions.
If the user answers:             bind as user-confirmed (canonical fact).
If the user does not know/skips:  create a scenario assumption (labeled) and continue.
If the user abandons:            proceed with assumptions; never block forever.
```
**No question may block package completion indefinitely.** Non-critical missing facts become assumptions without prompting. Every assumption is visible in the assumptions ledger (§13) and the audit pack.

---

## 14. Pricing requirement (dimension discovery, not universal live pricing)

Production pricing code stays generic — no hardcoded service names (already true; names in fixtures only **✓** [B23]). The agent **discovers usage dimensions and missing drivers** as `ServiceUsageDimension` candidates **✓** [B13]. The deterministic binder decides `bound` / `scenario_assumed` / `ambiguous` / `missing_quantity` / `not_estimated` / `unsupported` **✓** [B14]. Scenario-assumed → `AssumptionRecord(source="scenario_profile")` + `PricingDriverBinding(status="assumed")` **✓** [B24]. **No fake totals; no procurement-ready pricing unless deterministic pricing gates pass; retire the generic `(20,60,180)` placeholder for any agent-touched service.**

---

## 15. Research requirement (Option A only — not live retrieval)

Bedrock synthesizes from **provided deterministic context only**. No live AWS-Docs/pricing browsing. Claims needing fresh evidence are labeled `gap` (existing `classify_research_status` **✓** [B12]) and cannot promote past demo readiness. **The spec must not claim "authoritative fresh research" this branch.** Option B (allowlisted retrieval) is explicitly out of scope.

---

## 16. Architecture & diagram (proposal vs truth)

**Architecture:** model output is *candidate material only*. Only the deterministic compiler/spec pipeline creates architecture truth. Flow: propose typed candidate → deterministic adapter validates/maps safe parts → compiler renders only validated architecture → audit records rejected/downgraded proposals → `human_review` defaults `not_reviewed`, `procurement_cap` enforced **✓** [B15]. If a candidate can't be safely mapped, produce a **diagnostic architecture posture + candidate audit trail** (not a crash, not fake truth). No mutation of `SemanticArchitectureSpec`/FlowLedger/ViewPlanner/Layout IR/compiler/rendered diagrams.

**Diagram:** planner proposes views only. Compiler + rendering ledger **✓** [B16] decide `Rendered` / `Rendered with fallback` / `Not rendered (audit-only candidate)`. **Client pack cannot claim a diagram exists unless the artifact exists and the ledger confirms it.**

---

## 17. Always-generated artifact contract → (additive; verifier semantics frozen)

**`REQUIRED_ARTIFACTS` stays exactly its current 6 entries** **✓** [C4] — changing it is a forbidden verifier-semantics change. The contract below is a **D22 product guarantee** that these are *always present in a live_demo package*, with new files added **additively** (manifest inventory auto-hashes them):
```
README.md · manifest.json · 01-solution-brief.md · 03-pricing.md
client_pack/ · audit_pack/ · raw/
raw/session.json · raw/pricing.json · raw/agent_runs.json · raw/live_agent_calls.json
```
If architecture/pricing/diagrams aren't fully possible, include **diagnostic versions**, not omissions.

**Outcome-specific contents:**
- *Solution:* rendered diagrams, pricing posture, architecture summary, risks/gates, evidence summary.
- *Directional/diagnostic:* assumptions, missing facts, not-estimated pricing, candidate architecture, repair plan, diagram fallback notes.
- *Unsupported/refusal:* why unsupported, what would make it supportable, safe alternatives, audit trace — **no fake architecture/pricing.**

---

## 18. Acceptance tests (mocked ModelRouter in CI; one manual live run)

Automated (mock `ModelRouter.complete` → canned `LLMResult`; no real network in CI):
- `live_demo` reports setup-required if `bedrock_model_id` missing or `llm_provider != bedrock`; no Bedrock call is attempted, and the session continues to a deterministic/audit diagnostic package.
- `live_demo` never uses the fixture provider; never `provider=deterministic_fixture` with `live_demo=true`.
- every live lane's `task_type` ∈ `SONNET_TASKS`; each lane calls `ModelRouter.complete` via the shared harness.
- live call works whether or not an event loop is already running (async bridge).
- sensitive **value** (SSN) → zero Bedrock calls, `skipped`; domain words (HIPAA/diagnosis, no values) → calls proceed.
- malformed/empty response → `rejected`, no crash; failing call → `failed`, lane downgraded, package completes; budget exceeded → `not_attempted`.
- `model_proposed` cannot unlock readiness; missing pricing drivers → questions or `scenario_assumed`, never silent nonzero.
- unknown use case → diagnostic package; unsafe → refusal package (no crash either).
- architecture proposal can't become truth without deterministic validation; procurement cap holds; diagram can't claim `Rendered` unless ledger confirms.
- narrative reaching client_pack passed the narrative validator; client_pack zero D21-machinery leakage; audit_pack/raw include all `LiveCallAudit` with hashes.
- provability: every `provider: bedrock` trace has model_id + response_hash + duration_ms.
- always-generated artifact contract present for all three outcomes; `REQUIRED_ARTIFACTS` unchanged; verifier VALID.

Manual live run (not CI — real cost):
```
ARCHWAY_AGENTIC_MODE=live_demo ARCHWAY_LLM_PROVIDER=bedrock \
ARCHWAY_BEDROCK_MODEL_ID=<model-or-inference-profile> \
ARCHWAY_ENABLE_AGENTIC_USE_CASE_ANALYST=true ARCHWAY_ENABLE_AGENTIC_RESEARCH=true \
ARCHWAY_ENABLE_AGENTIC_PRICING=true ARCHWAY_ENABLE_AGENTIC_ARCHITECTURE=true \
ARCHWAY_ENABLE_AGENTIC_DIAGRAM_PLANNER=true ARCHWAY_ENABLE_AGENTIC_NARRATIVE=true \
ARCHWAY_ENABLE_AGENTIC_REVIEWER=true \
.venv/bin/python scripts/d21_live_demo_run.py --use-case "<any AWS-oriented use case>"
```
Manual acceptance must prove: Bedrock calls > 0; `provider=bedrock` + `model_id` + prompt/response hashes in traces; package generated; client_pack clean; audit_pack + raw populated; **and the same run reachable through the app UI showing live call status.**

---

## 19. Demo-ready means

> A user enters a new AWS-oriented use case **in the app**. Archway **visibly calls Bedrock**. It resolves ambiguity via questions or assumptions. It produces research / pricing / architecture / diagram proposals. It validates / downgrades / rejects safely. It generates a complete package. **The UI never dead-ends** — the user can always export and view artifacts.

---

## 20. Verified anchors (confirmed 2026-06-13)

| Tag | Claim | Location |
|---|---|---|
| B1 | env-flag convention | `app/core/config.py` (multiple) |
| B2 | D21 audit-only providers | `app/services/agentic/*_agent.py` |
| B3 | `bedrock_model_id` (None default) | `app/core/config.py:123` |
| B4 | `llm_provider` default `"deterministic"`; Bedrock routing | `app/core/config.py:121`, `app/services/llm/model_router.py:38` |
| B5 | per-lane provider Protocol + Disabled/Fixture/Live | `app/services/agentic/research_agent.py:96,106,147,252` |
| B6 | `ModelRouter.complete(task,messages,response_schema,temperature,max_tokens,timeout_seconds)` | `app/services/llm/model_router.py:28` |
| B7 | `LLMResult` fields (provider/model_id/duration_ms/token_usage/validated/retry_count) | `app/services/llm/base.py:39` |
| B8 | `llm_telemetry_store` | `app/services/llm/telemetry.py:25` |
| B9 | `SONNET_TASKS` Bedrock gate | `app/services/llm/model_router.py:11` |
| B10 | `hash_payload` | `app/core/logging.py:20` |
| B12 | `classify_research_status` → gap/conflict | `app/services/agentic/research_agent.py` (after :252) |
| B13 | `ServiceUsageDimension` | `app/domain/source_of_truth.py:66` |
| B14 | `bind_rate` statuses | `app/services/sku_pricing/binding.py:17–22` |
| B15 | arch `not_reviewed`/`procurement_cap=True`/human-review-removal blocked | `app/services/agentic/architecture_candidate_agent.py:30,117,433` |
| B16 | diagram view-rendering ledger | `app/services/agentic/diagram_planning_agent.py` + `diagram_compiler_adapter.py:120` |
| B19 | `bedrock_enable_structured_output` | `app/core/config.py:129` |
| B20 | `_SENSITIVE_PATTERNS` screen | `app/services/capability_router.py:80,:165` |
| B21 | `bedrock_retry_count`/`bedrock_timeout_seconds` | `app/core/config.py:126–127` |
| B22 | export emits agentic traces (hook point) | `app/services/export_package.py:454` |
| B23 | pricing generic (names in fixtures only) | `app/services/agentic/pricing_dimension_agent.py` |
| B24 | `AssumptionRecord(source="scenario_profile")` + `PricingDriverBinding(status="assumed")` | `app/domain/source_of_truth.py:39,:62` |
| C1 | `generate()` sync; `_collect_async` loop-safe bridge | `app/services/export_package.py:92, :1247–1270` |
| C2 | `_run_async` ThreadPoolExecutor bridge | `app/services/scenario_simulation.py:97–104` |
| C3 | PHI patterns trip on bare HIPAA/PHI/diagnosis (the over-block to refine) | `app/services/capability_router.py:80` block (PHI markers) |
| C4 | `REQUIRED_ARTIFACTS` = 6 entries (must stay frozen) | `app/services/dossier_manifest.py:33` |

---

## 21. Open questions for review

**Resolved by the v3 edits:** sensitivity scope → separate `live_demo` profile, D7/D15 untouched (§9); lane staging → Phases A–E in one branch (§5); UI depth → minimal + expandable (§13). Remaining open:

1. **New `LLMTaskType` members** are fresh per lane: `live_use_case_analyst`, `live_pricing_dimension`, `live_research_synthesis`, `live_architecture_candidate`, `live_diagram_planning`, `live_narrative_synthesis`, `live_reviewer_critique`; each is added to `SONNET_TASKS`.
2. **Budget ceiling** defaults to `ARCHWAY_AGENTIC_MAX_BEDROCK_CALLS=12`.
3. **Critical-vs-non-critical fact threshold** (§13a): critical facts are required for headline pricing, architecture safety, compliance/security posture, diagram renderability, or unsupported/refusal classification. Non-critical facts may be scenario-assumed and labeled. Reuse existing pricing closure, discovery, and reviewer signals where possible.

---

*Spec v3 authored 2026-06-13. ✓/C anchors verified at draft time (§20); → items are targets. Re-confirm at build time. This branch adds the engine and the product path — not new authority.*
