from __future__ import annotations

from typing import Any

from app.core.logging import hash_payload
from app.models.domain import UseCaseBrief
from app.services.use_case_profile import UseCaseProfile, profile_from_metadata


def build_canonical_fact_snapshot(brief: UseCaseBrief) -> dict[str, Any]:
    profile = profile_from_metadata(brief.use_case_profile, _brief_context(brief))
    snapshot = {
        "schema": "canonical_fact_snapshot_v1",
        "domain": profile.domain,
        "workload_families": list(profile.workload_families),
        "primary_workload_family": profile.primary_family,
        "excluded_workload_families": list(dict.fromkeys(profile.excluded_families + profile.excluded_patterns)),
        "explicit_user_corrections": _explicit_user_corrections(brief),
        "actors": list(profile.entities),
        "data_sources": [item.name for item in brief.data_sources],
        "signals": list(profile.signals),
        "actions": list(profile.actions),
        "quantities": _quantities(profile),
        "latency_slos": [item for item in [profile.latency_target, profile.latency_class, brief.performance_profile.latency_sensitivity] if item],
        "connectivity_constraints": _connectivity_constraints(profile, brief),
        "retention": _retention(profile),
        "compliance_security_hints": list(dict.fromkeys(brief.compliance_profile.regimes + profile.capability_model)),
        "approval_human_gates": [item.text for item in brief.assumptions if "approval" in item.text.lower() or "human" in item.text.lower()],
        "pricing_drivers": _pricing_driver_hints(profile),
    }
    snapshot["hash"] = "sha256:" + hash_payload(snapshot)
    return snapshot


def canonical_hash_from_report(report: dict | None) -> str | None:
    snapshot = ((report or {}).get("metadata") or {}).get("canonical_fact_snapshot")
    return snapshot.get("hash") if isinstance(snapshot, dict) else None


def _brief_context(brief: UseCaseBrief) -> str:
    return "\n".join(
        item
        for item in [
            brief.raw_use_case,
            brief.refined_problem_statement,
            *[assumption.text for assumption in brief.assumptions],
            *brief.business_goals,
            *[question.text for question in brief.open_questions],
        ]
        if item
    )


def _explicit_user_corrections(brief: UseCaseBrief) -> list[str]:
    corrections = []
    for assumption in brief.assumptions:
        text = assumption.text
        lower = text.lower()
        if assumption.user_confirmed and any(token in lower for token in ("not a", "not ", "exclude", "instead", "this is not")):
            corrections.append(text)
    return corrections


def _quantities(profile: UseCaseProfile) -> list[dict[str, Any]]:
    items = []
    for metric in profile.metrics:
        items.append({
            "name": metric.label,
            "value": metric.value,
            "unit": metric.unit,
            "source_text": metric.raw,
            "kind": metric.kind,
            "source": "user_confirmed",
        })
    return items


def _connectivity_constraints(profile: UseCaseProfile, brief: UseCaseBrief) -> list[str]:
    text = " ".join([brief.raw_use_case, brief.refined_problem_statement, *[item.text for item in brief.assumptions]]).lower()
    constraints = []
    if "intermittent" in text or "unreliable" in text or "offline" in text:
        constraints.append("intermittent_or_unreliable_connectivity")
    constraints.extend(item for item in profile.deployment_posture if item in {"edge_and_cloud", "hybrid", "air_gapped_on_prem"})
    return list(dict.fromkeys(constraints))


def _retention(profile: UseCaseProfile) -> list[dict[str, Any]]:
    structured = profile.structured_metrics or {}
    records = []
    for key, payload in (structured.get("business_targets") or {}).items():
        if "retention" not in key:
            continue
        if isinstance(payload, dict):
            records.append({"name": key, "value": payload.get("value"), "unit": payload.get("unit"), "source_text": payload.get("raw")})
    return records


def _pricing_driver_hints(profile: UseCaseProfile) -> list[str]:
    hints = []
    for metric in profile.metrics:
        if metric.kind in {"asset_count", "business_target", "frequency", "event_volume", "telemetry", "retention"}:
            hints.append(metric.label)
    hints.extend(profile.discovery_plan.get("pricing_drivers") or [])
    return list(dict.fromkeys(str(item) for item in hints if item))
