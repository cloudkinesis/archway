# RC2 Golden Baseline

Baseline commit: `0b8e924`

Date: 2026-06-12

## Validation

Final release-preservation pass on `master @ 0b8e924`:

```text
.venv/bin/python -m pytest -q
369 passed in 193.35s

.venv/bin/python scripts/rc2_validate.py --profile golden --frontend --allow-missing-optional-tests
RC2 validation [golden] -> READY
passed=369 known_fail=0 new_fail=0 skipped=0 known_now_passing=0

npm run build
PASS
```

Golden export packages from the validation run:

```text
Legal dossier verifier: VALID, 89 artifacts checked, 0 mismatched, 0 missing
Healthcare dossier verifier: VALID, 85 artifacts checked, 0 mismatched, 0 missing
Telecom dossier verifier: VALID, 75 artifacts checked, 0 mismatched, 0 missing
```

`docs/rc2/known_failures.yaml` has no known failures:

```text
known_failures: []
```

## Release-Blocking Fixes Included

- `c1588bc` merged `integration/rc2-golden-rehearsal-v2`.
- `a853c1c` merged known-failure cleanup plus final review fixes:
  - fail-closed dossier/export pricing headline safety,
  - removal of utility/depot/dispatch wording from healthcare-facing generic dossier sections,
  - removal of shared catalog dispatch/outage wording from healthcare artifacts.
- `0b8e924` merged the RC2 decision/control-plane docs.

## Excluded Next-Wave Branches

The following branches remain intentionally outside the RC2 Golden baseline:

```text
feature/capability-accelerator-packs-network-hcm
feature/capability-accelerator-packs-security-banking-spaces
feature/architecture-decision-records
feature/reviewer-mode-uncertainty-scenario-simulation
```

## Rollback

Rollback by reverting the merge commits in reverse order:

```bash
git revert -m 1 0b8e924
git revert -m 1 a853c1c
git revert -m 1 c1588bc
```

## Recommendation

Tag `0b8e924` as the Archway Diagram Compiler V2 / RC2 Golden baseline.
