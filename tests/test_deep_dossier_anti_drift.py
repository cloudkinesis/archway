"""Anti-drift coverage for generated deep dossier text."""

from __future__ import annotations

import json

from app.services.deep_dossier import DeepDossierService


def test_healthcare_deep_dossier_does_not_inherit_utility_depot_language():
    brief = {
        "title": "Healthcare OR delay prediction",
        "industry": "healthcare",
        "use_case_profile": {
            "domain": "healthcare",
            "workload_families": ["healthcare_operations_scheduling"],
            "capabilities": ["predictive_ml"],
            "actions": ["ehr_writeback_recommendation"],
            "deployment_posture": ["hybrid"],
        },
    }
    report = {
        "metadata": {
            "use_case_profile": brief["use_case_profile"],
            "customer_readiness": {"status": "directional_only", "warnings": [], "blockers": []},
            "evidence_quality": {"citation_coverage": {"passed": False}},
        },
        "evidence_items": [{"id": "ev1", "source_type": "local_policy"}],
    }
    pricing = {
        "metadata": {
            "pricing_can_be_displayed_as_headline": False,
            "pricing_ledger": {"summary": {"headline_safe": False, "procurement_ready": False}},
        },
        "line_items": [],
        "unknown_variables": ["operating_room_count"],
    }
    architectures = [{
        "mode": "production",
        "metadata": {"expected_views": ["network_private_connectivity"]},
        "selected_services": [
            {"service": "External Epic / EHR system"},
            {"service": "External OR command center"},
            {"service": "External staffing system"},
        ],
    }]

    dossier = DeepDossierService().build(
        session_id="sess_healthcare",
        brief=brief,
        report=report,
        pricing=pricing,
        architectures=architectures,
        diagrams=[],
    )

    text = json.dumps(dossier.model_dump(mode="json")).lower()
    for forbidden in (
        "asset identity",
        "depot",
        "dispatch",
        "field operations",
        "field crew",
        "iot core",
        "sitewise",
        "telemetry replay",
    ):
        assert forbidden not in text
