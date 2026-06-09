# RC2 Merge Plan

Proposed order to bring reviewed fixes onto `master`. Nothing here is executed by
this doc; it is the recommended sequence and the review gate. All merges should be
`--no-ff`, after a full-suite run (see GOLDEN_GATE.md) and Codex review.

---

## Stage 1 — Stabilization (five fixes via the integration branch)
Merge order (already validated together on `integration/rc2-stabilization-claude`):
1. `fix/architecture-revision-lifecycle` (`332df7c`)
2. `fix/synthesis-completion-loop` (`bbc9df2`)
3. `fix/export-quality-artifacts` (`0dbe9e9`)
4. `fix/job-manager-lifecycle` (`3556efa`)
5. `fix/typed-effectful-flow-detection` (`8dafe82`)

Recommended path: review and merge the **integration branch** `a23e676` as the unit
(it is exactly these five, `--no-ff`, conflict-free), OR merge the five individually
in the same order. Run the full backend suite + frontend build on the result.

## Stage 2 — Pricing headline fail-closed
6. `fix/pricing-headline-fail-closed` (`f39852b`)
7. `fix/export-pricing-headline-fail-closed` (`439b73b`)

Caveat: branch 7 was built off baseline and also edits `export_package.py`, which
Stage 1 branch 3 (`fix/export-quality-artifacts`) also edits. Expect a possible
conflict in `_pricing_markdown` / surrounding code. Resolution rule: keep the
loop-safe collection + quality-artifact status from branch 3 AND the fail-closed
default (`get(..., False)`) from branch 7. Re-run `tests/test_export_package.py`
and `tests/test_export_quality_artifacts.py` after resolving.

## Stage 3 — Audit / MCP hardening (only if completed and reviewed)
8. Audit-log robustness (KNOWN_ISSUES I3) — when a branch exists.
9. MCP URL allowlist (KNOWN_ISSUES I4) — when a branch exists.
Neither blocks the internal pilot; merge when ready.

## Stage 4 — SKU-backed pricing stack (stacked; merge bottom-up, after Codex review)
This is a dependency chain — review/merge in order, each onto the previous:
10. `feature/sku-backed-pricing-foundation` (`9b168d7`) — standalone SKU foundation; no live impact.
11. `feature/sku-pricing-local-cache-adapter` (`efe0849`, on `9b168d7`) — provenance-gated local-cache adapter; no live impact.
12. `feature/sku-pricing-source-truth-pilot` (`c301362`, on `efe0849`) — supplemental flag-gated pilot trace (legal/document RAG only).

Notes:
- All three are standalone/flag-gated; with `ARCHWAY_ENABLE_SKU_PRICING_PILOT` off (default) there is no live pricing change even after merge.
- Do NOT merge the pilot (12) without its bases (10, 11) — it imports them.
- The pilot must remain supplemental: it must not promote global `headline_safe`/`procurement_ready` (DECISIONS D10).
- Live UI/export do not yet surface the SKU pilot trace (KNOWN_ISSUES I9) — a future branch.

## Deferred — not in this RC2 stabilization line
- `experiment/domain-pack-interface` (`fe886af`) — DEFER until Codex review.
- `feature/domain-pack-phase2-pricing-drivers` (`20eea81`) — DEFER until Codex review.
- Frontend modularization (KNOWN_ISSUES I6) — DEFER post-stabilization.
- Bidirectional diagram sync (DECISIONS D8) — not near-term.

---

## Codex review checklist (per branch, before merge to master)
- [ ] Diff scope matches the branch's stated purpose; no unrelated files.
- [ ] No pricing numbers / families / rate-binding / source-truth math changed
      (unless that is the branch's explicit purpose).
- [ ] No safety gate relaxed: governance, headline safety, procurement/customer
      readiness, diagram QA remain owned by the deterministic pipeline.
- [ ] Fail-closed defaults preserved (no `get(flag, True)` reintroduced).
- [ ] Tests: the branch's focused tests pass; no new failures vs. baseline; the
      two known pre-existing failures (KNOWN_ISSUES I1/I2) are unchanged.
- [ ] Frontend build passes if any `frontend/` file changed; type changes additive.
- [ ] Domain-pack flag remains default OFF; flag-off behavior == baseline.
- [ ] Conflicts (esp. `export_package.py` in Stage 2) resolved per the rule above
      and re-tested.
- [ ] DECISIONS.md not contradicted; if it is, the decision is updated with rationale.
- [ ] Rollback command recorded (`git revert -m 1 <merge>`).
