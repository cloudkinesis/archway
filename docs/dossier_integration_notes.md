# Verifiable dossier — integration notes

Branch: `feature/verifiable-dossier-sku-export-ux` (stacked on
`feature/sku-pricing-official-snapshot-builder @ b92b98f`).

## Known integration dependency: pricing headline-safe is only as honest as the merged pricing gates

The dossier manifest reports global pricing headline safety **directly from the
existing pricing metadata** — specifically `pricing.metadata
["pricing_can_be_displayed_as_headline"]` and the source-truth ledger summary's
`headline_safe`. This branch does **not** re-derive or tighten that signal; it
faithfully mirrors whatever the legacy/global pricing path already produced.

Implication for the golden merge:

- The golden/master merge **must include the pricing fail-closed branches**
  (the headline/procurement fail-closed fixes) so that directional pricing can
  **never** be reported as `headline_safe = true`.
- If the dossier layer is merged **without** those pricing fail-closed branches,
  the manifest could show `pricing_headline_safe = true` for an estimate that is
  actually directional — because it is only echoing the upstream gate.

In short: this branch is a faithful **reporter** of pricing readiness, not its
**enforcer**. The enforcement lives in the pricing fail-closed branches, which are
a hard prerequisite for trustworthy `overall_status` / `pricing_headline_safe`
fields in the manifest.

## SKU provenance completeness

`pricing.sku_pilot.provenance_status` is:

- `complete` — `rate_authoritative=true` AND `upstream_source` + `version_hash` +
  `source_hash` are all present.
- `partial` — `rate_authoritative=true` but one of those provenance fields is
  missing. `scripts/verify_solution_dossier.py` warns by default and **fails** under
  `--strict`.
- `not_authoritative` — rates are not authoritative (e.g. fixture-backed).

## Verification is not inferred

The UI Trust panel never reports "verified" from manifest presence alone. It shows
the manifest as present/missing and verification as "not run — available offline",
flipping to "verified"/"failed" only when an actual
`scripts/verify_solution_dossier.py` result is supplied.
