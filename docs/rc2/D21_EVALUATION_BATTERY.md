# D21 Thin Evaluation Battery

This document records the D21 Phase 1 evaluation battery. It is a gate for future
agent lanes; it is not itself an agent, and it does not move authority from the
deterministic compiler.

## Scope

- Ten thin open-world scenarios exercise evidence, pricing-label, reproducibility,
  diagram render-or-disclose, client-surface protection, and repair-plan behavior.
- Auto-scored lanes cover observable safety properties only.
- Architecture soundness, domain appropriateness, and strategic fit remain
  human-judged. The battery deliberately does not pretend to certify those.
- Client-facing agent output remains blocked unless auto metrics pass and required
  human-scored lanes have explicit review.

## Runner

```bash
.venv/bin/python scripts/d21_eval_battery.py --output-dir artifacts/d21_eval_battery
.venv/bin/python scripts/d21_eval_battery.py --scenario lex_contact_center --json
```

The runner writes:

- `artifacts/d21_eval_battery/result.json`
- `artifacts/d21_eval_battery/report.md`

Generated outputs are validation artifacts and should remain uncommitted unless a
future decision promotes them into a golden fixture.

## Authority Boundary

The battery does not call an LLM, call the network, generate client-pack prose,
promote readiness, change pricing math, or change diagram/compiler truth. It
records whether future agentic output may be considered for client-facing use.
