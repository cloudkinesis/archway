# Archway — Independent Code & Solution Review

**Reviewer:** Claude (Opus 4.8), independent read-only review
**Date:** 2026-06-07
**Scope:** `docs/code-review-pack/*` (read in full) cross-checked against the actual `app/` backend, `frontend/`, and the configured D2 compiler boundary.
**Constraint honored:** No code or docs were edited or deleted. This is a new, additive review file only.

---

## 1. Verdict in one paragraph

Archway is **substantially better engineered than most "AI architecture assistant" prototypes**, and — importantly — the documentation in `docs/code-review-pack` is **honest about its own limitations** rather than overselling. The system's core thesis ("be deterministic, separate facts from assumptions, never present directional pricing as procurement-ready, route all diagrams through the existing compiler") is **genuinely implemented in code**, not just asserted in docs. The strongest parts (tool governance, source-truth pricing ledger, headline-safety gating, diagram-compiler boundary) are real and defensible. The weakest parts are **structural** (a 2,190-line monolithic frontend, heavy domain logic spread across many modules, and large hardcoded pricing heuristic tables) and a small number of **concrete code defects**, the most notable being a broken regex pair that is silently masked by a duplicated extractor. Nothing I found rises to a security or trust-integrity breach. The honest summary: **the plumbing is real; the maturity is "directional, demo-capable, not procurement-ready," and the code says so itself.**

---

## 2. What Archway is and its intended uses

Archway is a **local-first AWS solution-architecture assistant**. A user submits a rough AI use case and Archway walks it through a deterministic phase pipeline:

1. **Synthesis** — interview, brief, readiness, assumptions ([app/services/synthesis.py](app/services/synthesis.py), [routes.py:147](app/api/routes.py:147)).
2. **Research** — evidence gathering (local policy + optional AWS Docs MCP / AWS Pricing MCP / Tavily), recommendations, competitor scan, citation coverage ([app/services/research.py](app/services/research.py)).
3. **Pricing checkpoint** — explicit driver closure, scenario profiles, or "proceed-without-headline" ([routes.py:248-318](app/api/routes.py:248)).
4. **Architecture** — deterministic POC + production specs from a pattern catalog, governance enrichment, critique, bounded repair ([app/services/architecture.py](app/services/architecture.py), [routes.py:321](app/api/routes.py:321)).
5. **Diagrams** — compiled **only** through the external Archway D2 compiler adapter ([app/services/diagram_compiler_adapter.py](app/services/diagram_compiler_adapter.py)).
6. **Diagnostics / Export** — golden convergence + a full dossier zip ([app/services/export_package.py](app/services/export_package.py)).

**Legitimate, well-supported uses today:**
- Turning a vague use case into a **structured, well-organized solution brief and research narrative** with explicit assumptions and citations.
- Producing **deterministic, reproducible POC/production architecture skeletons** and AWS service shortlists for a known set of workload families.
- Generating **directional, transparently-caveated cost ranges** for customer demos and internal scoping.
- Producing **diagrams via the real compiler** and a **single exportable dossier** for review.

**Uses it is explicitly NOT ready for (and says so):**
- **Procurement-grade pricing** for arbitrary workloads. Only 4 families have the source-truth pricing path, and even those almost always remain directional unless live AWS rate binding succeeds.
- **Autonomous architecture correction.** Repair is bounded and pattern-specific.
- **Novel domains** outside the hand-coded classifier/pattern-catalog families.

---

## 3. What is genuinely well-built (strengths I verified)

### 3.1 Tool governance is real, not cosmetic
[app/tooling/registry.py](app/tooling/registry.py) hard-blocks write-capable tools (`assert_allowed` raises on `entry.write_capable`, [registry.py:39](app/tooling/registry.py:39)), and **every registered tool is `write_capable=False, read_only=True`** by construction. Tools are **phase-scoped** (`allowed_phases`) and **audit-logged** on every allow. The README claim "Tool calls are allowlisted, phase-scoped, and read-only by default" is **accurate**.

### 3.2 Artifact path safety is correctly implemented
[app/services/artifacts.py](app/services/artifacts.py) rejects absolute paths and `..` traversal in both `resolve` ([artifacts.py:36](app/services/artifacts.py:36)) and `_safe_path` ([artifacts.py:53](app/services/artifacts.py:53)), sanitizes filenames, and validates that resolved paths stay under the session root. The artifact-serving route ([routes.py:523](app/api/routes.py:523)) goes through `resolve`. This is the right boundary.

### 3.3 The source-truth pricing compiler is the crown jewel
[app/services/source_truth_pricing_compiler.py](app/services/source_truth_pricing_compiler.py) builds a **canonical facts ledger, assumption ledger, driver bindings, service usage dimensions, AWS rate bindings, and a pricing ledger with evidence classes** (`sku_tier_backed` / `price_catalog_referenced` / `heuristic` / `not_estimated`). Crucially:
- For **unsupported families** it disables itself and emits a **critical "non-zero pricing without ledger"** finding and withholds the headline ([compiler.py:39-62](app/services/source_truth_pricing_compiler.py:39)).
- It **overwrites** heuristic line totals with rate-bound totals only when binding is `bound`, and **zeroes out `not_estimated` lines** ([compiler.py:607-626](app/services/source_truth_pricing_compiler.py:607)).
- Sanity checks catch genuinely dangerous mistakes: a confirmed fact appearing as "unknown," a vague line item that still carries a dollar total, edge-compute priced in egress units, hidden MediaLive channel assumptions ([compiler.py:472-499](app/services/source_truth_pricing_compiler.py:472)).

This is **unusually disciplined** for this product category.

### 3.4 Rate binding is honest about ambiguity
[app/services/aws_rate_binding_engine.py](app/services/aws_rate_binding_engine.py) calls the real AWS Pricing API (`boto3 pricing.get_products`) and **only returns `bound` when exactly one OnDemand dimension matches** ([rate_binding_engine.py:70-76](app/services/aws_rate_binding_engine.py:70)). Multiple matches → `ambiguous` and the candidate rate is shown **but not used for the total**. This is the correct, non-deceptive behavior.

### 3.5 Diagram-compiler boundary is respected
[diagram_compiler_adapter.py:47-66](app/services/diagram_compiler_adapter.py:47) imports and calls the **external** `archway_diagram_compiler.compile_architecture`. There is no internal shortcut renderer. I confirmed the compiler package exists and is importable at the configured path. Timeout + concurrency control and missing/degraded-view tracking are present ([diagram_compiler_adapter.py:131-144](app/services/diagram_compiler_adapter.py:131), [:227-262](app/services/diagram_compiler_adapter.py:227)).

### 3.6 Governance enrichment is typed and structural
[app/services/governance_controls.py](app/services/governance_controls.py) classifies effectful flows, attaches typed `GovernanceControl`s **linked to governed flow ids**, and — when a flow can't be governed — **downgrades it to "recommendation / queue for review"** ([governance_controls.py:227-239](app/services/governance_controls.py:227)). The diagram gate blocks on `write_without_governance` critical issues ([architecture_revisions.py:76-82](app/services/architecture_revisions.py:76)). This matches the docs' "typed, not brittle string-only" intent (though see §7 for a caveat).

### 3.7 Secrets hygiene is correct
`.env` and `.archway/` are git-ignored and **not tracked** (verified). The exception handler returns generic errors outside development ([main.py:27-31](app/main.py:27)). Security headers/CSP, request-size limit, and rate limiting are wired ([app/security/policy.py](app/security/policy.py)).

---

## 4. Concrete code-level findings

These are specific, verifiable issues. None are catastrophic; they range from a real bug to fail-open defaults.

### 4.1 Broken regex pair (real bug, currently masked) — MEDIUM
[app/services/use_case_profile.py:408-409](app/services/use_case_profile.py:408) use **double-backslashes inside raw strings**:

```python
r"...(?:every\\s+)?(?P<value>\\d+(?:\\.\\d+)?)\\s+minutes?"   # refresh_cadence_minutes
r"(?P<value>\\d[\\d,]*)\\s+(?:scheduled\\s+)?surgeries..."     # scheduled_surgeries_per_day
```

In a raw string `\\d` is backslash-backslash-d, so the regex tries to match a **literal backslash**, never a digit. **These two patterns can never match real input.** Every other pattern in the same table correctly uses single `\d` (e.g. [use_case_profile.py:396](app/services/use_case_profile.py:396)).

**Why it's only MEDIUM:** the pricing engine reads the *structured* metrics path first (`_structured_metric(profile, "business_targets", "refresh_cadence_minutes")`, [pricing.py:150](app/services/pricing.py:150)), and the **structured extractor has the correct single-backslash patterns** ([metric_extractor.py:70-71](app/services/metric_extractor.py:70)). So the two healthcare drivers are still captured via that path; the broken copy in `profile.metrics` is a silent dead fallback. **The bug is real, but its blast radius is contained** — which is itself the warning sign (see 4.2).

### 4.2 Duplicated, drift-prone metric extraction — MEDIUM (maintainability)
There are **two parallel regex extraction tables** that must stay in sync: `_extract_metrics` in [use_case_profile.py:388](app/services/use_case_profile.py:388) and `extract_metrics` in [metric_extractor.py:33](app/services/metric_extractor.py:33). They share ~20 near-identical patterns. One copy has **already silently drifted into a broken state** (4.1). This is a textbook duplication hazard: the system works only because the *other* copy happens to be the one pricing reads first.

### 4.3 Headline-safety default is fail-OPEN — MEDIUM (trust)
[research_view_model.py:361](app/services/research_view_model.py:361):
```python
headline_safe = bool(metadata.get("pricing_can_be_displayed_as_headline", True)) and phase == "poc"
```
The default when the key is **missing** is `True`. The trust-critical posture (per docs 06) is that pricing should be withheld unless proven safe — i.e. it should **fail closed** (`default=False`). In practice the source-truth compiler always sets this key, so today it's safe; but any future pricing path that forgets to set the flag would present an unproven estimate as a confident headline. Same fail-open default appears at [research_view_model.py:443](app/services/research_view_model.py:443). Recommend defaulting to `False`.

### 4.4 Hardcoded heuristic pricing catalog is the real "directional" engine — EXPECTED, but be explicit
The bulk of pricing is a large hardcoded table of `(low, expected, high, basis, scale)` tuples per service ([pricing.py:514-633](app/services/pricing.py:514)) multiplied by workload scale factors. Every line item is stamped `procurement_ready: False` at creation ([pricing.py:113](app/services/pricing.py:113)). These numbers are **plausible engineering guesses, not AWS-derived rates**. The docs acknowledge this, and the source-truth layer + headline gating prevent it from being *presented* as exact. This is acceptable **only because** the honesty machinery around it works. The risk is if anyone reads `expected_monthly_usd` directly from the artifact without the metadata context — the number looks precise (`round(...,2)`) but is heuristic. Consider widening low/high spreads or labeling the JSON field itself.

### 4.5 `_read_json` uses `__import__("json")` inline — LOW (style)
[routes.py:579](app/api/routes.py:579), [:590](app/api/routes.py:590), [:598](app/api/routes.py:598) and the convergence orchestrator use `__import__("json")` instead of a top-level `import json`. Harmless but odd; suggests these helpers grew ad hoc. Minor readability cost.

### 4.6 Procurement-ready is effectively unreachable for most lines — DESIGN NOTE
`procurement_ready`/`headline_safe` require **every** line item to be `sku_tier_backed` ([compiler.py:466-468](app/services/source_truth_pricing_compiler.py:466)). But `_matching_dimensions` only matches via a few special cases (CloudFront/edge/MediaLive) or when `required_rate_dimensions` is non-empty — and the usage-dimension builders pass `required_rate_dimensions={}` for media ([compiler.py:380-387](app/services/source_truth_pricing_compiler.py:380)). Net effect: even with AWS credentials, **most line items stay heuristic, so a family almost never reaches procurement-ready.** This is *honest* (it won't fake readiness) but means the top rung of the "pricing readiness ladder" is largely aspirational in practice. Worth stating plainly to stakeholders.

---

## 5. Pricing system assessment (the highest-risk area)

**Honest grade: B+ on discipline, C on coverage.**

- The **separation of facts / assumptions / derived values / rate bindings** is excellent and traceable.
- The **headline-safety gating** genuinely prevents the worst failure mode (presenting a guess as a quote). Live media and healthcare are hard-forced to `headline_safe=False` ([pricing.py:828-833](app/services/pricing.py:828)).
- **Coverage is narrow:** only `HEALTHCARE_OPERATIONS_SCHEDULING`, `PAYMENT_FRAUD_SCORING`, `CAPITAL_MARKETS_RISK_ENGINE`, `LIVE_MEDIA_STREAMING` get the source-truth path ([compiler.py:28-33](app/services/source_truth_pricing_compiler.py:28)). Everything else is "legacy directional" with the headline withheld — safe, but a lot of workloads land there.
- **The actual dollar figures are heuristic** (§4.4). The system is built so that this is *disclosed* rather than *hidden*, which is the right call, but stakeholders should not interpret any `expected_monthly_usd` as AWS-backed unless `evidence_class == sku_tier_backed`.

Bottom line: the pricing system is **built the right way** (honesty-first), but is **directional by nature**. It should be sold as "transparent scoping," never "quote."

---

## 6. Domain classification & drift

The classifier ([use_case_profile.py:229-352](app/services/use_case_profile.py:229)) is a **hand-tuned keyword scoring system** with explicit cross-domain suppression (e.g. media zeroes out IoT/CV/fraud; healthcare zeroes industrial/field-service; telecom HBase/HDFS boosts big-data and suppresses IoT). The healthcare reserved-vocabulary lint is correctly **scoped to healthcare output only** ([pricing.py:1011-1025](app/services/pricing.py:1011)).

**Assessment:** This works for the curated scenario set and the anti-drift tests target exactly these cases. But the approach is **inherently brittle**: it's a growing pile of `if term in lower` rules with manual score nudging. The docs candidly call this out as "not a clean plugin interface." Adding a new domain risks regressions in the suppression rules. This is a **scalability/maintainability gap, not a correctness bug** today.

---

## 7. Security & governance

Strong overall (see §3.1, §3.2, §3.7). Two caveats:

- **Effectful-flow detection is still partly string-based.** `_action_type` matches `classification`/`label` substrings against `EFFECTFUL_ACTION_MARKERS` ([governance_controls.py:151-158](app/services/governance_controls.py:151)). The *controls* are typed and structural (good), but the *detection* of "this flow is effectful" depends on labels/classification text being present and well-formed. A mislabeled write flow could escape governance. The docs flag this as a thing to review — it remains a genuine soft spot.
- **Rate limiting is per-process in-memory** ([policy.py:34-50](app/security/policy.py:34)) and keyed on `request.client.host`. Fine for local single-user; not meaningful behind a proxy or multi-instance. Acceptable for the stated local-first scope.

No authentication exists on the API (local-first assumption). That's consistent with the product framing but means **this must never be exposed to a network** without adding auth.

---

## 8. Diagram compiler integration

Correctly bounded (§3.5). Residual risks are the ones the docs already name: the compiler path is environment-specific (default hardcodes `/Users/arnab/...` in [config.py:50](app/core/config.py:50)), and semantic→compiler view mapping can drift. The adapter does the right thing by recording `missing_requested_views` with reasons rather than silently dropping them ([diagram_compiler_adapter.py:227](app/services/diagram_compiler_adapter.py:227)) and separating icon-embedding metrics from layout QA ([:296-332](app/services/diagram_compiler_adapter.py:296)).

---

## 9. Repair & convergence

[golden_convergence_orchestrator.py](app/services/convergence/golden_convergence_orchestrator.py) is genuinely wired into export ([export_package.py:40-44](app/services/export_package.py:40)), collects findings from understanding/pricing/diagrams/dossier/readiness/architecture, applies bounded repairs (max 2 iterations), and records `repairs_applied`. The honesty point from the docs is respected: it records `repair_plan` separately and final status reflects unresolved findings ([_final_status](app/services/convergence/golden_convergence_orchestrator.py:353)). It is, as advertised, a **bounded safety net, not an autonomous fixer** — many `RepairAction` types map to no real executor.

---

## 10. Maintainability / structural gaps

- **Frontend monolith:** [frontend/src/components/App.tsx](frontend/src/components/App.tsx) is **2,190 lines of 2,681 total** — i.e. ~82% of the frontend lives in one file. The docs admit this. It's a real maintainability and review-surface risk, though not a functional defect.
- **Large backend service files:** `pricing.py` (1,095), `deep_dossier.py` (1,014), `pattern_catalog.py` (854), `research_view_model.py` (840). Lots of domain knowledge encoded as long conditional ladders. Comprehensible but high-friction to extend safely.
- **Domain logic is spread across ~8 modules** (classifier, synthesis, pricing, pattern catalog, research view model, dossier, governance, repairer). Adding a domain means touching all of them — exactly the leakage surface the anti-drift tests exist to guard.

---

## 11. Docs-vs-code accuracy check

The `code-review-pack` is **accurate and refreshingly non-promotional.** Spot-checks:

| Doc claim | Code reality | Verdict |
|---|---|---|
| Tools allowlisted, phase-scoped, read-only | [registry.py](app/tooling/registry.py) enforces all three | ✅ Accurate |
| Artifact IDs path-safe, reject `..`/absolute | [artifacts.py:36-65](app/services/artifacts.py:36) | ✅ Accurate |
| Diagrams only via external D2 compiler | [diagram_compiler_adapter.py:47](app/services/diagram_compiler_adapter.py:47) | ✅ Accurate |
| Pricing honest about maturity; headline gated | source-truth compiler + closure | ✅ Accurate (with §4.3 fail-open nit) |
| "Not all estimates are procurement-ready" | Confirmed; most never reach it (§4.6) | ✅ Accurate, arguably understated |
| Frontend is a large monolith | 2,190-line App.tsx | ✅ Accurate |
| Repair is bounded, not universal | max 2 iters, partial executors | ✅ Accurate |
| Domain packs not a clean interface | Spread across 8 modules | ✅ Accurate |

The docs do **not** mention the 4.1 regex bug (they wouldn't — it's masked). Otherwise the docs are a trustworthy map of the code.

---

## 12. Prioritized recommendations

**High value, low risk:**
1. Fix [use_case_profile.py:408-409](app/services/use_case_profile.py:408) (single backslashes) **and** collapse the two extractors (§4.2) into one shared table to kill the drift hazard.
2. Change headline-safety defaults to **fail-closed** ([research_view_model.py:361](app/services/research_view_model.py:361) and [:443](app/services/research_view_model.py:443)): `metadata.get("pricing_can_be_displayed_as_headline", False)`.

**Medium term:**
3. Add a tiny regression test that asserts every persisted `expected_monthly_usd` line is either `sku_tier_backed` or has `procurement_ready=False` — guards §4.4/§4.6 from future presentation drift.
4. Begin extracting the frontend phase views out of `App.tsx` (start with `ResearchView`/`PricingResearchTab`) to shrink the review surface.
5. Strengthen effectful-flow detection (§7) so governance keys off a structured flow attribute rather than label substrings.

**Strategic:**
6. Refactor domain logic toward a single "domain pack" interface (classifier + pattern catalog + pricing family + reserved vocab in one registered unit) before adding the next domain. The anti-drift tests are a good safety net for this refactor.
7. Decide and document explicitly whether "procurement-ready" pricing is a real target or should be removed from the ladder until live rate binding is reliably achievable (§4.6).

---

## 13. Final assessment

**Is Archway being built the right way? Largely, yes.** The architecture choices that matter for *trust* — deterministic core, evidence discipline, headline-safety gating, read-only allowlisted tools, real compiler boundary, honest self-documentation — are implemented in code, not merely claimed. The gaps are real but bounded: one masked regex bug, a fail-open default in the presentation layer, narrow pricing/domain coverage, and significant monolith/duplication debt that will slow safe extension. None of these undermine the product's central honesty guarantees today.

The single most important thing the team has gotten right is the **refusal to fake precision**: directional pricing stays directional, ungoverned writes get downgraded, dropped diagram views get reported. That discipline is rare and is the foundation everything else can be built on. The main thing to watch is **structural debt outrunning the test net** as more domains and pricing families are added.
