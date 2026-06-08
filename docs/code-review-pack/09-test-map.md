# Test Map

Tests live under `tests/`, with additional golden scenario tests under `tests/golden_scenarios/`.

## Trust and Anti-Drift Tests

- `tests/test_healthcare_anti_drift.py`: verifies healthcare-specific additions do not turn generic, telecom, or media cases into healthcare-shaped outputs. Checks healthcare pricing family gating, governance view gating, healthcare reserved vocabulary scope, and domain-neutral lane categories.
- `tests/test_research_view_model.py`: checks profile-driven research wording, no healthcare leakage into telecom/generic research, hidden raw evidence ids, and pricing presentation rules.
- `tests/test_progress_stages.py`: checks meaningful progress labels for research/architecture/export jobs.
- `tests/golden_scenarios/test_scenario_matrix.py`: checks scenario classification and telecom guardrails.
- `tests/golden_scenarios/test_metric_extraction.py`: checks metric extraction for golden scenarios.

## Pricing Tests

- `tests/test_pricing.py`: deterministic pricing and selected workload-specific pricing behavior.
- `tests/test_pricing_driver_closure.py`: pricing checkpoint, scenario profiles, readiness ladder, and export closure section behavior.
- `tests/test_media_streaming_pricing.py`: live media pricing and first-class media compiler expectations.
- `tests/test_source_truth_pricing_compiler.py`: source-truth pricing compiler behavior, media assumptions, rate binding, and heuristic/not-estimated status.

## Diagram Tests

Relevant diagram/compiler tests include renderer/compiler adapter tests and domain-specific compiler placement tests. Some integration tests may require the local D2 compiler/runtime and are more expensive or environment-sensitive.

## End-to-End/API Tests

- `tests/test_end_to_end_flow.py`: verifies a broad local app flow and expected views.
- Additional route and export tests cover session creation, hydration, artifacts, and export package behavior.

## What Recently Passed

Prior run in this thread reported the full backend suite passing with 129 tests. The docs pack validation should not be treated as a replacement for a fresh full suite when making product changes.

## Suggested Reviewer Commands

Use:

```bash
python3 -m pytest -q
python3 -m pytest tests/test_healthcare_anti_drift.py -q
python3 -m pytest tests/test_research_view_model.py tests/test_progress_stages.py -q
python3 -m pytest tests/test_pricing.py tests/test_pricing_driver_closure.py tests/test_source_truth_pricing_compiler.py -q
```

Run frontend build with:

```bash
cd frontend
npm run build
```

If diagram tests fail, first confirm the configured compiler path and runtime are valid before assuming product logic is wrong.

