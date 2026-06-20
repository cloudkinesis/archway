"""D27 semantic-authority guards.

These tests encode the four D27 invariants as permanent, offline, domain-blind
assertions so the categorization treadmill cannot silently restart:

  INV-2  open-world failure fails closed (honest "unclassified"), and a transport
         failure is labelled provider_unavailable, NOT structured_output_invalid.
  INV-3  the LLM's workload-family classification is authoritative — a non-catalog
         use case routes to GENERIC instead of being keyword-squeezed, while a
         supported workload still reaches its specialized family.
  INV-4  a headline event quantity with no confirmed scale input is critical.
  Anti-treadmill: no new per-intent / per-domain keyword guards may be added to the
         selector or profiler.
"""

import ast
import re
from pathlib import Path

import pytest

from app.services.open_world_understanding import (
    CanonicalCandidate,
    CanonicalWorkloadUnderstanding,
    _families_from_understanding,
)
from app.services.pricing_driver_selector import PricingDriverFamily, select_pricing_driver_family
from app.services.source_truth_pricing_compiler import _quantity_plausibility_findings
from app.services.use_case_profile import UseCaseProfile
from app.services.convergence.golden_convergence_orchestrator import _understanding_authority_findings

ROOT = Path(__file__).resolve().parents[1]


def _profile(families, capabilities=None):
    return UseCaseProfile(
        domain="x",
        workload_families=list(families),
        excluded_families=[],
        capabilities=list(capabilities or []),
        entities=[],
        signals=[],
        actions=[],
    )


# --------------------------------------------------------------------------- #
# INV-3 — LLM family classification is authoritative; no upstream keyword squeeze
# --------------------------------------------------------------------------- #
def test_inv3_non_catalog_workload_routes_to_generic_not_squeezed():
    # Food-delivery class: the model correctly says this is not one of the catalog
    # families (open_world_other). It must NOT be keyword-squeezed into IoT/anomaly.
    understanding = CanonicalWorkloadUnderstanding(
        workload_intent="real-time dynamic pricing for food delivery with demand prediction streaming",
        domain_candidates=[CanonicalCandidate(label="Real-Time Dynamic Pricing")],
        workload_family_candidates=[CanonicalCandidate(label="open_world_other")],
    )
    families = _families_from_understanding(understanding, ["stream_ingestion", "ml_inference"])
    assert families == ["web_api_application"]
    profile = _profile(families, capabilities=["stream_ingestion", "ml_inference"])
    assert select_pricing_driver_family(profile) is PricingDriverFamily.GENERIC_DIRECTIONAL


def test_inv3_label_not_in_vocabulary_is_dropped_not_forced():
    understanding = CanonicalWorkloadUnderstanding(
        workload_intent="reverse logistics refurbishment marketplace",
        workload_family_candidates=[CanonicalCandidate(label="Circular Economy Disposition Engine")],
    )
    families = _families_from_understanding(understanding, [])
    assert families == ["web_api_application"]  # unknown label dropped → generic default


def test_inv3_supported_workload_still_reaches_specialized_family():
    # The catalog must remain reachable when the model positively names a known family.
    for label, expected in [
        ("healthcare_operations_scheduling", PricingDriverFamily.HEALTHCARE_OPERATIONS_SCHEDULING),
        ("financial_fraud_detection", PricingDriverFamily.PAYMENT_FRAUD_SCORING),
        ("capital_markets_risk_engine", PricingDriverFamily.CAPITAL_MARKETS_RISK_ENGINE),
        ("industrial_iot_streaming_ml", PricingDriverFamily.INDUSTRIAL_IOT_STREAMING),
    ]:
        understanding = CanonicalWorkloadUnderstanding(
            workload_intent=label,
            workload_family_candidates=[CanonicalCandidate(label=label)],
        )
        families = _families_from_understanding(understanding, [])
        assert families == [label]
        assert select_pricing_driver_family(_profile(families)) is expected


# --------------------------------------------------------------------------- #
# INV-2 — fail closed honestly when an attempted classification is non-authoritative
# --------------------------------------------------------------------------- #
def test_inv2_attempted_failure_caps_to_internal_only():
    brief = {
        "use_case_profile": {
            "understanding_authoritative": False,
            "understanding_unavailable_reason": "EndpointConnectionError: Could not connect to the endpoint URL",
        }
    }
    findings = _understanding_authority_findings(brief)
    assert len(findings) == 1
    f = findings[0]
    assert f.code == "understanding.unavailable"
    assert f.severity == "critical"
    assert f.customer_readiness_impact == "cap_to_internal_only"
    assert "EndpointConnectionError" in f.description  # true reason surfaced verbatim


def test_inv2_authoritative_run_is_not_capped():
    brief = {"use_case_profile": {"understanding_authoritative": True, "understanding_unavailable_reason": None}}
    assert _understanding_authority_findings(brief) == []


def test_inv2_disabled_offline_mode_is_not_capped():
    # Deterministic offline mode (reason is None) is sanctioned and governed by the
    # existing readiness gates — it must NOT trip the fail-closed cap.
    brief = {"use_case_profile": {"understanding_authoritative": False, "understanding_unavailable_reason": None}}
    assert _understanding_authority_findings(brief) == []


# --------------------------------------------------------------------------- #
# INV-4 — events with no confirmed scale input are critical (scale-free)
# --------------------------------------------------------------------------- #
def test_inv4_unjustified_events_are_critical():
    findings = _quantity_plausibility_findings(
        asset_count=0, cadence_seconds=0, monthly_events=5_000_000_000,
        monthly_media_items=0, storage_gb_month=0, events_from_confirmed_input=False,
    )
    assert any(f["code"] == "quantity.missing_graph_justification" and f["severity"] == "critical" for f in findings)


def test_inv4_justified_large_events_pass_scale_free():
    # Genuinely large but confirmed-input-backed events must NOT trip — no magic ceiling.
    findings = _quantity_plausibility_findings(
        asset_count=0, cadence_seconds=0, monthly_events=50_000_000_000,
        monthly_media_items=0, storage_gb_month=0, events_from_confirmed_input=True,
    )
    assert not any(f["code"] == "quantity.missing_graph_justification" for f in findings)


# --------------------------------------------------------------------------- #
# Anti-treadmill — no new per-intent / per-domain keyword guards
# --------------------------------------------------------------------------- #
# Ratchet baseline: legacy per-intent guards on the DETERMINISTIC path that predate D27.
# They did not cause the live-path bugs (those were the silent fallback + the upstream
# family squeeze, both fixed) and removing them entails offline golden churn, so they are
# tracked here as known debt. This set may only SHRINK — any NEW guard (or a typo'd
# resurrection) fails CI. Removing a legacy guard must also delete it from this baseline.
_LEGACY_INTENT_GUARDS = {
    "app/services/pricing_driver_selector.py": {
        "_has_live_media_distribution_intent",
        "_has_document_workflow_intent",
    },
    "app/services/use_case_profile.py": {
        "_has_live_media_delivery_intent",
        "_has_document_workflow_intent",
    },
}


@pytest.mark.parametrize("rel_path", sorted(_LEGACY_INTENT_GUARDS))
def test_no_new_per_intent_or_refiner_guards(rel_path):
    source = (ROOT / rel_path).read_text()
    tree = ast.parse(source)
    guards = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and (node.name.startswith("_refine_") or re.search(r"_intent$", node.name))
    }
    new_guards = guards - _LEGACY_INTENT_GUARDS[rel_path]
    assert not new_guards, (
        f"{rel_path} introduced NEW per-intent/per-domain guard(s): {sorted(new_guards)}. "
        "D27 forbids keyword/intent special-casing in the classifier path — route unknowns "
        "to GENERIC_DIRECTIONAL via positive justification instead."
    )
    # The baseline must only shrink: a guard that no longer exists must be removed from it.
    stale = _LEGACY_INTENT_GUARDS[rel_path] - guards
    assert not stale, f"Remove now-deleted guards from the ratchet baseline for {rel_path}: {sorted(stale)}"
