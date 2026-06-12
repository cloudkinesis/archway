# Archway V2 Post-RC2 Claude Showcase

Status: APPROVED for post-RC2 showcase/master integration.

This note records the post-RC2 master integration that preserves the RC2 Golden
Baseline while adding Claude showcase work. The protected RC2 tag was not moved,
deleted, recreated, or retargeted.

## Protected Baseline

- RC2 baseline tag: `archway-v2-rc2-golden-baseline`
- RC2 baseline commit: `0b8e924720c6e2e29b7e3fc207ae2d0a9894d0c0`
- RC2 tag object: `9064080e6226ad0669593e4c00b2888953a1ed85`
- Post-note master commit before showcase integration: `d5c4ed1eae4beaa2ef0da77321d8618f808e97f9`
- Safety tag at pre-showcase master: `pre-claude-showcase-master`

## Integrated Claude Branches

The following branches were merged with `--no-ff` into
`integration/post-rc2-claude-showcase`; no squash merges were used.

| Branch | Branch SHA | Integration merge SHA | Notes |
|---|---:|---:|---|
| `feature/capability-accelerator-packs-network-hcm` | `1fc93de83766e19f8c7cb0141e378e4719040adb` | `7c15e8e` | Added default-off advisory accelerator packs for network/HCM intake hints. |
| `feature/capability-accelerator-packs-security-banking-spaces` | `d3d7242d9fb6b2f8b6dda2ff99424966c97fcede` | `3b1532b` | Added security, smart-spaces, banking, and financial-crime advisory accelerator packs. |
| `feature/architecture-decision-records` | `ac3d86b15acb3586d16c86bc7c5259b12d419f23` | `2509210` | Added deterministic ADR export artifacts and manifest summary. |
| `feature/reviewer-mode-uncertainty-scenario-simulation` | `f5e1192540e371bb8e8a4223ad426a78769b0671` | `4ee4031` | Added deterministic reviewer/uncertainty artifacts and default-off scenario simulations. |

## Conflicts Resolved

- `app/core/config.py` during `feature/capability-accelerator-packs-network-hcm`:
  preserved existing RC2 SKU pricing pilot settings and added the accelerator
  flag as default-off.
- `app/core/config.py` during
  `feature/reviewer-mode-uncertainty-scenario-simulation`: preserved the
  accelerator flag and added the scenario simulation flag as default-off.

No conflicts changed pricing, dossier, export, verifier, known-failure, or QA gate
semantics.

## Validation

Per-branch gates were run before each integration merge commit:

| Branch | Pytest | Focused RC2 validation | Frontend build |
|---|---:|---:|---|
| Network/HCM accelerator packs | `386 passed` | `READY_WITH_UNCOMMITTED_CHANGES`, `passed=27`, `known_fail=0`, `new_fail=0`, `skipped=0`, `known_now_passing=0` | PASS |
| Security/banking/spaces accelerator packs | `406 passed` | `READY_WITH_UNCOMMITTED_CHANGES`, `passed=27`, `known_fail=0`, `new_fail=0`, `skipped=0`, `known_now_passing=0` | PASS |
| Architecture decision records | `423 passed` | `READY_WITH_UNCOMMITTED_CHANGES`, `passed=27`, `known_fail=0`, `new_fail=0`, `skipped=0`, `known_now_passing=0` | PASS |
| Reviewer mode / uncertainty / scenario simulation | `447 passed` | `READY_WITH_UNCOMMITTED_CHANGES`, `passed=27`, `known_fail=0`, `new_fail=0`, `skipped=0`, `known_now_passing=0` | PASS |

Final integrated validation on `integration/post-rc2-claude-showcase`:

```bash
.venv/bin/python -m pytest -q
# 447 passed in 199.27s

.venv/bin/python scripts/rc2_validate.py --profile golden --frontend --allow-missing-optional-tests
# RC2 validation [golden] -> READY
# passed=447 known_fail=0 new_fail=0 skipped=0 known_now_passing=0

npm run build
# PASS
```

## Golden Export Packages

Fresh golden export packages from the final validation were verified with
`scripts/verify_solution_dossier.py`.

| Scenario | Result | Artifacts checked | Mismatched | Missing |
|---|---:|---:|---:|---:|
| Legal | VALID | 98 | 0 | 0 |
| Healthcare | VALID | 94 | 0 | 0 |
| Telecom | VALID | 84 | 0 | 0 |

Artifact counts are higher than RC2 because the showcase work adds ADR and
reviewer/uncertainty artifacts. All listed artifacts were present and hashes
matched.

## Anti-Drift Checks

- Pricing headline-safe export and manifest gates remain fail-closed:
  `pricing_can_be_displayed_as_headline` is headline-safe only when explicitly
  `True`.
- `docs/rc2/known_failures.yaml` remains `known_failures: []`.
- Logical edge crossing threshold remains `logical_edge_crossing_max: int = 8`.
- Healthcare package grep found utility/IoT terms only in
  `raw/golden_regression_summary.json`, the cross-scenario baseline summary; no
  healthcare-facing dossier or architecture artifact leakage was found.
- No validation thresholds were weakened.

## Rollback Plan

To roll back this showcase integration after it lands on master:

```bash
git revert -m 1 <post-rc2-showcase-master-merge-commit>
git tag -d archway-v2-post-rc2-claude-showcase
git push origin :refs/tags/archway-v2-post-rc2-claude-showcase
git push origin master
```

The protected RC2 tag must remain unchanged. If a return to the exact pre-showcase
master is needed, use the safety tag for inspection:

```bash
git log --oneline pre-claude-showcase-master..master
```

