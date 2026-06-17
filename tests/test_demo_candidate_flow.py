from __future__ import annotations

from pathlib import Path

from app.services.agentic.candidate_client_flow import build_client_facing_plan
from app.services.artifact_linter import lint_markdown
from app.services.client_pack import client_pack_files
from app.services.deep_dossier import DeepDossierService


def _base_payload(profile: dict) -> dict:
    brief = {
        "title": "Open-world Demo Case",
        "industry": "unconfirmed",
        "refined_problem_statement": "Design an AWS architecture for a novel operational workflow.",
        "poc_scope": "Validate the core workflow with representative data.",
        "production_scope": "Harden the workflow with governed operations.",
        "assumptions": [],
        "open_questions": [{"text": "What scale and latency targets should be confirmed?"}],
        "use_case_profile": profile,
    }
    report = {
        "metadata": {
            "use_case_profile": profile,
            "customer_readiness": {"status": "directional_only", "warnings": [], "blockers": []},
            "evidence_quality": {
                "evidence_authority": "strong",
                "aws_docs_available": True,
                "aws_pricing_available": True,
                "customer_ready": True,
            },
        },
        "citation_coverage": {"coverage_percent": 100.0, "passed": True},
        "evidence_items": [{"id": "ev1", "source_type": "aws_docs"}],
        "recommended_production_direction": "A governed AWS-native candidate path with explicit validation gates.",
    }
    pricing = {
        "region": "us-east-1",
        "low_monthly_usd": 1000.0,
        "expected_monthly_usd": 2000.0,
        "high_monthly_usd": 3000.0,
        "line_items": [],
        "main_cost_drivers": ["assumed_monthly_events=10000"],
        "unknown_variables": [],
        "metadata": {
            "pricing_can_be_displayed_as_headline": True,
            "pricing_ledger": {"summary": {"headline_safe": True, "procurement_ready": True}},
            "pricing_driver_closure": {"missing_drivers": [], "procurement_ready": True},
        },
    }
    architectures = [{
        "mode": "production",
        "title": "Production Architecture",
        "summary": "Deterministic fallback architecture for the workflow.",
        "metadata": {"expected_views": []},
        "selected_services": [{
            "service": "Amazon API Gateway",
            "purpose": "Controlled API entry point",
            "rationale": "It owns the external request boundary.",
            "alternatives_considered": ["Elastic Load Balancing"],
        }],
    }]
    diagrams = [{
        "mode": "production",
        "diagrams": [{
            "view_id": "production_logical_service_flow",
            "format_paths": {"svg": "diagrams/production/arch_1/production_logical_service_flow/diagram.svg"},
        }],
    }]
    dossier = DeepDossierService().build(
        session_id="sess_demo_candidate",
        brief=brief,
        report=report,
        pricing=pricing,
        architectures=architectures,
        diagrams=diagrams,
    )
    return {
        "brief": brief,
        "report": report,
        "pricing": pricing,
        "architectures": architectures,
        "diagrams": diagrams,
        "dossier": dossier,
    }


def _candidate_traces() -> dict:
    live_call = {"provider": "bedrock", "status": "accepted"}
    return {
        "architecture": {
            "enabled": True,
            "provider": "bedrock",
            "live_call": live_call,
            "proposal": {
                "title": "Candidate workflow architecture",
                "candidate_components": [{
                    "component_id": "edge_signal_filter",
                    "label": "Edge Signal Filter",
                    "service_hint": "Amazon Kinesis Video Streams",
                    "role": "Filters incoming media and telemetry before downstream analysis.",
                    "confidence_label": "medium",
                    "accepted_status": "needs_review",
                }],
                "candidate_flows": [{
                    "flow_id": "signal_to_analysis",
                    "source": "Edge Signal Filter",
                    "target": "Analysis Service",
                    "flow_type": "streaming ingest",
                    "data_class": "operational media",
                    "security_controls": ["identity", "audit"],
                    "accepted_status": "needs_review",
                }],
                "security_controls": [{
                    "control_id": "identity_boundary",
                    "control_type": "identity",
                    "rationale": "Each producer and processing role needs scoped identity permissions.",
                    "accepted_status": "needs_review",
                }],
                "reliability_controls": [],
                "observability_controls": [],
                "assumptions": ["Monthly event volume is a planning assumption until confirmed."],
                "risks": ["Streaming media retention and retry windows must be reviewed."],
                "open_questions": ["Which sites require continuous collection versus scheduled sampling?"],
            },
        },
        "pricing": {
            "enabled": True,
            "provider": "bedrock",
            "live_call": live_call,
            "proposal": {
                "usage_dimensions": [{
                    "dimension_id": "media_hours",
                    "service_name": "Amazon Kinesis Video Streams",
                    "usage_name": "Media hours",
                    "unit": "hours",
                    "required_customer_drivers": ["monthly_media_hours", "retention_days"],
                    "binding_label": "missing_quantity",
                    "ambiguity_reason": "Customer must confirm monthly media hours and retention.",
                }],
                "required_drivers": [{
                    "driver_key": "monthly_media_hours",
                    "display_label": "Monthly media hours",
                    "unit": "hours",
                    "status": "missing",
                    "reason": "Required to estimate video ingestion and storage.",
                }],
                "scenario_profiles": [{
                    "profile_id": "pilot",
                    "label": "Pilot scenario",
                    "assumptions": ["One region and representative site count."],
                }],
                "not_estimated_reasons": ["Exact media volume is not confirmed."],
                "ambiguities": [],
                "conflicts": [],
            },
        },
        "diagram": {
            "enabled": True,
            "provider": "bedrock",
            "live_call": live_call,
            "proposal": {
                "candidate_views": [{
                    "view_id": "operator_journey",
                    "display_label": "Operator journey",
                    "purpose": "Shows how a human reviews alerts and exceptions.",
                    "accepted_status": "unsupported",
                }],
                "missing_view_requests": [],
                "unsupported_view_requests": [{
                    "requested_view_type": "field_exception_view",
                    "disclosure_text": "This view is useful for discussion but is not rendered by the current compiler.",
                }],
            },
        },
        "reviewer": {
            "enabled": True,
            "provider": "bedrock",
            "live_call": live_call,
            "accepted_findings": [{
                "severity": "warning",
                "category": "missing_driver",
                "message": "Confirm media volume before presenting budget numbers.",
                "suggested_repair": "Ask for monthly media hours and retention period.",
            }],
        },
    }


def test_candidate_client_plan_requires_open_world_and_live_architecture_candidate():
    profile = {
        "profile_source": "open_world_understanding",
        "workload_families": ["web_api_application"],
        "open_world_understanding": {"confidence": "medium"},
    }
    plan = build_client_facing_plan(
        profile_metadata=profile,
        architecture_candidate_trace=_candidate_traces()["architecture"],
    )
    assert plan.tier == "candidate"
    assert plan.readiness_cap == "demo_ready"

    no_live = _candidate_traces()["architecture"] | {"live_call": {"provider": "bedrock", "status": "failed"}}
    assert build_client_facing_plan(profile_metadata=profile, architecture_candidate_trace=no_live).tier == "deterministic"
    known_profile = {"profile_source": "deterministic", "workload_families": ["web_api_application"]}
    assert build_client_facing_plan(profile_metadata=known_profile, architecture_candidate_trace=_candidate_traces()["architecture"]).tier == "deterministic"


def test_candidate_selector_has_no_domain_specific_treadmill_terms():
    source = Path("app/services/agentic/candidate_client_flow.py").read_text(encoding="utf-8").lower()
    forbidden = ["aquaculture", "wildfire", "airport", "healthcare", "legal", "telecom"]
    assert [term for term in forbidden if term in source] == []


def test_known_profile_client_pack_is_byte_stable_with_candidate_traces():
    payload = _base_payload({"profile_source": "deterministic", "workload_families": ["web_api_application"]})
    base = client_pack_files(
        session_name="Known Case",
        brief=payload["brief"],
        report=payload["report"],
        pricing=payload["pricing"],
        architectures=payload["architectures"],
        diagrams=payload["diagrams"],
        deep_dossier=payload["dossier"],
        decision_records=[],
    )
    with_traces = client_pack_files(
        session_name="Known Case",
        brief=payload["brief"],
        report=payload["report"],
        pricing=payload["pricing"],
        architectures=payload["architectures"],
        diagrams=payload["diagrams"],
        deep_dossier=payload["dossier"],
        decision_records=[],
        candidate_traces=_candidate_traces(),
    )
    assert with_traces == base


def test_open_world_candidate_client_pack_is_labeled_lint_clean_and_capped():
    profile = {
        "profile_source": "open_world_understanding",
        "workload_families": ["web_api_application"],
        "open_world_understanding": {"confidence": "medium"},
    }
    payload = _base_payload(profile)
    client = client_pack_files(
        session_name="Novel Case",
        brief=payload["brief"],
        report=payload["report"],
        pricing=payload["pricing"],
        architectures=payload["architectures"],
        diagrams=payload["diagrams"],
        deep_dossier=payload["dossier"],
        decision_records=[],
        candidate_traces=_candidate_traces(),
    )

    assert "**Readiness tier:** Demo ready" in client["01-executive-memo.md"]
    assert "Candidate architecture" in client["03-architecture-summary.md"]
    assert "Edge Signal Filter" in client["03-architecture-summary.md"]
    assert "Candidate pricing dimensions" in client["04-pricing-summary.md"]
    assert "Monthly media hours" in client["04-pricing-summary.md"]
    assert "Proposed views not yet natively rendered" in client["07-diagrams-index.md"]
    assert "Candidate review observations" in client["05-risks-and-gates.md"]

    client_text = "\n".join(client.values())
    assert "model_proposed" not in client_text
    assert "agent_architecture_candidate" not in client_text
    assert "agent_pricing_dimension" not in client_text
    assert "procurement-ready: yes" not in client_text.lower()

    for path, content in client.items():
        assert lint_markdown(content, f"client_pack/{path}") == []
