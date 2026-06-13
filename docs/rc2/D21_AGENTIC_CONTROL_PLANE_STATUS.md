# D21 Agentic Control Plane Status

Status: diagram-planning audit-only lane added after narrative/reviewer audit-only lanes.

Baseline master: `5791b1a60a33e4aaf4aee4a882b3457c8efa588e`

This document records the current D21 control-plane state after the narrative,
reviewer/red-team, and diagram-planning audit-only lanes are implemented.
Architecture-candidate agents remain future work.
The system now has an agentic proposal substrate, but deterministic Archway
still owns truth.

## Landed D21 Milestones

| Milestone | Tag | Target |
|---|---|---|
| Agentic foundation + deterministic repair planner | `archway-v2-agentic-foundation` | `2e83b5688a9d6c557fa1659db8babcfc5f6045f9` |
| Thin evaluation battery | `archway-v2-d21-evaluation-battery` | `57f84b9818b4f9ea551cf83f3473f34e72c1f5e2` |
| Research agent audit-only lane | `archway-v2-d21-research-agent-audit` | `a632ced19087e34c0af8ce4a53ee731f4176d620` |
| Use-case analyst audit-only lane | `archway-v2-d21-use-case-analyst-audit` | `7b4ed96bfe759bf87d658d48873484307f9be346` |
| Pricing-dimension audit-only lane | `archway-v2-d21-pricing-dimension-audit` | `d9878ae75f02730688abfc4d121c890e258ff324` |
| Control-plane consolidation checkpoint | `archway-v2-d21-control-plane` | `90379059468612fe0088303eefb095c9ecb9cdd7` |
| Narrative and reviewer audit-only lanes | `archway-v2-d21-narrative-reviewer-audit` | `5791b1a60a33e4aaf4aee4a882b3457c8efa588e` |

## Current Lane Status

| Lane / component | Current status |
|---|---|
| Deterministic baseline | Implemented and authority-bearing. |
| Repair planner | Implemented; deterministic, raw/audit-only. |
| Evaluation battery | Implemented; deterministic, advisory gate only. |
| Research agent | Implemented as audit-only proposal lane; default off. |
| Use-case analyst agent | Implemented as audit-only proposal lane; default off. |
| Pricing-dimension agent | Implemented as audit-only proposal lane; default off. |
| Narrative agent | Implemented as audit-only proposal lane; default off. |
| Reviewer agent | Implemented as audit-only proposal lane; default off; deterministic reviewer mode remains authoritative. |
| Diagram-planning agent | Implemented as audit-only proposal lane; default off; deterministic compiler and rendering ledger remain authoritative. |
| Architecture-candidate agent | Not implemented. |

## Authority Matrix

| Component | Default enabled | Can propose | Writes raw | Writes audit_pack | Writes client_pack | Can affect readiness | Can affect pricing math | Can affect headline pricing | Can affect architecture/compiler truth | Can affect diagram rendering | Requires human review |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Deterministic baseline | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | No |
| Repair planner | No | Yes | Yes | Yes | No | No | No | No | No | No | No |
| Evaluation battery | No | No | Yes | Yes | No | No | No | No | No | No | Yes |
| Research agent | No | Yes | Yes | Yes | No | No | No | No | No | No | Yes |
| Use-case analyst agent | No | Yes | Yes | Yes | No | No | No | No | No | No | Yes |
| Pricing-dimension agent | No | Yes | Yes | Yes | No | No | No | No | No | No | Yes |
| Narrative agent | No | Yes | Yes | Yes | No | No | No | No | No | No | Yes |
| Reviewer agent | No | Yes | Yes | Yes | No | No | No | No | No | No | Yes |
| Diagram-planning agent | No | Yes | Yes | Yes | No | No | No | No | No | No | Yes |
| Future architecture-candidate agent | No | No | No | No | No | No | No | No | No | No | Yes |

## Allowed Today

- Deterministic export generation.
- Deterministic repair planning from existing readiness, pricing, evidence,
  reviewer, linter, and diagram signals.
- Raw/audit traces for current D21 lanes.
- Research, use-case, pricing-dimension, narrative, reviewer, and diagram-plan
  proposals as auditable candidates.
- Deterministic validation, downgrade, rejection, or assumption labeling of
  proposals.
- Evaluation-battery scoring that records human-review requirements.

## Explicitly Not Allowed Yet

- Client-facing agent output.
- Live LLM calls in the default/golden path.
- Live network calls in the default/golden path.
- Readiness promotion from agentic proposals.
- Pricing math or headline pricing changes from agentic proposals.
- Architecture/compiler truth changes from agentic proposals.
- Diagram rendering changes from agentic proposals.
- Governance or verifier semantics changes from agentic proposals.
- Any claim that D21 is fully complete.

## Raw / Audit Artifact Contract

Current D21 exports should include raw traces:

- `raw/agent_runs.json`
- `raw/agent_proposals.json`
- `raw/agent_repair_plan.json`
- `raw/agent_evaluation_battery.json`
- `raw/agent_research_trace.json`
- `raw/agent_research_evidence.json`
- `raw/agent_use_case_analyst_trace.json`
- `raw/agent_use_case_analyst_proposal.json`
- `raw/agent_pricing_dimension_trace.json`
- `raw/agent_pricing_dimension_proposal.json`
- `raw/agent_narrative_trace.json`
- `raw/agent_narrative_proposals.json`
- `raw/agent_reviewer_trace.json`
- `raw/agent_reviewer_findings.json`
- `raw/agent_diagram_plan_trace.json`
- `raw/agent_diagram_plan_proposal.json`

Current D21 exports should include audit summaries:

- `audit_pack/agentic-repair-plan.md`
- `audit_pack/agentic-evaluation-summary.md`
- `audit_pack/agentic-research-summary.md`
- `audit_pack/agentic-use-case-analysis.md`
- `audit_pack/agentic-pricing-dimensions.md`
- `audit_pack/agentic-narrative-proposals.md`
- `audit_pack/agentic-reviewer-findings.md`
- `audit_pack/agentic-diagram-plan.md`

These artifacts are manifest-inventoried and verifier-covered. They are not
client-pack authority.

## Next Recommended Branch

`feature/d21-architecture-candidate-agent-audit-only`

That branch should stay audit-first. It may propose architecture candidates
only; deterministic critique and human review must remain mandatory before any
client-facing authority is considered.
