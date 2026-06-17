"""Tests for the D25 brutal convergence eval battery.

These lock in the PROVEN invariants — the over-compounding / 40-exabyte bug
must never recur, retained event streams must not under-count storage to zero,
and the diverse scenarios must stay clean without scenario-specific logic.
"""

from __future__ import annotations

from app.services.d25_convergence_eval import (
    d25_convergence_scenarios,
    run_convergence_eval,
)


def test_battery_has_diverse_scenarios():
    scenarios = d25_convergence_scenarios()
    assert len(scenarios) >= 10
    # Genuinely diverse / unseen — not all streaming-prediction clones.
    ids = {s.scenario_id for s in scenarios}
    assert {"museum_conservation", "space_debris", "carbon_forest_verification"} <= ids


def test_no_absurd_quantities_for_any_scenario():
    """The proven fix: no derived quantity is physically absurd, and the
    plausibility gate raises no critical finding — for every scenario."""
    result = run_convergence_eval()
    for item in result["results"]:
        checks = item["checks"]
        assert checks["no_critical_plausibility"], f"{item['scenario_id']} hit a critical plausibility finding"
        assert checks["storage_not_absurd"], f"{item['scenario_id']} derived absurd storage ({item['storage_gb_month']})"
        assert checks["events_finite_nonneg"], item["scenario_id"]


def test_consistency_and_prose_invariants_hold_for_all():
    """Profile consistency and prose hygiene generalize across scenarios."""
    result = run_convergence_eval()
    for item in result["results"]:
        checks = item["checks"]
        assert checks["no_selected_excluded_overlap"], f"{item['scenario_id']} selected∩excluded not empty"
        assert checks["negation_honored"], f"{item['scenario_id']} kept an explicitly negated family"
        assert checks["prose_clean"], f"{item['scenario_id']} leaked interview/negation scaffolding into prose"


def test_no_streaming_scenario_undercounts_retained_storage_to_zero():
    """A retained event stream with extracted payload shape must not silently
    collapse to zero storage."""
    result = run_convergence_eval()
    undercount = [
        item["scenario_id"]
        for item in result["results"]
        if not item["checks"]["storage_consistent_with_events"]
    ]
    assert undercount == []
