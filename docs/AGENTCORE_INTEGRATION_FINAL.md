# Archway × AgentCore — Final Integration Plan

Status: **final decision document** (uncommitted). Supersedes the working analysis in
[`AGENTCORE_FIT_ASSESSMENT.md`](./AGENTCORE_FIT_ASSESSMENT.md), which remains the
long-form, code-grounded rationale.
Audience: Archway owner, deciding what to bake in for a Re:Invent-2026-grade story.
Method: grounded in Archway code (file:line seams) and three AWS sources — the
[AgentCore release notes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html),
the [June 17 2026 "broader knowledge and continuous learning" blog](https://aws.amazon.com/blogs/machine-learning/new-in-amazon-bedrock-agentcore-build-agents-with-broader-knowledge-and-continuous-learning/),
and the AgentCore service docs. Where sources disagree, both are recorded.

---

## 0. The one constraint everything is judged against

> **The LLM proposes. Deterministic code validates. The catalog is a reference, never
> a judge.** No AgentCore service — including the new Managed Knowledge Base — may
> become an authority over architecture truth, pricing truth, or readiness. The
> deterministic compiler (`source_truth_pricing_compiler.py`, `canonical_intent.py`,
> the convergence gates) stays the final authority (INV-1).

AgentCore's role is to **observe, evaluate, learn from, feed evidence to, and govern**
Archway's agents — never to decide output truth.

---

## 1. What changed after reading the blog (delta from the working doc)

The blog and release notes together move four things:

1. **Managed Knowledge Base becomes a first-class item.** Previously absent. It is the
   AWS-native, richer successor to Archway's `local_policy` pack + AWS Docs MCP, and it
   belongs in the evidence layer — feeding **evidence, not truth**.
2. **Failure / Intent / Trajectory Insights moves up** to #3, right after Observability
   and Evaluations. It is not a footnote; it targets Archway's defining failure mode.
3. **Web Search is confirmed real and GA** — with a source conflict on integration
   shape (see §3.4) that must be resolved in-account before wiring.
4. **Harness GA is acknowledged but still deferred** — it is a migration, not a
   quality gain, while jobs/exports/diagrams/SQLite are local.

Everything in the working doc's code-grounding (Archway already has *local analogs* —
not equivalents — of tool-policy, telemetry, and offline evals) still stands.

---

## 2. Final priority and branch order

| # | Branch | Class | Demo risk | Why |
|---|---|---|---|---|
| 1 | `feature/agentcore-observability-spine` | Out-of-band | None | Stitch + trace; prerequisite for Insights |
| 2 | `feature/agentcore-evaluations-user-simulation` | Out-of-band | None | Mirror batteries + User Simulation + Batch Eval + Ground-Truth assertions |
| 3 | `feature/agentcore-failure-intent-trajectory-insights` | Out-of-band | None | Detect silent behavioral failures across runs |
| 4 | `feature/agentcore-knowledge-and-evidence-provider` | In-band | Medium | `EvidenceProvider` over Tavily/AWS Docs/Pricing + **Web Search** + **Managed KB** |
| 5 | `feature/agentcore-gateway-policy-guardrails-shadow` | In-band | High | Gateway/Policy/Guardrails in **shadow** mode; `ToolPolicyEngine` stays the real gate |
| 6 | Later, separate branches | Mixed | — | Code Interpreter advisory verifier; Memory preferences-only; Harness/Runtime exploration |

Organizing axis (unchanged): **out-of-band first** (#1–#3, no live-path risk), then
**in-band, flag-gated, shadow-before-block** (#4–#5).

---

## 3. The items, grounded

### 3.1 Observability — branch #1

**AWS.** AgentCore Observability: OTEL/X-Ray traces and trajectory views; one-click
enablement for Runtime/Memory/Gateway/Tools; put-to-get trace latency under 10s.

**Archway seam + the real work.** Archway produces the data but in **three separate
streams**, not one trace:
- LLM calls — `LLMCallTelemetry` / `LLMTaskType` ([`base.py:11,78`](../app/services/llm/base.py)),
  in-memory store ([`telemetry.py:8`](../app/services/llm/telemetry.py)), exported to
  `raw/llm_call_telemetry.json` ([`export_package.py:256`](../app/services/export_package.py)).
- Tool calls — separate audit events (`tool_policy_allowed` [`registry.py:43`](../app/tooling/registry.py);
  `tavily_search_*` [`tavily.py:76`](../app/services/tavily.py)).
- Job / gate / export transitions — separate audit events from
  [`jobs.py`](../app/services/jobs.py) and the convergence gates.

The branch's actual work is **stitching these into one correlated trace** (by
`session_id` + span hierarchy), then OTEL-exporting. Additive, out-of-band, no
behavior change. Export failure must never fail a job.

**Verdict.** First. It is the prerequisite for Insights (#3), which consumes traces.

---

### 3.2 Evaluations + User Simulation + Batch Eval — branch #2

**AWS (GA, March–June 2026).** 13 built-in evaluators; **code-based (Lambda)** custom
evaluators; **Ground Truth** against reference answers, behavioral assertions, and
**expected tool-execution sequences**; **Batch Evaluation** (replay a dataset, compare
pre/post, catch regressions pre-rollout); **User Simulation** ("realistic multi-turn
conversations using LLM-backed actors to reveal behaviors beyond scripted tests").

**Archway seam.** `run_convergence_eval()` already returns per-scenario
`checks: {name: bool}` over never-coded scenarios, offline
([`scripts/d25_convergence_eval_battery.py`](../scripts/d25_convergence_eval_battery.py));
same shape in `rc2_validate.py`, `d21/d23_eval_battery.py`. Mapping:
- boolean `checks` → **code-based evaluators**;
- "must NOT pick streaming topology" / "events must be graph-justified" → **behavioral
  assertions**;
- expected service/topology set → **expected tool/topology sequence**.

**User Simulation is the standout.** It automates exactly the manual browser user-sims
you keep running on novel use cases (food delivery, reverse logistics, library
manuscripts, permits, disaster relief) — turning your hardest question (*does this
generalize to unseen use cases?*) into an automated, scaled battery.

**Verdict.** Co-first with Observability. Offline/CI only; AgentCore mirrors the
batteries, the **local batteries stay authoritative**.

---

### 3.3 Failure / Intent / Trajectory Insights — branch #3 (moved up)

**AWS (Preview).** The blog is explicit and on-theme: *"The most dangerous agent
failures aren't the ones that throw errors… an agent that confirms an order
modification it never executed… produces no error signals."*
- **Failure insights** — "discover recurring failure patterns, including the silent
  behavioral failures that produce no error signal, explain the root cause… rank them
  by how widespread they are."
- **Intent insights** — "cluster requests by what users were actually trying to do."
- **Trajectory insights** — "group the paths your agents take through a task… spot
  common patterns and outliers."

**Why this is near the top for Archway specifically.** Archway's entire history is
fighting *silent success with the wrong answer*: the categorization treadmill, borrowed
telemetry topology, the food-delivery→industrial-IoT misclassification with
1.03-trillion-event quantities. None threw an error. The D27–D38 gates catch *instances*
at output time; Insights surfaces the *patterns* across many runs so you fix the cause.
**Intent insights** doubles as a check on Archway's core classification (domain /
workload-family) — clustering "what the user actually wanted" is an independent read on
whether the four-layer classifier is right.

**Verdict.** #3, immediately after Observability + Evaluations (it consumes their
output). Out-of-band, low risk, highest thematic fit.

---

### 3.4 Knowledge + Evidence Provider — branch #4

This branch carries **two** AgentCore evidence sources behind one interface.

**The seam (already exists).** Search/evidence already converges on a single type:
`EvidenceItem` (`tavily_response_to_evidence` [`tavily.py:121`](../app/services/tavily.py);
AWS Docs/Pricing in [`aws_research_tools.py`](../app/services/aws_research_tools.py)).
The interface is small: `EvidenceProvider.search(query, session_id, purpose) ->
list[EvidenceItem]`, with deterministic fallback on any provider error.

**(a) AgentCore Web Search — confirmed GA, integration shape must be verified.**
- The **blog** confirms it: built on Amazon's search infrastructure, keeps queries
  "within your AWS security and compliance boundary, with no extra vendor to onboard."
  The blog does **not** describe a Gateway/MCP shape.
- The **release notes** add: "exposed as a built-in connector target on AgentCore
  gateway using the Model Context Protocol (MCP)," returning snippets, source URLs,
  titles, and **publication dates**.
- **Resolution:** treat the Gateway/MCP coupling as AWS-stated (release notes) but
  **verify in the target account/docs before wiring.** *If Gateway-backed, Web Search
  lands with branch #5; if a direct tool/API is available, it can be an
  `EvidenceProvider` here.* The returned publication date maps cleanly onto Archway's
  citation-freshness needs; zero-egress is a strong enterprise talking point.

**(b) AgentCore Managed Knowledge Base — the biggest addition (GA).**
- **AWS.** Connect unstructured sources (S3, SharePoint, Confluence, Google Drive,
  OneDrive, internal wikis); AgentCore manages the vector store, embeddings, and
  re-ranking. The **agentic retriever** "plans queries across your knowledge bases,
  connects related concepts across documents, evaluates intermediate results, and
  re-ranks before answering" — beyond chunk-matching RAG. Agents query it through the
  gateway.
- **For Archway**, KB becomes the AWS-native, far richer successor to the
  `local_policy` "Local AWS Architecture Policy Pack" ([`registry.py:56`](../app/tooling/registry.py))
  and AWS Docs MCP. Curate into it: AWS Well-Architected guidance, AWS architecture
  patterns, known anti-patterns, and — when deployed for a customer — that customer's
  private architecture context. Retrieval returns **`EvidenceItem`s** the research
  phase cites.

**Guardrail — KB feeds evidence, never truth (this is load-bearing).** Two specific
risks, both flagged by Archway's standing review lens (D23 inversion: the catalog
must not become a judge):
- **Do not put "Archway's accepted decisions" into a KB the agent treats as
  authority.** That is the categorization treadmill reborn as retrieval — a curated doc
  silently deciding topology. KB content enters only as cited `EvidenceItem`s that the
  deterministic gates still weigh and can override.
- **Do not put "approved pricing assumptions" into KB as a pricing source.** Pricing
  authority stays with `source_truth_pricing_compiler.py` + authoritative rate binding.
  A KB document must never become a rate or a quantity. KB may *inform* the research
  narrative; it may not *set a price*.

**Verdict.** Adopt as the evidence layer. Managed KB is the highest-value *new*
capability for dossier quality — but only behind the `EvidenceProvider` interface and
the evidence-not-truth firewall.

---

### 3.5 Gateway + Policy + Guardrails — branch #5 (shadow first)

**AWS.** Gateway: managed MCP-compatible tool server (OpenAPI/Smithy/Lambda + **HTTP
passthrough** targets), ingress+egress auth, interceptors, CloudTrail. Policy
(GA): centralized fine-grained agent↔tool control. **Guardrails in Policy (GA):**
*"evaluates every agent action for prompt injection… harmful content… sensitive data
exposure. These checks run at the gateway layer, outside the agent's code, where the
agent can't see them… can't reason around them."*

**Archway seam (the crux).** Archway already has the *local analog*:
`ToolPolicyEngine.assert_allowed(tool_id, phase, payload)` ([`registry.py:33`](../app/tooling/registry.py))
denies unregistered/disabled/write-capable/out-of-phase tools and audits allows;
`validate_mcp_endpoint_url` ([`mcp_security.py:86`](../app/services/mcp_security.py)) is
the fail-closed egress credential gate. AgentCore does **not** add a missing capability;
it **externalizes** this to AWS-managed, CloudTrail-audited, Guardrails-screened
infrastructure.

**Two release-note items that improve the trade.**
- **HTTP passthrough** lets Archway *front* the existing Tavily/AWS Docs/Pricing
  endpoints without rewriting them as native MCP targets — lowering adoption cost.
- **Guardrails-in-Policy** is the concrete, out-of-agent-code mechanism for "no PII to
  external search," enforced where the model can't reason around it.

**Discipline (non-negotiable).** *AgentCore Policy shadows Archway's `ToolPolicyEngine`
first; Archway remains the real gate until shadow mismatch rate is zero and fallback is
proven.* Order: shadow/log-only → emit `raw/agentcore_policy_decisions.json` → graduate
one read-only path (AWS Docs or pricing reference). Keep `ToolPolicyEngine` as the
in-process backstop indefinitely. Policy governs **tool access**, never output truth.

**Verdict.** High value, staged, **augments not replaces**. Highest in-band risk →
last of the active branches → shadow before block.

---

### 3.6 Deferred / later — branch #6 and beyond

- **Code Interpreter** — later; **strictly advisory verifier** only. Pricing math is
  already single-authority in `source_truth_pricing_compiler.py` (INV-1); Code
  Interpreter may emit a *finding* ("this total looks absurd"), never a number, or it
  re-creates dual authority and the number treadmill.
- **Memory** — later; **preferences only**. Cross-session memory that nudges
  classification/topology is the treadmill at session scope. The firewall is now
  *enforceable by config*: **metadata filtering + resource-based policies** scope a
  memory to an `org_preferences` namespace and deny everything else. Never facts,
  quantities, or topology.
- **Harness (GA) / Runtime** — **defer.** Attractive (built-in memory, unified
  observability, Step Functions orchestration, model-swap mid-session), but Archway has
  in-memory jobs ([`jobs.py:19`](../app/services/jobs.py)), local artifacts, SQLite, and
  a UI workflow. Adopting Harness now is an infrastructure migration, not a quality
  gain, and the single-worker constraint is invisible in a controlled demo. Revisit for
  isolated agent lanes after demo quality is stable.
- **Payments** — **no.** Irrelevant to architecture dossiers; adds risk, zero quality.
- **Registry / GovCloud / SOC·ISO·CSA STAR** — narrative talking points only; no code
  impact.

---

## 4. Non-regression gates for every branch

Each must be proven by test before merge (the protection against "ruining Archway"):

1. **Flag off ⇒ byte-equivalent output** — same discipline as `enable_sku_pricing_pilot`
   et al. ([`config.py`](../app/core/config.py)).
2. **Flag off ⇒ no new network calls** — no AgentCore endpoint contacted when disabled.
3. **Trace/insight/eval export failure cannot fail a session** — fire-and-forget; logged,
   never propagated to a job.
4. **Policy shadow mismatch is recorded, not silently ignored** — written to
   `raw/agentcore_policy_decisions.json`; the deterministic engine still governs.
5. **No AgentCore service changes architecture / pricing / readiness truth** — owned by
   the deterministic compiler and gates (INV-1). Specifically: **Managed KB feeds cited
   `EvidenceItem`s only; it never sets a topology, a rate, or a quantity.**

---

## 5. The Re:Invent narrative

Not "Archway uses AgentCore" (a feature checklist). The defensible story — true in
spirit today because the gates already exist, and made *visible and AWS-native* by
AgentCore:

> Archway is an agentic AWS architecture compiler. AgentCore gives its agents **live
> web and curated organizational knowledge**, **traces every reasoning and tool step**,
> **evaluates behavior against simulated users**, **detects silent failures across
> sessions**, and **enforces deterministic tool-access policy outside the model** —
> while a deterministic Archway compiler remains the final authority and **refuses to
> make a customer-facing claim it cannot defend.**

The refusal is the differentiator. AgentCore makes it observable, evaluable, and
governed.

---

## 6. Honest limits

- **In-band creep.** Web Search, Managed KB query, Gateway/Policy, and Code Interpreter
  all sit in the live path. Each is an on-stage failure mode. Hold the
  out-of-band-first / shadow-before-block line.
- **KB as silent authority** is the subtlest new risk. The evidence-not-truth firewall
  (§3.4, gate #5) is mandatory, not optional — especially for pricing.
- **Web Search integration shape is unresolved** between blog and release notes; verify
  in-account before committing it to branch #4 vs #5.
- **Dual authority** (Code Interpreter, Memory) remains the standing threat to INV-1;
  the firewalls in §3.6 are conditions of adoption, not suggestions.

---

## Appendix: claims-to-code index

| Claim | Evidence |
|---|---|
| Per-step LLM telemetry exists, exported | [`base.py:11,78`](../app/services/llm/base.py); [`export_package.py:256`](../app/services/export_package.py) |
| Three separate observability streams (not one trace) | telemetry vs `registry.py:43` vs `jobs.py` audit events |
| Homegrown per-tool/per-phase policy (local analog of Gateway/Policy) | `ToolPolicyEngine.assert_allowed` — [`registry.py:33`](../app/tooling/registry.py) |
| Fail-closed egress credential trust | `validate_mcp_endpoint_url` — [`mcp_security.py:86`](../app/services/mcp_security.py) |
| Evidence converges on `EvidenceItem` (KB/Web Search slot here) | `tavily_response_to_evidence` — [`tavily.py:121`](../app/services/tavily.py) |
| Local curated-knowledge pack KB would succeed | `local_policy` "Local AWS Architecture Policy Pack" — [`registry.py:56`](../app/tooling/registry.py) |
| Offline eval batteries return deterministic pass/fail | `run_convergence_eval` — [`scripts/d25_convergence_eval_battery.py`](../scripts/d25_convergence_eval_battery.py) |
| Jobs in-memory single-process (Harness defer) | `JobManager` — [`jobs.py:19`](../app/services/jobs.py) |
| Pricing single authority (KB/Code-Interpreter must not breach) | `source_truth_pricing_compiler.py` |
| Flag-off = byte-equivalent precedent | `enable_sku_pricing_pilot` — [`config.py`](../app/core/config.py) |
