# D21 Agentic Demo Readiness Freeze

Status: final D21 audit-only demo-readiness freeze candidate.

Baseline master: `9001b20581a39a950eef5b6bb8cd2c2c3e2fd57b`

Remote: `https://github.com/cloudkinesis/archway.git`

This is the final D21 audit-only demo freeze. It stops agent-lane development
before demo and records the proof posture for Archway as an agentic compiler
framework under deterministic authority.

## Relevant Tags

| Tag | Target |
|---|---|
| `archway-v2-rc2-golden-baseline` | `0b8e924720c6e2e29b7e3fc207ae2d0a9894d0c0` |
| `archway-v2-post-rc2-claude-showcase` | `c6ce85b91036728e35d7001e5c7a7f9681d416e7` |
| `archway-v2-agentic-foundation` | `2e83b5688a9d6c557fa1659db8babcfc5f6045f9` |
| `archway-v2-d21-evaluation-battery` | `57f84b9818b4f9ea551cf83f3473f34e72c1f5e2` |
| `archway-v2-d21-research-agent-audit` | `a632ced19087e34c0af8ce4a53ee731f4176d620` |
| `archway-v2-d21-use-case-analyst-audit` | `7b4ed96bfe759bf87d658d48873484307f9be346` |
| `archway-v2-d21-pricing-dimension-audit` | `d9878ae75f02730688abfc4d121c890e258ff324` |
| `archway-v2-d21-control-plane` | `90379059468612fe0088303eefb095c9ecb9cdd7` |
| `archway-v2-d21-narrative-reviewer-audit` | `5791b1a60a33e4aaf4aee4a882b3457c8efa588e` |
| `archway-v2-d21-diagram-planning-audit` | `9ccf6ff3a90825ab4d00470e64a103f43e7a7dd8` |
| `archway-v2-d21-architecture-candidate-audit` | `9001b20581a39a950eef5b6bb8cd2c2c3e2fd57b` |

## What Archway Can Now Do

- Accept legitimate AWS-oriented use cases and produce a complete package outcome.
- Produce `client_pack/` and `audit_pack/` alongside root compatibility artifacts.
- Produce deterministic diagrams, or disclose fallback/missing views through the rendering ledger and audit pack.
- Produce pricing posture with explicit labels, assumptions, missing drivers, and not-estimated states where appropriate.
- Produce raw/audit traces for repair planning, research, use-case analysis, pricing dimensions, narrative proposals, reviewer findings, diagram planning, and architecture candidates.
- Produce repair plans and next advancement steps from existing deterministic signals.
- Run the D21 evaluation battery with human-review markers for subjective lanes.

## What Archway Does Not Claim

- Not every artifact is procurement-ready.
- Agent proposals are not architecture truth, pricing truth, diagram truth, readiness truth, or verifier truth.
- Architecture soundness is human-reviewed; it is not automatically certified.
- `model_proposed` cannot unlock readiness.
- No live agent lane is enabled by default.
- No client-facing agent output is enabled.
- Pricing is not procurement-grade unless deterministic pricing gates pass.
- A diagram is not truth unless the compiler rendered it or the ledger disclosed the fallback/omission.

## Outcome Taxonomy

1. **Solution package** - mapped or pattern-backed workload where deterministic gates pass.
2. **Directional / diagnostic package** - coherent use case where gates are not fully met; the package includes assumptions, missing facts, repair plan, and downgraded readiness.
3. **Unsupported / refusal package** - unsafe, out-of-scope, or irresponsible architecture request; Archway returns a finished explanation and repair path instead of fake architecture/pricing.

The product-readiness claim is that Archway can complete one of these outcomes
without half-built output or silent overconfidence. It is not a claim that every
artifact reaches procurement readiness.

## Authority Matrix

| Component | Default enabled | Writes raw | Writes audit_pack | Writes client_pack | Can affect readiness | Can affect pricing math | Can affect headline pricing | Can affect architecture truth | Can affect diagram truth | Can affect manifest/verifier | Requires human review |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Deterministic baseline | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | No |
| Repair planner | No | Yes | Yes | No | No | No | No | No | No | No | No |
| Evaluation battery | No | Yes | Yes | No | No | No | No | No | No | No | Yes |
| Research agent | No | Yes | Yes | No | No | No | No | No | No | No | Yes |
| Use-case analyst agent | No | Yes | Yes | No | No | No | No | No | No | No | Yes |
| Pricing-dimension agent | No | Yes | Yes | No | No | No | No | No | No | No | Yes |
| Narrative agent | No | Yes | Yes | No | No | No | No | No | No | No | Yes |
| Reviewer agent | No | Yes | Yes | No | No | No | No | No | No | No | Yes |
| Diagram planning agent | No | Yes | Yes | No | No | No | No | No | No | No | Yes |
| Architecture candidate agent | No | Yes | Yes | No | No | No | No | No | No | No | Yes |

## Demo Story

- Archway is now an agentic compiler framework.
- Agents propose; deterministic gates decide.
- The compiler owns truth.
- The client pack is polished and free of raw agent machinery.
- The audit pack contains provenance, traces, rejected proposals, and repair paths.
- Every claim is grounded, assumed, proposed, rejected, or not estimated.

## Final Validation Checklist

- `python -m pytest -q`
- `python scripts/rc2_validate.py --profile golden --frontend --allow-missing-optional-tests`
- `npm run build` from `frontend/`
- `python scripts/d21_eval_battery.py --output-dir artifacts/d21_eval_battery`
- `python scripts/d21_agentic_status.py --output artifacts/d21_agentic_status.md`
- `python scripts/d21_demo_readiness_check.py` and, after golden export generation, rerun it with the three package zip paths.

## Next Decision

The next future decision is explicit client-facing promotion rules. It is not
another hidden authority movement and not another agent lane before demo.
