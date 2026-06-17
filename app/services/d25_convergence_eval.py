"""D25 brutal convergence eval battery (offline, deterministic, domain-blind).

Proves that the open-world quantity graph, plausibility gate, prose hygiene,
and profile consistency generalize across diverse, never-before-coded use cases
— not just the railway scenario that exposed the original 40-exabyte bug.

This battery runs the REAL deterministic pipeline for each scenario
(`profile_use_case` -> `_canonical_facts` -> `_generic_quantity_context`) and
asserts artifact-level invariants on the output. It makes NO live model calls
and contains NO per-domain logic: the scenarios are test inputs only; every
check is a generic invariant that must hold for any legitimate use case.

Invariants asserted per scenario:
- plausibility:   no critical plausibility finding (events within asset/cadence
                  bound; storage not implausible per asset).
- storage sanity: derived storage is not physically absurd (< 1 exabyte).
- consistency:    selected and excluded workload families never overlap; an
                  explicit "not X" never appears as a selected family/domain.
- prose hygiene:  client-facing text strips interview-note dumps and
                  "not X, not Y" negation runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.client_pack import clean_presentation_text
from app.services.source_truth_pricing_compiler import (
    _canonical_facts,
    _generic_quantity_context,
)
from app.services.use_case_profile import profile_use_case

# A derived monthly storage figure at or above one exabyte (in GB) is physically
# absurd for any single workload and signals a quantity-composition bug.
ONE_EXABYTE_GB = 1_000_000_000


@dataclass
class D25Scenario:
    """A never-before-coded use case used purely as eval input (no production logic)."""

    scenario_id: str
    title: str
    use_case: str
    # Workload families / domains the use case explicitly negates ("not X"). Must
    # never end up selected. These are checked generically, not special-cased.
    negated_families: tuple[str, ...] = ()


def d25_convergence_scenarios() -> list[D25Scenario]:
    """Ten diverse, deliberately unseen scenarios, each with embedded quantities."""
    return [
        D25Scenario(
            "railway_structure",
            "Railway bridge and tunnel structural monitoring",
            "Monitor 1850 bridges and tunnels using vibration sensors every 5 seconds at 1.5 KB per event, "
            "acoustic clips of 800 KB occurring 50 times per day per 100 assets, and quarterly drone thermal "
            "images of 18 MB each at 20 images per bridge per quarter. Predict structural fatigue, retain raw "
            "sensor data 18 months and evidence summaries 10 years. This is not legal, not document search, not RAG.",
            negated_families=("rag_assistant", "document_intelligence"),
        ),
        D25Scenario(
            "museum_conservation",
            "Museum environmental conservation monitoring",
            "Protect artifacts across 320 galleries using humidity and temperature sensors every 60 seconds at "
            "2 KB per reading, plus 12 conservation cameras producing 4 MB images 50 times per day. Detect "
            "conservation risk, alert curators, retain readings for 5 years. This is not retail, not document search.",
            negated_families=("document_intelligence",),
        ),
        D25Scenario(
            "port_customs",
            "Port customs container inspection",
            "Across 14 berths and 80 cranes, ingest AIS vessel feeds every 10 seconds at 1 KB per message and "
            "X-ray container scans of 25 MB each for 6000 containers per day. Prioritize inspections, notify "
            "officers, retain evidence 7 years. This is not legal, not chatbot.",
        ),
        D25Scenario(
            "space_debris",
            "Space debris conjunction tracking",
            "From 6 radar stations, ingest track updates every 2 seconds at 3 KB per update for 40000 cataloged "
            "objects, run conjunction screening, and retain orbital history for 30 years. This is not RAG, not document search.",
            negated_families=("rag_assistant",),
        ),
        D25Scenario(
            "clinical_trial_logistics",
            "Clinical trial sample cold-chain logistics",
            "Across 220 trial sites, track cold-chain sensors every 30 seconds at 1 KB per reading for 90000 "
            "samples per month, enforce chain-of-custody, alert coordinators, and retain records 15 years. "
            "This is not retail, not field-service dispatch.",
            negated_families=("field_service_automation",),
        ),
        D25Scenario(
            "mining_tailings",
            "Mining tailings dam stability monitoring",
            "Monitor 48 tailings dams with piezometer and inclinometer readings every 15 seconds at 2 KB per "
            "reading, plus weekly InSAR scenes of 200 MB each. Predict instability, require engineer approval, "
            "retain data 25 years. This is not legal, not chatbot.",
        ),
        D25Scenario(
            "smart_building_energy",
            "Smart building energy arbitration",
            "Across 1200 smart meters, ingest HVAC telemetry every 60 seconds at 1 KB per reading plus occupancy "
            "forecasts and tariff signals. Optimize battery dispatch, retain data 3 years. This is not document search, not RAG.",
            negated_families=("rag_assistant", "document_intelligence"),
        ),
        D25Scenario(
            "marine_insurance_triage",
            "Marine insurance claims triage",
            "For 5000 policies, ingest vessel telemetry every 300 seconds at 2 KB per reading and drone damage "
            "photos of 15 MB each at 30 images per claim for 400 claims per month. Triage claims, retain evidence "
            "10 years. This is not a legal repository, not chatbot.",
        ),
        D25Scenario(
            "carbon_forest_verification",
            "Carbon-credit forest verification",
            "Across 900 forest parcels, ingest monthly satellite vegetation indices of 50 MB each and field audit "
            "photos of 8 MB each at 40 images per parcel per year. Verify carbon sequestration, retain evidence "
            "40 years. This is not retail, not document search.",
            negated_families=("document_intelligence",),
        ),
        D25Scenario(
            "vertical_farming",
            "Vertical farming AI operations",
            "Operate 60 grow rooms with climate sensors every 10 seconds at 1 KB per reading and plant-health "
            "cameras producing 6 MB images 200 times per day. Predict yield, recommend nutrient dosing, retain "
            "data 2 years. This is not legal, not document search.",
            negated_families=("document_intelligence",),
        ),
    ]


def _evaluate(scenario: D25Scenario) -> dict[str, Any]:
    profile = profile_use_case(scenario.use_case)
    facts = _canonical_facts(profile, None)
    ctx = _generic_quantity_context(facts)

    plausibility = ctx.get("plausibility_findings") or []
    critical = [item for item in plausibility if str(item.get("severity")) == "critical"]

    selected = set(profile.workload_families or [])
    excluded = set(profile.excluded_families or []) | set(profile.excluded_patterns or [])
    domain = (profile.domain or "")

    checks = {
        "no_critical_plausibility": not critical,
        "storage_not_absurd": float(ctx.get("storage_gb_month") or 0) < ONE_EXABYTE_GB,
        "events_finite_nonneg": float(ctx.get("monthly_events") or 0) >= 0,
        "no_selected_excluded_overlap": not (selected & excluded),
        "negation_honored": all(
            term not in selected and term != domain for term in scenario.negated_families
        ),
        "prose_clean": _prose_is_clean(scenario.use_case),
        # Internal consistency: a workload with a large retained event stream
        # cannot derive zero storage. Catches silent under-counts (the inverse
        # of the over-compounding bug).
        "storage_consistent_with_events": not (
            float(ctx.get("monthly_events") or 0) > 1_000_000
            and float(ctx.get("storage_gb_month") or 0) == 0
        ),
    }
    return {
        "scenario_id": scenario.scenario_id,
        "title": scenario.title,
        "passed": all(checks.values()),
        "checks": checks,
        "monthly_events": float(ctx.get("monthly_events") or 0),
        "monthly_inferences": float(ctx.get("monthly_inferences") or 0),
        "storage_gb_month": float(ctx.get("storage_gb_month") or 0),
        "critical_findings": critical,
        "selected_families": sorted(selected),
        "domain": domain,
    }


def _prose_is_clean(use_case: str) -> bool:
    """Inject the exact scaffolding the railway package leaked, then confirm the
    client prose cleaner strips it — for any use case, not a special-cased one."""
    dirty = (
        f"{use_case} Synthesis interview note: What cadence? Answer: every 5 seconds. "
        "Interview answer for 'scale?': about 1850 assets."
    )
    cleaned = clean_presentation_text(dirty)
    low = cleaned.lower()
    return (
        "synthesis interview note" not in low
        and "interview answer for" not in low
        and "not legal, not" not in low
        and "not retail, not" not in low
    )


def run_convergence_eval(scenarios: list[D25Scenario] | None = None) -> dict[str, Any]:
    scenarios = scenarios or d25_convergence_scenarios()
    results = [_evaluate(scenario) for scenario in scenarios]
    passed = sum(1 for item in results if item["passed"])
    return {
        "battery": "d25_open_world_convergence_quality_gates",
        "mode": "offline_deterministic",
        "scenario_count": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }
