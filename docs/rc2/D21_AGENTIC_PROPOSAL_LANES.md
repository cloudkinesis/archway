# D21 — Agentic Proposal Lanes Under Deterministic Authority (approved design candidate, Phase 0 authorized)

**Status:** APPROVED DESIGN CANDIDATE / IMPLEMENTATION PHASE 0 AUTHORIZED. D21-0/D21-1 may implement the decision freeze, default-off contracts, deterministic repair planner, and raw/audit traces. The full D21 agentic system is not implemented by this status.
**Date:** 2026-06-13
**Relates to:** D7 (LLM proposes, deterministic pipeline owns safety), D15 (any-usecase contract; model prior advisory only), D16 (domain lane model), D17 (vendored compiler), D18 (accelerator packs), D19 (ADR no-invention), D20 (reviewer mode / uncertainty / scenario simulation). Builds on the Branch-4 readiness tiers.
**Supersedes:** D21 DRAFT v1. Moves no authority; grows the proposal surface only.

> **Anti-hallucination rule for this document.** Every claim of the form "Archway already has X" is tagged **✓** and backed by a file:line in §13 (Verified Anchors), confirmed against the working tree on 2026-06-13. Every claim of the form "this must happen" is tagged **→** and is a *target to build*, not current behavior. If a statement has neither tag, it is doctrine/opinion, not a fact about the code. Implementers must re-confirm anchors at build time; line numbers drift.

---

## 1. Goal (the honest version)

Archway becomes truly agentic when it can take **any legitimate AWS-oriented use case** and:

- discover the right **questions**,
- retrieve and **cite** authoritative research, and **synthesize** cross-source insight (tradeoffs, gaps, comparisons) — never invent novelty,
- propose **architecture and pricing candidates**,
- **validate or downgrade every claim** against the existing deterministic ledgers,
- render **clean diagrams** or disclose missing views,
- produce a **polished client pack** plus a **full audit pack**,

…where **mapped workloads can reach usage-ready when deterministic gates pass**, **novel workloads can reach usage-ready-as-a-reviewed-candidate after human review and evidence grounding**, and the system **never presents uncertainty as certainty or a silent number as a price**. Being *mapped* is necessary, not sufficient — the gates still decide.

That is demo-ready and usage-ready, honestly. The explicitly-rejected system is: *an LLM picks services, pricing tiers, and diagrams, and prose wraps them*. Clauses D21-A…F and refinements R1…R3 rule that out.

**Doctrine (the one-paragraph north star):**

> Archway is agentic in **exploration, not authority**. It can answer any legitimate use case by producing a **solution, diagnostic, or refusal** package. It becomes usage-ready when every output is either **grounded, assumed, proposed, rejected, or not-estimated** — and *labeled as such*. It does **not** become usage-ready by pretending every unknown is solved.

**Two distinct meanings of "usage-ready" (do not blur them — Codex fix 4):**
- **Product usage-ready** — a property of *Archway the tool*: safe for an SA or customer-solutions user to run and review. This is what "Archway is usage-ready" means.
- **Artifact confidence tier** — a property of *the output*: demo-ready / workshop-ready / procurement-ready.

An SA can use a product-usage-ready Archway to generate a package that is only *Demo ready* as an artifact. The tool being usage-ready never implies the artifact is procurement-ready.

---

## 2. Governing invariant: fail-closed never means fail-stopped

> **Every legitimate use case produces a complete, well-formed package. A gate that does not pass DOWNGRADES and LABELS; it never halts the pipeline or emits a broken artifact.**

"Invalid" is a **label on a line**, never a **termination of the run**. Three existing behaviors already follow this pattern and must not regress:

- Branch-4 readiness **caps** a package at a lower tier with a stated reason (`tier['reasons']`) instead of failing. **✓** [A6]
- The SKU rate binder returns `unsupported`/`not_found`/`missing_quantity`/`ambiguous` instead of a silent price. **✓** [A2]
- The diagram adapter records a fallback/omitted ledger instead of a blank. **✓** [A8]

**Honest correction to v1:** v1 claimed "pricing already emits `not_estimated` when a service is unmapped." That is **false for the main heuristic engine**: an unmapped service falls back to a **generic nonzero band** `(20, 60, 180, "usage-based managed service charges", 1.0)`. **✓** [A3] The `not_estimated` behavior exists only on the source-truth-compiler path for supported families. Retiring that silent placeholder is a *target* of the pricing lane (clause D21-D), not current behavior.

Completion taxonomy — every run lands on exactly one (clause from Codex pushback 1):

| Outcome | When | Still a complete artifact? |
|---|---|---|
| **Solution package** | mapped or pattern-backed workload, gates pass | yes — usage-ready |
| **Directional / diagnostic package** | coherent but gates not met (e.g. evidence missing) | yes — demo/internal-ready, with repair plan |
| **Unsupported / refusal package** | unsafe request (D15) or no responsible architecture possible | yes — a finished artifact explaining *why*, with a repair path |

There is **no code path** where a sane use case yields a half-built or aborted package. A refusal is a finished, readable artifact — not a mid-pipeline stop. **Not every use case yields a *well-architected architecture*; some yield a well-formed explanation of why one cannot be responsibly generated yet.**

---

## 3. Binding amendments (Codex D21-A … F)

**D21-A — No synthetic architecture truth.** A model-proposed architecture is a **candidate**, not an approved architecture. Deterministic validation (the existing architecture critique **✓** [A9]) proves *form and safety boundaries*, not *design correctness*. A model-proposed architecture may be **demo-ready as a candidate**; it cannot be workshop/usage/procurement-ready until **reviewed by a human or backed by deterministic pattern support**.

**D21-B — Claim-specific evidence gates** (amended by R1 below). AWS service/architecture claims require AWS Docs evidence; AWS pricing claims require AWS Pricing evidence; one evidence class cannot substitute for another. Current Branch-4 code uses a weaker package-level "docs OR pricing" rule. **✓** [A7] — this is what D21-B tightens.

**D21-C — Scenario assumptions are assumptions, not evidence.** A scenario-assumed quantity is a **presentation/readiness concept**, not a new ledger evidence class. It maps to existing fields verbatim: `AssumptionRecord(source="scenario_profile")` **✓** [A4a] + `PricingDriverBinding(status="assumed")` **✓** [A4b] + `pricing_driver_closure.directional_scenario_allowed = true` **✓** [A5]. No new evidence class is created for it.

**D21-D — Retire generic nonzero pricing placeholders.** Agentic pricing must move unknown service dimensions toward `not_estimated`, `ambiguous`, or `scenario_assumed` — **never a silent nonzero total**. The current generic `(20, 60, 180)` fallback **✓** [A3] is legacy behavior the pricing lane retires.

**D21-E — Evaluation battery gates client-facing output.** No agent lane may affect **client-facing artifacts** until at least the thin open-world battery exists and records hallucination, citation, pricing-label, and reproducibility scores (per-lane, see R3). Until then, an agent lane may write only to the audit pack and `raw/` traces.

**D21-F — Architecture procurement hard cap** (Codex fix 5, promoted from §8 to a binding clause). A model-proposed architecture **cannot be procurement-ready** unless it is **either human-approved or promoted into deterministic pattern support**. A validator proves structure (boundaries exist); it cannot prove design soundness. This is non-negotiable and separate from the readiness arithmetic in §8.

---

## 4. Refinements (Claude R1 … R3)

**R1 — Gate by provenance AND claim-kind so offline mode answers any use case without laundering authority** (Codex fix 2, refined). D21-B as stated would cap *everything* at demo in the clean/offline env (no MCP — the exact Branch-4 condition), because no architecture claim could get live Docs evidence. Resolution: gate by **origin of the claim** *and* **what the claim asserts**.
- A **`catalog_backed`** claim presented as **Archway catalog/pattern rationale** ("we recommend DynamoDB for hot operational state because…") is offline-eligible for demo/internal and workshop *as Archway rationale*. It carries no AWS-authority badge.
- A claim that represents **current AWS service capability, limits, availability, or a versioned best-practice** ("DynamoDB supports N transactions/sec", "service X is available in region Y") **requires AWS Docs evidence** for workshop/customer authority — *regardless* of catalog backing. Otherwise local catalog knowledge launders into "AWS says this."
- A **`model_proposed`** architecture/service claim requires AWS Docs evidence to promote past demo.
- **Refinement (Claude):** distinguish a **stable design principle** (multi-AZ for HA, least-privilege IAM — durable, offline-eligible as rationale) from a **versioned AWS fact** (quantified limits, regional availability — needs Docs). The test: "could AWS change this in a release?" If yes, it needs Docs; if it is a durable design principle, it stays rationale. This prevents the tightening from flagging every best-practice sentence as Docs-required, which would defeat offline answering.

This keeps the deterministic baseline answering *any* use case offline (as labeled rationale), while holding both AWS-capability claims and agent proposals to the evidence bar. (This is the mechanism behind the "mapped → usage-ready, novel → reviewed-candidate" split in §1.)

**R2 — "Usage-ready" is provenance-scoped and gate-qualified, not universal.** For mapped verticals and pattern-backed cases, Archway **can produce a usage-ready design when the deterministic evidence, pricing, governance, diagram, and readiness gates pass** — being mapped does not by itself make a design good. For a **novel** workload, the agentic lane produces a **reviewed candidate** — well-formed and safety-boundary-checked, but not autonomously certifiable as *the right* architecture, because no validator certifies design soundness, only design form (D21-A). "Usage-ready" for the open world therefore means **usage-ready-as-reviewed-candidate**. This line is the source of SA-leadership credibility, not a weakness to hide.

**R3 — The evaluation battery scores per-lane with explicit confidence labels.** Lanes are not equally measurable:
- **Mechanically scorable** (auto): pricing labels (`bound`/`scenario_assumed`/`ambiguous`/`not_estimated`), citation coverage, diagram render-or-disclose, reproducibility hashes.
- **Human-judged only**: architecture *soundness* — there is no deterministic oracle for "is this the right design." 
A single blended "hallucination rate" across lanes would overstate confidence on the one lane that cannot be auto-scored. The battery must report per-lane scores tagged `auto` vs `human`, or it launders confidence — exactly what D21 exists to prevent.

---

## 5. Provenance taxonomy — reuse what exists; add exactly one class

A parallel taxonomy would fork the verifier's vocabulary and recreate the two-sources-of-truth bug class (the shape of the Branch-4 BLOCK). The agentic layer **reuses** existing, verifier-wired provenance and adds **one** class.

Already implemented — do not duplicate:
- Pricing evidence classes — `DossierPricingEvidenceClass`: `sku_tier_backed`, `price_list_catalog_backed`, `pricing_mcp_backed`, `official_pricing_page_backed`, `heuristic`, `not_estimated`. **✓** [A1]
- Rate-binding outcomes — `bind_rate`: `bound`, `ambiguous`, `not_found`, `unsupported`, `unit_mismatch`, `missing_quantity`. **✓** [A2]
- Driver-binding status — `confirmed`, `assumed`, `missing`, `derived`. **✓** [A4b]
- Assumption provenance — `AssumptionRecord.source ∈ {deterministic_default, scenario_profile, user_input, derived}`. **✓** [A4a]
- Conflict provenance — `understanding_conflicts`, emitted in research metadata. **✓** [A10a]
- Canonical-fact provenance — `canonical_facts`, produced by the source-truth pricing compiler and emitted through pricing metadata / export `raw/` payloads (not research-flow metadata — Codex fix 1). **✓** [A10b]

**The one new class:** `model_proposed` — a claim originated by an agent, not yet grounded in an official source. Lowest trust. Always allowed in the audit pack; allowed in the client pack only after a validator upgrades it to a grounded class, or rendered as an explicit assumption/question. **A `model_proposed` claim never unlocks a readiness tier on its own** (D21-A, R1). D21 ships one mapping table from the existing classes plus `model_proposed`; it does not ship a second vocabulary.

---

## 6. The lane contract (identical for every lane)

```
1. Deterministic baseline runs FIRST and always.   → the package exists with the model OFF
2. Agent proposes only where the baseline is silent.
3. Validator accepts / downgrades / marks-assumed / rejects.   → code decides, never the model
4. Export records BOTH the customer-facing label AND the raw proposal trace.
```

If an agent is flagged off or unreachable, step 1's output is the package — i.e. today's deterministic Archway, full suite green, zero network. The default LLM provider is the literal string `"deterministic"`. **✓** [A11]

---

## 7. The lanes (build order = safe order)

Each is feature-flagged `ARCHWAY_ENABLE_AGENTIC_*` (default off — matching the existing `ARCHWAY_ENABLE_*` convention **✓** [A12]), Phase-0-inspected, Codex-reviewed as its own change. Order matters: architecture is **last** because it is the easiest place for a model to sound brilliant and be wrong.

1. **Repair planner — deterministic, no LLM.** Render the next-action plan from signals that already exist: `tier['reasons']` **✓** [A6], the pricing driver closure (missing/assumed drivers) **✓** [A5], the diagram fallback ledger **✓** [A8]. Output: "To promote Demo → Workshop: 1. confirm Lex text-request volume; 2. bind the rate from AWS Pricing; 3. refresh AWS Docs evidence." Ships **before** any agent; proves the propose-validate shape at zero model risk.

2. **Thin evaluation battery (10 scenarios).** Prerequisite for any client-facing agent output (D21-E). Scores per-lane, `auto` vs `human` (R3).

3. **Research agent.** Plans queries, pulls AWS Docs/Pricing evidence via the existing research flow **✓** [A13], returns cited findings. AWS claims require an official AWS source; "eye-opening" = cross-source synthesis, tradeoff framing, gap detection — never unsupported novelty (Codex pushback 5). Missing evidence **caps readiness**, never breaks generation.

4. **Use-case analyst agent.** Proposes a candidate profile (domain, workload-family candidates, actors, data classes, action flows, latency, compliance hints, missing facts, pricing drivers); extends the existing deep-understanding path **✓** [A14]. May not overwrite deterministic facts; disagreements → `understanding_conflicts` **✓** [A10a]; missing facts → questions or disclosed assumptions; sensitive-input screening still runs before any model call (D15).

5. **Pricing agent.** For services outside today's hand maps (`pricing_filter_mapper` is hand-mapped **✓** [A15]), proposes `ServiceUsageDimension` candidates — `aws_service_code`, `usage_name`, `unit`, `formula`, `required_rate_dimensions` **✓** [A4c] — plus required drivers and assumption profiles. The binder decides: `bound` / `scenario_assumed` / `ambiguous` / `not_estimated` (D21-C, D21-D). **Lex is the first proof case** (text/speech requests, streaming duration, sessions, region, monthly volume). Unknown volume → small-pilot / department / enterprise scenarios, quantity labeled `assumed` via `AssumptionRecord(source="scenario_profile")` **✓** [A4a].

6. **Dossier narrative agent.** Polishes client-pack language from **verified claims only**. May not introduce a service, price, AWS fact, or compliance claim. Every factual sentence maps to evidence, a disclosed assumption, or `not_estimated`. Client pack gets prose; audit pack keeps raw machinery.

7. **Reviewer / red-team agent.** Attacks the dossier (uncited claims, unsupported precision, missing drivers, domain leakage, readiness set too high, client-pack machine-speak). Sits on top of the deterministic reviewer **✓** [A16]; can only **add** findings, never remove or unlock.

8. **Diagram planning agent.** Chooses semantic views; emits a **view plan**, not diagrams. The compiler stays the renderer of truth (D17) via the existing view planner **✓** [A17] and adapter **✓** [A8]; unsupported views go to the rendering ledger; the agent can request a view but can never claim one rendered.

9. **Architecture candidate agent — last, hardest.** Proposes typed architecture candidates only (components, flows, trust boundaries, data classes, controls, failure modes, observability, assumptions). The deterministic critique **✓** [A9] checks the structural boundaries (identity, audit, encryption, network, observability). Carries `model_proposed` provenance; never self-unlocks readiness (D21-A); definition-of-done includes a human-review gate (R2).

---

## 8. Readiness stays deterministic (reuse Branch 4)

Tiers unchanged: `internal_only → demo_ready → workshop_ready → procurement_ready`. **✓** [A6] Agentic output can *fill gaps* (propose the driver, fetch the evidence) but never *promote* a package; promotion still requires the gates to pass deterministically, now claim-specific (D21-B + R1):

- citation coverage passed;
- **model-proposed** AWS/architecture claims backed by AWS Docs evidence (catalog-backed claims already grounded — R1);
- pricing claims backed by AWS Pricing evidence; pricing-ledger maturity met;
- no critical reviewer findings;
- diagrams rendered or missing views disclosed;
- assumptions visible;
- **procurement-ready** additionally requires exact rate bindings (`bound` **✓** [A2]) and confirmed quantities (`status="confirmed"` **✓** [A4b]); a model-proposed architecture is hard-capped below procurement until human-approved or pattern-backed (D21-F).

Branch 4's lesson holds: a polished package with no relevant AWS evidence is demo-ready, not workshop-ready. Agents do not change that arithmetic.

---

## 9. Invariants that never move

- Readiness/verdict computation, governance enforcement, headline-pricing safety.
- The manifest, the offline verifier, export verification semantics.
- The diagram compiler as the sole renderer of truth.
- Offline deterministic mode: agents off → today's Archway, full suite green, zero network. **✓** [A11]
- No agent mutates protected gates, manifests, pricing readiness, or compiler output.
- **Reproducibility:** pinned model + pinned prompt + same input → same proposal hashes; every agent call records model id, prompt hash, response hash, accept/reject decision (the D7/D15 quarantine pattern generalized). A Phase-0 invariant — Branch 4 proved output can be environment-dependent; agents widen that exposure.

---

## 10. Phasing

- **Phase 0 — foundation.** Orchestration schemas (`AgentRun`, `AgentTask`, `AgentProposal`, `AgentEvidenceRef`, `AgentDecision`, `AgentFinding`, `AgentRepairPlan`, `ArtifactCompletenessState`); the single `model_proposed` class + mapping table to existing provenance (§5); `raw/agent_runs.json` + `raw/agent_proposals.json` with model/prompt/response hashes and accept/reject logs; `ARCHWAY_ENABLE_AGENTIC_*` flags (default off). Plus the deterministic **repair planner** (lane 1).
- **Phase 1 — thin 10-scenario battery (lane 2), then research + use-case analyst.** No agent touches client-facing artifacts until the battery exists (D21-E).
- **Phase 2 — agentic pricing,** Lex first; every result `bound`/`scenario_assumed`/`ambiguous`/`not_estimated`; retire the generic placeholder (D21-D).
- **Phase 3 — narrative + reviewer agents,** evidence-bound rewrite validation, red-team findings before export.
- **Phase 4 — diagram planning,** compiler authority preserved, friendly missing-view ledger in the client pack.
- **Phase 5 — architecture candidate agent,** constrained typed proposals, mandatory critique + human-review gate.
- **Phase 6 — evaluation hardening,** battery to ~50 (Lex, Connect, SAP migration, EKS SaaS, IoT cold chain, insurance claims, public-sector permitting, pharma trial ops, airline disruption, media streaming, smart building, bank AML, retail personalization); per-lane hallucination, citation, pricing-label, reproducibility thresholds enforced.

---

## 11. Definition of done

- Any sane use case produces a complete package; unsupported cases produce a diagnostic/refusal package with a repair path — never a broken or halted artifact (§2).
- Every price is `bound`, `scenario_assumed`, `catalog_backed`/`heuristic`, or `not_estimated` — never a silent number (D21-D).
- Every AWS service/architecture claim has AWS Docs evidence or is marked `model_proposed`/assumption; every price has AWS Pricing evidence or is labeled (D21-B, R1).
- Mapped workloads *can* reach usage-ready when deterministic gates pass; novel workloads reach usage-ready-as-reviewed-candidate after human review and evidence grounding (R2). Being mapped is necessary, not sufficient.
- A model-proposed architecture is never procurement-ready without human approval or pattern-backing (D21-F).
- Client pack polished and readable; audit pack contains every trace and every provenance class.
- Model-off deterministic mode still works; full suite green.
- Same pinned model/prompt/input → reproducible proposal hashes.
- No agent mutates protected gates, manifests, pricing readiness, or compiler truth.
- The evaluation battery reports per-lane scores tagged `auto`/`human` (R3).

---

## 12. Open questions for final review

1. **Reproducibility of grounded output.** Live AWS evidence is network/time-dependent. Pin an evidence snapshot per run (like the SKU snapshot), accepting staleness, or accept statistical reproducibility with retrieval timestamps recorded?
2. **Procurement cap for model-proposed architecture.** Is a human-review gate sufficient for procurement-ready, or do we *permanently* cap model-proposed architectures at workshop-ready until pattern-backed?
3. **Cost/latency budget.** Multi-agent deep research turns a free, seconds-long dossier into a minutes-long, dollars-costing one. Per-dossier budget should be a gate, not a discovery — what is the ceiling, and does exceeding it downgrade to the deterministic baseline?
4. **Scenario default in the client pack.** When the agent proposes pilot/department/enterprise scenarios, which (if any) shows by default, and does showing one ever count toward `budgetary_range` framing?

---

## 13. Verified anchors (confirmed against the working tree 2026-06-13)

| Tag | Claim | Location |
|---|---|---|
| A1 | `DossierPricingEvidenceClass` (6 values) | `app/models/domain.py:194` |
| A2 | `bind_rate` statuses: bound/ambiguous/not_found/unsupported/unit_mismatch/missing_quantity | `app/services/sku_pricing/binding.py:17–22` |
| A3 | Heuristic engine generic nonzero default `(20,60,180,...)` for unmapped service | `app/services/pricing.py:100` |
| A4a | `AssumptionRecord.source` includes `scenario_profile` | `app/domain/source_of_truth.py:39` |
| A4b | `PricingDriverBinding.status: Literal["confirmed","assumed","missing","derived"]` | `app/domain/source_of_truth.py:62` |
| A4c | `ServiceUsageDimension` (aws_service_code, usage_name, unit, formula, required_rate_dimensions) | `app/domain/source_of_truth.py:66` |
| A5 | `pricing_driver_closure` consumes assumed/derived driver bindings (`:224`); `scenario_profile_used` sets `directional_allowed=True` — the D21-C mapping (`:245–256`); emitted as `directional_scenario_allowed` on the closure report (`:283`); field def `:72`. (`:323` is the unrelated procurement-fallback path, deliberately not cited here.) | `app/services/pricing_driver_closure.py:224, :245–256, :283` |
| A6 | `READINESS_TIERS` + `compute_readiness_tier` (returns `reasons`) | `app/services/customer_readiness.py:88, :120` |
| A7 | Branch-4 evidence gate is package-level "docs OR pricing" | `app/services/customer_readiness.py:166–167` |
| A8 | Diagram adapter rendering/fallback ledger (`view_rendering_ledger`) | `app/services/diagram_compiler_adapter.py:120` |
| A9 | Deterministic architecture critique (structural validation) | `app/services/architecture_critique.py:59` |
| A10a | `understanding_conflicts` emitted in research metadata | `app/services/research.py:326` |
| A10b | `canonical_facts` from source-truth pricing compiler, placed into pricing metadata, and emitted via export raw | `app/services/source_truth_pricing_compiler.py:95`, `app/services/source_truth_pricing_compiler.py:117`, `app/services/export_package.py:187` |
| A11 | `llm_provider` default `"deterministic"` | `app/core/config.py:121` |
| A12 | `ARCHWAY_ENABLE_*` flag convention (representative: `enable_aws_docs_mcp`) | `app/core/config.py:80` |
| A13 | Centralized research/evidence flow (`run_research`) | `app/services/research.py:39` |
| A14 | Deep use-case understanding (`DeepUseCaseUnderstandingService`) | `app/services/understanding/deep_use_case_understanding.py:70` |
| A15 | `pricing_filter_mapper` is hand-mapped (`_SERVICE_CODE_ALIASES` `:13`; lookup `:61`) | `app/services/pricing_filter_mapper.py:13, :61` |
| A16 | Deterministic reviewer mode — D20 (`build_reviewer_report`) | `app/services/reviewer_mode.py:499` |
| A17 | View planner (`plan_semantic_views`) | `app/services/view_planner.py:122` |

Decision-log context confirmed: max committed decision is **D20**, max known issue is **I16** (`docs/rc2/DECISIONS.md`, `docs/rc2/KNOWN_ISSUES.md`).

---

## 14. Sequencing

The next **era**, not the next **sprint**. The polish wave is now **merged to master** (all four branches: prose defects, artifact linter, client/audit pack split, readiness tiers + evidence gate — tip `942c446`). D21 lands only after the remaining prerequisites: linter strict-promotion completes its clean-run count, and platform hardening (durable jobs, auth/deployment) ships — agents on an in-memory job store with no eval battery is the fluent-incident path. D21 is paper; attack it now at zero code risk.

---

*Approved design candidate authored 2026-06-13 from DRAFT v3. All ✓ anchors verified at decision-freeze time (§13); → items are targets. Re-confirm anchors at implementation time — line numbers drift, and this document must never be the source of a claim the code no longer supports.*
