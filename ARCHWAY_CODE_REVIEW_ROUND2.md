# Archway — Deep Code Review, Round 2 (line-by-line pass)

**Reviewer:** Claude (Opus 4.8), read-only. **Date:** 2026-06-08.
**Method:** Second, deeper pass focused on code paths not fully traced in round 1 — concurrency (job manager), audit/secrets, the SSRF/URL-allowlist surface, MCP transport, the synthesis interview engine, architecture revision lifecycle, customer-readiness gating, and the frontend client. Nothing was edited or deleted.

This file lists **new** findings. The round-1 findings (regex `\\d` bug, duplicated extractors, fail-open headline default, heuristic pricing, monolithic frontend) still stand — see `ARCHWAY_SOLUTION_REVIEW.md`.

---

## A. Correctness bugs (new)

### A1. Re-generating architecture is a silent no-op — HIGH
`generate_architecture` ([routes.py:344](app/api/routes.py:344)) does all the expensive work (plan → governance → critique → repair) and then persists via:

```python
revision = architecture_revisions.initialize(session_id, specs)
```

But `initialize` ([architecture_revisions.py:20-24](app/services/architecture_revisions.py:20)) **returns the last existing revision and ignores the new specs** if any revision already exists:

```python
def initialize(self, session_id, specs, reason=...):
    revisions = self.list(session_id)
    if revisions:
        return revisions[-1]          # <-- new specs discarded, specs.json NOT rewritten
    return self._append(session_id, specs, reason)
```

**Consequence:** the first generation works; **every subsequent call to `/architecture/generate` throws away the freshly computed architecture** and leaves the old `specs.json`/revision in place. The job still reports success and returns `"architecture/specs.json"`, so the UI shows "done" while nothing changed. The diagram phase then compiles stale specs. The only way to change architecture after the first run is the separate `/architecture/regenerate` or PATCH endpoints. This is a genuine state bug, not just a naming issue.

**Fix direction:** either make `generate_architecture` call a force/append path, or have `initialize` detect that specs differ and append a new revision.

### A2. "Regenerate" doesn't actually regenerate — MEDIUM
`regenerate_from_active` ([architecture_revisions.py:54-61](app/services/architecture_revisions.py:54)) deep-copies the current specs and sets `metadata["regenerated_from_user_edits"] = True` — it does **not** re-run the planner, critique, or repair. So the `/architecture/regenerate` endpoint produces a near-identical revision. The button implies fresh generation; the behavior is "clone + flag." Combined with A1, **there is no working path that re-derives architecture from scratch after the first generation.** Worth either renaming or wiring it to the planner.

### A3. Customer-readiness is permanently capped without optional MCPs — MEDIUM (expectation gap)
`assess_customer_readiness` ([customer_readiness.py:43-46](app/services/customer_readiness.py:43)) adds a **blocker** whenever AWS Docs MCP or AWS Pricing MCP is unavailable:

```python
if not evidence_quality.get("aws_docs_available"):
    blockers.append("AWS Docs MCP unavailable ...")
if not evidence_quality.get("aws_pricing_available"):
    blockers.append("AWS Pricing MCP unavailable ...")
```

Both MCPs are **optional and off by default** ([config.py:79-91](app/core/config.py:79)). Any blocker forces `DIRECTIONAL_ONLY` ([customer_readiness.py:68-69](app/services/customer_readiness.py:68)). Net effect: **in the default local configuration, every session is hard-capped at "directional only" forever**, no matter how good the brief or architecture is. This is *defensible* (you arguably can't be customer-ready without authoritative sources), but it means the entire upper half of the readiness ladder (`customer_demo_ready`, `customer_ready`) is **unreachable out of the box** — the same structural pattern as procurement-ready pricing (round 1, §4.6). The product's "ladder" is real in code but its top rungs require external integrations most users won't have configured. This should be stated plainly to stakeholders so the ladder isn't read as "achievable today."

### A4. Interview loops on the last question after exhaustion — LOW
In `respond` ([synthesis.py:111](app/services/synthesis.py:111)):

```python
current = next((item for item in questions if item.id not in answered),
               questions[0] if questions else None)
```

Once **all** synthesis questions are answered, this falls back to `questions[0]` and re-"answers" it every turn. Because each user message has different text, `_record_interview_answer` ([synthesis.py:215-230](app/services/synthesis.py:215)) appends a **new assumption each turn** ("Interview answer for '<first question>': …") and keeps **growing `refined_problem_statement`** with notes mis-attributed to the first question. Long conversations after the interview is "done" accumulate junk assumptions and an ever-growing problem statement. Low severity but messy, and it pollutes downstream artifacts.

---

## B. Robustness / resource issues (new)

### B1. JobManager state grows unbounded; cancel rarely works — MEDIUM (local-scope)
[jobs.py](app/services/jobs.py):
- `_jobs` and `_futures` are **never evicted** ([jobs.py:17-18](app/services/jobs.py:17)). A long-lived process accumulates every job forever (memory growth). Fine for short local sessions, real for a long-running server.
- Global pool is `max_workers=2` ([jobs.py:16](app/services/jobs.py:16)) across **all sessions**, and each job body calls `asyncio.run(...)`. Two concurrent heavy jobs (e.g. research + export) saturate the pool; a third queues with no user-visible "queued behind N" signal.
- `cancel` calls `future.cancel()` ([jobs.py:80](app/services/jobs.py:80)), which **cannot cancel an already-running future**. Only the diagram loop checks `should_cancel` mid-flight ([routes.py:468](app/api/routes.py:468)); research, architecture, and export ignore cancellation entirely. So "Cancel" usually just relabels the job while the work runs to completion.
- `update`/`should_cancel`/`_run` do `self._jobs[job_id]` with no guard ([jobs.py:59](app/services/jobs.py:59), [:85](app/services/jobs.py:85)); a `KeyError` would surface as an unhandled 500 (jobs are never deleted today, so it won't fire — but it's a latent trap if eviction is ever added).

### B2. `read_session_logs` will 500 on a corrupt audit line — LOW
[logging.py:79-83](app/core/logging.py:79) does `json.loads(line)` for every non-blank line with no try/except. A single malformed/partial line in `audit.jsonl` (e.g. interrupted write) makes `/diagnostics`, `/export`, and **hydration** throw. Audit writes are append-mode without locking ([logging.py:53-54](app/core/logging.py:53)); two concurrent jobs for one session can interleave writes and produce a corrupt line. Wrap the parse in try/except and skip bad lines.

### B3. Audit secret-redaction is name-based and shallow — LOW
[logging.py:41](app/core/logging.py:41) filters only top-level keys containing `secret` or `api_key`. It does **not** redact `token`, `auth`, `authorization`, `password`, or any secret nested inside a dict value. Today no audit call passes raw secrets (I checked the call sites), so it's not currently leaking — but the filter is weaker than it looks and would not catch an `auth_token=...` field if one were ever added. Broaden the denylist and consider recursive redaction.

---

## C. Security surface notes (new, low risk under the local-first model)

### C1. MCP server URLs are not host-allowlisted — LOW (operator-trust)
The **web fallback** results are correctly constrained to `aws.amazon.com`/`docs.aws.amazon.com` ([aws_research_tools.py:274-287](app/services/aws_research_tools.py:274)). But the **MCP endpoints themselves** (`aws_docs_mcp_url`, `aws_pricing_mcp_url`, `aws_pricing_reference_mcp_url`) are taken straight from env and POSTed to with the Bearer token attached, with **no validation that the host is an AWS/managed endpoint** — `_is_managed_aws_mcp_url` only affects *tool naming*, not allowlisting ([aws_research_tools.py:290-292](app/services/aws_research_tools.py:290)). An operator who misconfigures (or is tricked into setting) an MCP URL would send the auth token to an arbitrary host. This is config-controlled, so it's an operator-trust issue rather than a user-facing SSRF — but given the rest of the system is allowlist-disciplined, this is an inconsistency worth closing.

### C2. CORS is permissive for credentials-off but methods are broad — INFO
[main.py:14-20](app/main.py:14) allows the two localhost origins with `allow_credentials=False`. Fine for local. Just note there is **no authentication** on any endpoint; the security model relies entirely on "bound to localhost, single user." This must be enforced operationally — the app must never be exposed on `0.0.0.0` without adding auth (the README's "secrets stay server-side" claim assumes the server itself is trusted/local).

---

## D. Documentation accuracy gaps (new)

### D1. `discovery_planner.py` is undocumented — MEDIUM (doc completeness)
`app/services/discovery_planner.py` is a **379-line / 24 KB** module that arbitrates between the deterministic classifier and an optional LLM, and **drives the synthesis interview questions** (`plan_sync` is called on every session creation, [synthesis.py:39](app/services/synthesis.py:39)). It is **not mentioned anywhere in `docs/code-review-pack`** (confirmed by grep). For a module this central to the synthesis phase, that's a meaningful gap in the otherwise-accurate backend module map (`02-backend-module-map.md`). The understanding modules are documented; this larger one is not.

### D2. `model_router` / LLM provider path is lightly covered — LOW
`discovery_planner.plan()` and `architecture_critique` can call `ModelRouter` → Bedrock/Ollama providers. The docs mention Bedrock/Ollama settings but don't make clear which phases actually invoke a live model vs. stay deterministic. Given the product's "deterministic-first" promise, a short doc note on exactly where an LLM can enter the pipeline (discovery planning, deep understanding, architecture critique) would help reviewers reason about reproducibility.

---

## E. Smaller code-quality observations

- **`__import__("json")` instead of `import json`** recurs in hot helpers: [routes.py:579](app/api/routes.py:579)/[:590](app/api/routes.py:590)/[:598](app/api/routes.py:598), [architecture_revisions.py:151](app/services/architecture_revisions.py:151), and the convergence orchestrator. Harmless but a consistent code smell suggesting copy-paste growth.
- **`_scale_profile` posture heuristic** ([synthesis.py:357](app/services/synthesis.py:357)) flags `posture="production"` if *any* extracted metric `>= 100000`. A large but non-throughput metric (e.g. an audit-retention or latency value that happens to be large) could misclassify posture. Narrow it to throughput/asset metrics.
- **Frontend `request()` has no timeout** ([api.ts:5-18](frontend/src/lib/api.ts:5)); a hung backend hangs the UI call indefinitely. The health/diagnostics calls trigger remote checks and can be slow. Consider an `AbortController` timeout.
- **`artifactUrl`** ([api.ts:20](frontend/src/lib/api.ts:20)) interpolates `artifactId` (which contains `/`) without encoding. The backend `{artifact_id:path}` route tolerates slashes and ids are sanitized server-side, so it works, but it's fragile if id formats ever change.

---

## F. Re-confirmation of strengths (still true after deeper read)

- Job lifecycle, while limited, **correctly serializes all shared-state mutation under a single lock** and records start/succeed/fail/duration + audit events. No data races on `_jobs` were found.
- MCP HTTP client uses a **10s timeout**, raises on JSON-RPC `error`, validates result shape, and **never logs the auth token** ([mcp_http.py:32-52](app/services/mcp_http.py:32)).
- The synthesis interview, despite A4, is **fully deterministic** for session creation (no blocking network on `POST /sessions`) — `plan_sync` uses `_deterministic_plan` only.
- Architecture revisions **always re-run governance enrichment + validation on every append** ([architecture_revisions.py:110-119](app/services/architecture_revisions.py:110)), so a saved revision can't bypass the governance gate.

---

## G. Priority ranking of round-2 findings

| # | Finding | Severity | Type |
|---|---|---|---|
| A1 | Re-generate architecture silently discards new specs | **HIGH** | Correctness |
| A3 | Readiness ladder unreachable without optional MCPs (default cap = directional) | MEDIUM | Expectation/design |
| A2 | "Regenerate" only clones, never re-derives | MEDIUM | Correctness/UX |
| B1 | Job state unbounded; cancel mostly ineffective | MEDIUM | Robustness |
| D1 | `discovery_planner.py` undocumented | MEDIUM | Docs |
| A4 | Interview loops/pollutes artifacts after exhaustion | LOW | Correctness/UX |
| B2 | Corrupt audit line 500s diagnostics/hydration | LOW | Robustness |
| B3 | Shallow secret redaction in audit log | LOW | Security hygiene |
| C1 | MCP URLs not host-allowlisted | LOW | Security (operator-trust) |
| E* | `__import__`, posture heuristic, no fetch timeout | LOW | Quality |

---

## H. Honest bottom line for round 2

The deeper pass did **not** surface any trust-integrity breach (no faked pricing, no governance bypass, no path traversal, no secret leakage in practice). What it surfaced is a cluster of **state-lifecycle and expectation issues**: the most important is **A1** — re-generating architecture is a silent no-op once a revision exists, which is the kind of bug that quietly erodes user trust because the UI says "done" while nothing changed. The second theme is that **the product's two "readiness ladders" (pricing maturity and customer readiness) both top out at "directional" in any default install**, because their upper rungs are gated behind optional AWS MCP integrations — the code is honest, but the achievable ceiling is lower than the ladders imply. Everything else is robustness/quality polish appropriate to a pre-production local tool. The engineering discipline observed in round 1 holds up under closer reading; the gaps are in lifecycle edge cases and in matching stated capability ceilings to what a default deployment can actually reach.
