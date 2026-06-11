"""Deterministic scenario / what-if simulation (export trust artifacts).

Bounded, honest first version (DECISIONS lineage D3/D10/D19):

Supported (REAL recomputation through the actual ``PricingEngine`` with its
first-class ``pricing_driver_overrides`` parameter):
- ``pricing_driver_override``  — set a recognized driver to a value.
- ``pricing_driver_multiplier`` — multiply a recognized driver's baseline value.
- ``retention_constraint``     — mapped onto a retention driver when one exists.
- ``quantity_confirmation``    — SKU-pilot simulation-only readiness toggle.

Honest ``not_applied`` (NO faking):
- ``region_constraint`` / ``resilience_constraint`` (RTO/RPO) — region-aware and
  DR/multi-region recomputation are not supported by the current pipeline, so
  these report a design-review requirement instead of inventing architecture.
- Unrecognized drivers — the engine silently ignores unknown override keys, so
  the simulator detects no-ops and reports ``not_applied`` rather than echoing
  unchanged totals as if they were a result.

Never: new architecture components, multi-region designs, new governance
controls, global readiness promotion, LLM/model output, or mutation of the
original session payloads.
"""

from __future__ import annotations

import asyncio
import copy
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.domain import AWSServiceSelection, UseCaseBrief
from app.services.reviewer_mode import build_reviewer_report, build_uncertainty_map

SimulationStatus = Literal["completed", "partial", "not_applied", "failed_closed"]

RETENTION_DRIVER_CANDIDATES = ("audit_retention_years", "retention_years")


class ScenarioOverride(BaseModel):
    override_id: str
    override_type: Literal[
        "pricing_driver_override",
        "pricing_driver_multiplier",
        "region_constraint",
        "resilience_constraint",
        "retention_constraint",
        "quantity_confirmation",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)


class ScenarioSimulationResult(BaseModel):
    scenario_id: str
    title: str
    status: SimulationStatus
    applied_overrides: list[dict[str, Any]] = Field(default_factory=list)
    not_applied_overrides: list[dict[str, Any]] = Field(default_factory=list)
    pricing_delta: dict[str, Any] = Field(default_factory=dict)
    architecture_delta: dict[str, Any] = Field(default_factory=dict)
    governance_delta: dict[str, Any] = Field(default_factory=dict)
    readiness_delta: dict[str, Any] = Field(default_factory=dict)
    adr_delta: dict[str, Any] = Field(default_factory=dict)
    uncertainty_delta: dict[str, Any] = Field(default_factory=dict)
    reviewer_findings_delta: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    generated_by: Literal["deterministic_rule"] = "deterministic_rule"


_UNCHANGED_ARCHITECTURE = {
    "status": "unchanged",
    "reason": "architecture recomputation is not supported by scenario simulation; pricing-only what-if.",
}
_UNCHANGED_GOVERNANCE = {
    "status": "unchanged",
    "reason": "governance recomputation is not supported by scenario simulation.",
}


def known_driver_values(pricing: dict | None) -> dict[str, float]:
    """Parse ``name=value`` driver strings from main_cost_drivers (incl. assumed_ prefix)."""
    values: dict[str, float] = {}
    for item in (pricing or {}).get("main_cost_drivers") or []:
        match = re.match(r"^(assumed_)?([a-z0-9_]+)=([0-9][0-9_,.]*)$", str(item).strip())
        if match:
            name = match.group(2)
            try:
                values[name] = float(match.group(3).replace(",", "").replace("_", ""))
            except ValueError:
                continue
    return values


def _run_async(coro):
    """Run a coroutine safely whether or not an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


def _recompute_pricing(brief: dict, architectures: list | None, overrides: dict[str, Any]) -> dict | None:
    """Re-run the REAL pricing engine with driver overrides. Returns a dump or None."""
    from app.services.pricing import PricingEngine  # local import: keeps module import light

    try:
        brief_obj = UseCaseBrief.model_validate(brief)
    except Exception:
        return None
    spec = next((s for s in (architectures or []) if isinstance(s, dict) and s.get("mode") == "production"),
                next((s for s in (architectures or []) if isinstance(s, dict)), {}))
    plan: list[AWSServiceSelection] = []
    for item in spec.get("selected_services") or []:
        if isinstance(item, dict):
            try:
                plan.append(AWSServiceSelection.model_validate(
                    {k: item.get(k) for k in ("service", "purpose", "selected", "rationale", "alternatives_considered") if item.get(k) is not None}
                ))
            except Exception:
                continue
    try:
        result = _run_async(PricingEngine().estimate(brief_obj, plan, pricing_driver_overrides=overrides))
    except Exception:
        return None
    return result.model_dump(mode="json")


def _totals(pricing: dict | None) -> dict[str, float]:
    return {
        "low_monthly_usd": float((pricing or {}).get("low_monthly_usd") or 0.0),
        "expected_monthly_usd": float((pricing or {}).get("expected_monthly_usd") or 0.0),
        "high_monthly_usd": float((pricing or {}).get("high_monthly_usd") or 0.0),
    }


def _readiness(pricing: dict | None) -> dict[str, Any]:
    metadata = (pricing or {}).get("metadata") or {}
    summary = (metadata.get("pricing_ledger") or {}).get("summary") or {}
    pilot = metadata.get("sku_pricing_pilot") or {}
    return {
        "headline_flag": metadata.get("pricing_can_be_displayed_as_headline", False) is True,
        "headline_safe": bool(summary.get("headline_safe", False)),
        "procurement_ready": bool(summary.get("procurement_ready", False)),
        "sku_pilot_procurement_ready": bool(pilot.get("sku_pilot_procurement_ready", False)) if pilot else None,
    }


def _findings_by_category(report) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in report.findings:
        counts[finding.category] = counts.get(finding.category, 0) + 1
    return counts


def _build_deltas(
    baseline_pricing: dict | None,
    simulated_pricing: dict | None,
    *,
    brief: dict | None,
    report: dict | None,
    architectures: list | None,
    diagrams: Any,
    decision_records: list[dict] | None,
    affected_drivers: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    base_totals, sim_totals = _totals(baseline_pricing), _totals(simulated_pricing)
    pricing_delta = {
        "baseline": base_totals,
        "simulated": sim_totals,
        "delta": {key: round(sim_totals[key] - base_totals[key], 2) for key in base_totals},
        "affected_drivers": affected_drivers,
    }
    readiness_delta = {"baseline": _readiness(baseline_pricing), "simulated": _readiness(simulated_pricing)}
    base_review = build_reviewer_report(brief, report, baseline_pricing, architectures, diagrams, decision_records)
    sim_review = build_reviewer_report(brief, report, simulated_pricing, architectures, diagrams, decision_records)
    reviewer_delta = {
        "baseline_counts": _findings_by_category(base_review),
        "simulated_counts": _findings_by_category(sim_review),
        "baseline_status": base_review.overall_review_status,
        "simulated_status": sim_review.overall_review_status,
    }
    base_unc = build_uncertainty_map(brief, report, baseline_pricing, architectures, diagrams, decision_records)
    sim_unc = build_uncertainty_map(brief, report, simulated_pricing, architectures, diagrams, decision_records)
    uncertainty_delta = {
        "baseline_pricing_confidence": base_unc["by_section"]["pricing"],
        "simulated_pricing_confidence": sim_unc["by_section"]["pricing"],
    }
    return {
        "pricing_delta": pricing_delta,
        "readiness_delta": readiness_delta,
        "reviewer_findings_delta": reviewer_delta,
        "uncertainty_delta": uncertainty_delta,
    }


def _simulate_driver_change(
    override: ScenarioOverride,
    *,
    brief: dict | None,
    baseline_pricing: dict | None,
    report: dict | None,
    architectures: list | None,
    diagrams: Any,
    decision_records: list[dict] | None,
) -> ScenarioSimulationResult:
    payload = override.payload
    known = known_driver_values(baseline_pricing)
    if override.override_type == "retention_constraint":
        retention_days = payload.get("retention_days")
        driver = next((d for d in RETENTION_DRIVER_CANDIDATES if d in known), None)
        if driver is None or retention_days is None:
            return ScenarioSimulationResult(
                scenario_id=override.override_id, title="Retention constraint",
                status="not_applied",
                not_applied_overrides=[{**override.model_dump(), "reason": "no retention pricing driver exists for this workload"}],
                architecture_delta=_UNCHANGED_ARCHITECTURE, governance_delta=_UNCHANGED_GOVERNANCE,
                warnings=["retention override could not be mapped to a pricing driver"],
            )
        new_value = round(float(retention_days) / 365.0, 2)
        driver_name, value = driver, new_value
        title = f"Retention {retention_days} days (→ {driver}={new_value} years)"
    else:
        driver_name = str(payload.get("driver") or "")
        if override.override_type == "pricing_driver_multiplier":
            if driver_name not in known:
                return ScenarioSimulationResult(
                    scenario_id=override.override_id, title=f"Driver multiplier: {driver_name}",
                    status="not_applied",
                    not_applied_overrides=[{**override.model_dump(), "reason": f"driver '{driver_name}' has no baseline value in pricing metadata"}],
                    architecture_delta=_UNCHANGED_ARCHITECTURE, governance_delta=_UNCHANGED_GOVERNANCE,
                    warnings=[f"unknown driver '{driver_name}'"],
                )
            value = known[driver_name] * float(payload.get("multiplier") or 1)
            title = f"{driver_name} × {payload.get('multiplier')}"
        else:
            value = payload.get("value")
            title = f"{driver_name} = {value}"
            if driver_name not in known:
                return ScenarioSimulationResult(
                    scenario_id=override.override_id, title=title,
                    status="not_applied",
                    not_applied_overrides=[{**override.model_dump(), "reason": f"driver '{driver_name}' is not a recognized pricing driver for this workload"}],
                    architecture_delta=_UNCHANGED_ARCHITECTURE, governance_delta=_UNCHANGED_GOVERNANCE,
                    warnings=[f"unknown driver '{driver_name}'"],
                )
    simulated = _recompute_pricing(dict(brief or {}), architectures, {driver_name: value})
    if simulated is None:
        return ScenarioSimulationResult(
            scenario_id=override.override_id, title=title, status="failed_closed",
            not_applied_overrides=[{**override.model_dump(), "reason": "pricing engine recomputation failed"}],
            architecture_delta=_UNCHANGED_ARCHITECTURE, governance_delta=_UNCHANGED_GOVERNANCE,
            warnings=["recomputation failed; no simulated totals are reported"],
        )
    sim_known = known_driver_values(simulated)
    no_op = (
        _totals(simulated) == _totals(baseline_pricing)
        and sim_known.get(driver_name) == known.get(driver_name)
    )
    if no_op:
        return ScenarioSimulationResult(
            scenario_id=override.override_id, title=title, status="not_applied",
            not_applied_overrides=[{**override.model_dump(), "reason": "pricing engine did not honor the override (driver not used by this family)"}],
            architecture_delta=_UNCHANGED_ARCHITECTURE, governance_delta=_UNCHANGED_GOVERNANCE,
            warnings=[f"override on '{driver_name}' produced no change; reported honestly as not applied"],
        )
    affected = [{"driver": driver_name, "old": known.get(driver_name), "new": sim_known.get(driver_name, value)}]
    deltas = _build_deltas(
        baseline_pricing, simulated, brief=brief, report=report, architectures=architectures,
        diagrams=diagrams, decision_records=decision_records, affected_drivers=affected,
    )
    return ScenarioSimulationResult(
        scenario_id=override.override_id, title=title, status="completed",
        applied_overrides=[override.model_dump()],
        architecture_delta=_UNCHANGED_ARCHITECTURE, governance_delta=_UNCHANGED_GOVERNANCE,
        adr_delta={"status": "unchanged", "reason": "decision records are re-derived at export; driver changes affect pricing-readiness ADR inputs only."},
        **deltas,
    )


def _simulate_quantity_confirmation(override: ScenarioOverride, baseline_pricing: dict | None) -> ScenarioSimulationResult:
    pilot = ((baseline_pricing or {}).get("metadata") or {}).get("sku_pricing_pilot")
    if not pilot:
        return ScenarioSimulationResult(
            scenario_id=override.override_id, title="Quantity confirmation toggle",
            status="not_applied",
            not_applied_overrides=[{**override.model_dump(), "reason": "no SKU pricing pilot metadata present"}],
            architecture_delta=_UNCHANGED_ARCHITECTURE, governance_delta=_UNCHANGED_GOVERNANCE,
        )
    confirmed = bool(override.payload.get("confirmed", True))
    simulated_pilot = copy.deepcopy(pilot)
    simulated_pilot["quantities_confirmed"] = confirmed
    simulated_pilot["quantity_source"] = "simulated_confirmation" if confirmed else "assumed"
    simulated_pilot["sku_pilot_procurement_ready"] = bool(
        confirmed and pilot.get("rate_authoritative") and pilot.get("sku_pilot_estimate_ready")
    )
    return ScenarioSimulationResult(
        scenario_id=override.override_id,
        title=f"SKU quantity confirmation = {confirmed} (simulation-only)",
        status="completed",
        applied_overrides=[override.model_dump()],
        architecture_delta=_UNCHANGED_ARCHITECTURE, governance_delta=_UNCHANGED_GOVERNANCE,
        readiness_delta={
            "scope": "sku_pilot_only",
            "baseline": {
                "quantities_confirmed": bool(pilot.get("quantities_confirmed")),
                "sku_pilot_procurement_ready": bool(pilot.get("sku_pilot_procurement_ready")),
            },
            "simulated": {
                "quantities_confirmed": simulated_pilot["quantities_confirmed"],
                "sku_pilot_procurement_ready": simulated_pilot["sku_pilot_procurement_ready"],
            },
            "global_readiness": "unchanged — simulation never promotes global headline/procurement readiness",
        },
        warnings=["simulation-only: quantities are NOT confirmed in the real workflow unless the customer confirms them"],
    )


def _simulate_unsupported(override: ScenarioOverride) -> ScenarioSimulationResult:
    if override.override_type == "region_constraint":
        title = f"Region constraint: {override.payload.get('region')}"
        reason = "region-aware recomputation not supported by current pipeline"
        warning = "region/data-residency changes require a manual architecture and pricing review"
    else:
        title = f"Resilience constraint: RTO={override.payload.get('rto_minutes')}min RPO={override.payload.get('rpo_minutes')}min"
        reason = "strict RTO/RPO requires DR architecture review; multi-region recomputation not supported"
        warning = "current architecture has no confirmed DR/multi-region pattern; design review required"
    return ScenarioSimulationResult(
        scenario_id=override.override_id, title=title, status="not_applied",
        not_applied_overrides=[{**override.model_dump(), "reason": reason}],
        architecture_delta={"status": "unchanged", "reason": reason},
        governance_delta=_UNCHANGED_GOVERNANCE,
        warnings=[warning],
    )


def simulate_scenarios(
    overrides: list[ScenarioOverride] | list[dict],
    *,
    brief: dict | None,
    baseline_pricing: dict | None,
    report: dict | None = None,
    architectures: list | None = None,
    diagrams: Any = None,
    decision_records: list[dict] | None = None,
) -> list[ScenarioSimulationResult]:
    """Run bounded deterministic what-ifs. Inputs are never mutated."""
    brief = copy.deepcopy(brief or {})
    baseline_pricing = copy.deepcopy(baseline_pricing or {})
    results: list[ScenarioSimulationResult] = []
    for raw in overrides:
        override = raw if isinstance(raw, ScenarioOverride) else ScenarioOverride.model_validate(raw)
        if override.override_type in {"pricing_driver_override", "pricing_driver_multiplier", "retention_constraint"}:
            results.append(_simulate_driver_change(
                override, brief=brief, baseline_pricing=baseline_pricing, report=report,
                architectures=architectures, diagrams=diagrams, decision_records=decision_records,
            ))
        elif override.override_type == "quantity_confirmation":
            results.append(_simulate_quantity_confirmation(override, baseline_pricing))
        else:
            results.append(_simulate_unsupported(override))
    return sorted(results, key=lambda r: r.scenario_id)


def scenario_summary(results: list[ScenarioSimulationResult]) -> dict[str, int]:
    return {
        "scenario_count": len(results),
        "completed_count": sum(1 for r in results if r.status == "completed"),
        "partial_count": sum(1 for r in results if r.status == "partial"),
        "not_applied_count": sum(1 for r in results if r.status == "not_applied"),
        "failed_closed_count": sum(1 for r in results if r.status == "failed_closed"),
    }


def scenario_simulations_markdown(results: list[ScenarioSimulationResult]) -> str:
    lines = [
        "# Scenario Simulations",
        "",
        "Bounded deterministic what-ifs through the real pricing engine. Unsupported",
        "constraints are reported honestly as not applied — nothing is faked.",
        "",
    ]
    for result in results:
        lines.extend([f"## {result.scenario_id} — {result.title}", "", f"- **Status:** {result.status}"])
        if result.pricing_delta:
            delta = result.pricing_delta.get("delta") or {}
            lines.append(
                f"- **Pricing delta (monthly USD):** low {delta.get('low_monthly_usd')}, "
                f"expected {delta.get('expected_monthly_usd')}, high {delta.get('high_monthly_usd')}"
            )
            for item in result.pricing_delta.get("affected_drivers") or []:
                lines.append(f"- **Driver:** {item.get('driver')}: {item.get('old')} → {item.get('new')}")
        for item in result.not_applied_overrides:
            lines.append(f"- **Not applied:** {item.get('reason')}")
        for warning in result.warnings:
            lines.append(f"- **Warning:** {warning}")
        lines.append("")
    return "\n".join(lines)
