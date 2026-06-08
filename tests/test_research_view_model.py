import json

from app.services.research_view_model import build_research_view_model


def _report(domain: str, families: list[str], interpretation: str = "Design an AWS enterprise analytics workload."):
    return {
        "session_id": "sess_view_model",
        "generated_at": "2026-06-07T00:00:00Z",
        "executive_verdict": "Proceed with caution.",
        "proceed_recommendation": "proceed_with_caution",
        "use_case_interpretation": interpretation,
        "assumptions": [],
        "recommended_poc": "Start with a scoped POC.",
        "recommended_production_direction": "Harden with multi-AZ production controls.",
        "aws_service_recommendations": [
            {
                "service": "Amazon Kinesis Data Streams",
                "purpose": "stream ingestion for workload events",
                "rationale": "Selected for managed event ingestion.",
                "alternatives_considered": ["Amazon MSK"],
            }
        ],
        "risks": [],
        "evidence_items": [
            {
                "id": "ev_1234567890",
                "source_type": "aws_docs",
                "title": "AWS service guidance",
                "quote_or_summary": "AWS guidance summary.",
                "confidence": "high",
            }
        ],
        "citation_coverage": {"coverage_percent": 100},
        "metadata": {
            "use_case_profile": {"domain": domain, "workload_families": families},
            "workload_families": families,
            "customer_readiness": {"status": "directional_only"},
            "evidence_quality": {"evidence_authority": "official"},
            "competitor_scan": {
                "tavily_enabled": True,
                "competitor_scan_enabled": True,
                "session_budget": 4,
                "queries_attempted": 2,
                "queries_executed": 2,
                "results_returned": 2,
                "results_used": 2,
                "query_plan": ["market competitors", "commercial alternatives"],
            },
        },
        "competitor_analysis": "Competitor / market scan completed with Tavily.\n\n## Market signals\n- Competitor source: packaged workflow platform.\n\n## AWS positioning implication\n- Keep the design AWS-native and governed.",
    }


def _pricing(headline_safe: bool = False):
    return {
        "region": "us-east-1",
        "low_monthly_usd": 10,
        "expected_monthly_usd": 20,
        "high_monthly_usd": 40,
        "unknown_variables": ["event_rate", "retention"],
        "line_items": [
            {
                "service": "Amazon Kinesis Data Streams",
                "unit_basis": "event ingestion",
                "expected_monthly_usd": 20,
                "pricing_trace": {
                    "calculation_source": "deterministic_model_with_official_offer_catalog",
                    "price_list_evidence_id": "ev_price",
                    "quantity": 1000,
                    "unit": "events",
                },
            }
        ],
        "metadata": {
            "pricing_can_be_displayed_as_headline": headline_safe,
            "pricing_maturity": "pricing_directional_with_assumptions",
            "pricing_ledger": {"summary": {"procurement_ready": False, "pricing_page_or_mcp_backed_subtotal": 20}},
        },
    }


def test_research_view_model_uses_healthcare_profile_without_losing_or_language():
    report = _report(
        "healthcare",
        ["healthcare_operations_scheduling", "surgical_scheduling_prediction"],
        "Hospital OR scheduling with Epic integration and PHI controls.",
    )

    view_model = build_research_view_model("sess_health", report, None, _pricing(), None)
    rendered = view_model.model_dump_json() if view_model else ""

    assert "operating rooms" in rendered
    assert "EHR writeback attempts/day" in rendered
    assert "patient-identifiable video" in rendered


def test_research_view_model_does_not_leak_healthcare_terms_into_telecom():
    report = _report(
        "telecommunications",
        ["telecom_network_analytics", "cdr_congestion_prediction"],
        "Telecom operator migrates HBase/HDFS/Spark CDR analytics with OSS/BSS integration and QoS reporting.",
    )

    view_model = build_research_view_model("sess_telco", report, None, _pricing(), None)
    rendered = view_model.model_dump_json() if view_model else ""

    assert "OSS/BSS" in rendered
    assert "HBase read QPS" in rendered
    assert "network events/sec" in rendered
    assert "operating rooms" not in rendered
    assert "EHR" not in rendered
    assert "patient-identifiable video" not in rendered
    assert "External healthcare systems" not in rendered


def test_research_view_model_generic_profile_stays_neutral_and_hides_raw_evidence_ids():
    report = _report("retail", ["web_api_application"], "Retail order-status assistant with support workflow integration.")

    view_model = build_research_view_model("sess_generic", report, None, _pricing(), None)
    assert view_model is not None
    default_surface = {
        "executive_briefing": view_model.executive_briefing.model_dump(),
        "overview": view_model.overview.model_dump(),
        "architecture": view_model.architecture_rationale.model_dump(),
        "pricing_poc": view_model.pricing_poc.model_dump(),
        "competitor_scan": view_model.competitor_scan.model_dump(),
        "top_sources": [item.model_dump() for item in view_model.evidence_summary.top_sources],
    }
    rendered = json.dumps(default_surface)

    assert "operating rooms" not in rendered
    assert "EHR" not in rendered
    assert "PHI" not in rendered
    assert "patient-identifiable video" not in rendered
    assert "ev_1234567890" not in rendered


def test_pricing_headline_unsafe_estimate_is_withheld_and_basis_is_visible():
    report = _report("retail", ["web_api_application"])
    view_model = build_research_view_model("sess_pricing", report, None, _pricing(headline_safe=False), None)

    assert view_model is not None
    assert view_model.pricing_poc.monthly_expected == "Withheld from headline"
    assert view_model.pricing_poc.confidence == "Directional"
    assert view_model.pricing_poc.line_items[0].pricing_basis == "AWS catalog-referenced"
    assert any("withheld" in item.lower() for item in view_model.pricing_poc.readiness_findings)


def test_pricing_headline_missing_safety_flag_fails_closed():
    report = _report("retail", ["web_api_application"])
    pricing = _pricing(headline_safe=True)
    pricing["metadata"].pop("pricing_can_be_displayed_as_headline")

    view_model = build_research_view_model("sess_pricing_missing_flag", report, None, pricing, None)

    assert view_model is not None
    assert view_model.pricing_poc.headline_safe is False
    assert view_model.pricing_poc.monthly_expected == "Withheld from headline"
    assert any("not headline-safe" in item.lower() for item in view_model.pricing_poc.readiness_findings)
