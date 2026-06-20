import pytest

from app.core.config import get_settings
from app.domain.source_of_truth import AwsRateBinding, CanonicalFact, CanonicalFactsLedger
from app.models.domain import AWSServiceSelection, PricingAnalysis
from app.services.architecture import _architecture_summary
from app.services.deep_dossier import _cost_range, _dossier_readiness
from app.models.domain import DossierConsistencyCheck, DossierReadinessStatus
from app.services.pricing import PricingEngine
from app.services.pricing_sanity_reviewer import PricingSanityFinding, _drop_stale_confirmed_unknown_findings
from app.services.source_truth_pricing_compiler import _generic_quantity_context, _generic_usage_dimension
from app.services.synthesis import SynthesisEngine
from tests.golden_scenarios.scenarios import GOLDEN_SCENARIOS


@pytest.mark.asyncio
async def test_pass1_exports_canonical_facts_and_pricing_ledger_for_payment_fraud():
    use_case = (
        "A regional bank wants an AWS platform to detect real-time payment fraud across 12 million card transactions per day, "
        "score events in under 250 milliseconds, queue suspicious payments for analyst review, block high-confidence fraudulent "
        "transactions after policy approval, retain audit evidence for seven years, and reduce false positives by 30 percent in the first year."
    )
    brief = SynthesisEngine().create_initial_brief(use_case)

    estimate = await PricingEngine().estimate(
        brief,
        [
            AWSServiceSelection(service="Amazon Kinesis Data Streams", purpose="stream", rationale="managed"),
            AWSServiceSelection(service="Amazon SageMaker", purpose="ml", rationale="managed"),
            AWSServiceSelection(service="Amazon S3", purpose="audit", rationale="durable"),
        ],
    )

    assert estimate.metadata["source_truth_pricing_compiler"]["enabled"] is True
    assert estimate.metadata["source_truth_pricing_compiler"]["workload_family"] == "payment_fraud_scoring"
    facts = estimate.metadata["canonical_facts"]["facts"]
    assert any(item["name"] == "transactions_per_day" and item["value"] == 12_000_000 for item in facts)
    assert "transactions_per_day" not in estimate.unknown_variables
    bindings = estimate.metadata["pricing_driver_bindings"]
    assert any(item["driver_name"] == "latency_target_ms" and item["value"] == 250 for item in bindings)
    assert any(item["driver_name"] == "peak_tps" and item["status"] == "derived" for item in bindings)
    ledger = estimate.metadata["pricing_ledger"]
    assert ledger["summary"]["procurement_ready"] is False
    assert ledger["line_items"]
    assert all(item["evidence_class"] in {"heuristic", "not_estimated", "price_catalog_referenced", "sku_tier_backed"} for item in ledger["line_items"])
    assert all(
        item["procurement_ready"] is False
        for item in ledger["line_items"]
        if float(item.get("monthly_total") or 0) > 0 and item["evidence_class"] != "sku_tier_backed"
    )


@pytest.mark.asyncio
async def test_pass1_media_separates_cdn_egress_from_edge_function_requests():
    brief = SynthesisEngine().create_initial_brief(GOLDEN_SCENARIOS["live_sports"])

    estimate = await PricingEngine().estimate(
        brief,
        [
            AWSServiceSelection(service="Amazon CloudFront", purpose="cdn", rationale="managed"),
            AWSServiceSelection(service="AWS Lambda@Edge / CloudFront Functions", purpose="edge", rationale="managed"),
            AWSServiceSelection(service="AWS Elemental MediaTailor", purpose="ads", rationale="managed"),
        ],
    )

    dimensions = estimate.metadata["service_usage_dimensions"]
    cloudfront = next(item for item in dimensions if item["service_name"] == "Amazon CloudFront")
    edge = next(item for item in dimensions if item["service_name"] == "AWS Lambda@Edge / CloudFront Functions")
    assert cloudfront["usage_name"] == "CDN data transfer out"
    assert edge["usage_name"] == "edge function invocations"
    assert cloudfront["unit"] == "GB"
    assert edge["unit"] == "requests"
    assert cloudfront["quantity"] != edge["quantity"]
    assert "concurrent_viewers" not in estimate.unknown_variables
    assert estimate.metadata["pricing_ledger"]["summary"]["headline_safe"] is False


@pytest.mark.asyncio
async def test_generic_open_world_pricing_preserves_typed_quantities_without_procurement_claims():
    use_case = (
        "A drone logistics command center coordinates 420 autonomous medical delivery drones, receives GPS and "
        "telemetry updates every 5 seconds, stores 2 KB telemetry payloads for 90 days, predicts route risks, "
        "and dispatches operational alerts."
    )
    brief = SynthesisEngine().create_initial_brief(use_case)

    estimate = await PricingEngine().estimate(
        brief,
        [
            AWSServiceSelection(service="Amazon Kinesis Data Streams", purpose="telemetry stream", rationale="managed"),
            AWSServiceSelection(service="Amazon S3", purpose="telemetry archive", rationale="durable"),
            AWSServiceSelection(service="AWS Lambda", purpose="dispatch actions", rationale="serverless"),
        ],
    )

    assert estimate.metadata["source_truth_pricing_compiler"]["mode"] == "generic_quantity_backed_directional"
    ledger = estimate.metadata["pricing_ledger"]
    assert ledger["summary"]["procurement_ready"] is False
    assert ledger["summary"]["headline_safe"] is False
    quantified = [item for item in ledger["line_items"] if item["quantity"] is not None]
    assert quantified
    assert all(item["procurement_ready"] is False for item in ledger["line_items"])
    assert any(item["service_name"] == "Amazon Kinesis Data Streams" and float(item["quantity"]) > 0 for item in quantified)
    assert any(item["service_name"] == "Amazon S3" and float(item["quantity"]) > 0 for item in quantified)
    assert any(
        item["code"] == "pricing.unsupported_family_not_estimated"
        and item["customer_readiness_impact"] == "cap_to_workshop"
        for item in estimate.metadata["pricing_sanity_findings"]
    )
    traces = [item.pricing_trace for item in estimate.line_items]
    assert any(item.get("pricing_validity") == "quantity_backed_directional" for item in traces)


@pytest.mark.asyncio
async def test_pass1_risk_marks_missing_compute_drivers_not_procurement_ready():
    brief = SynthesisEngine().create_initial_brief(GOLDEN_SCENARIOS["investment_risk"])

    estimate = await PricingEngine().estimate(
        brief,
        [
            AWSServiceSelection(service="AWS Batch", purpose="risk", rationale="managed"),
            AWSServiceSelection(service="Amazon FSx for Lustre", purpose="scratch", rationale="managed"),
            AWSServiceSelection(service="Amazon ElastiCache", purpose="cache", rationale="managed"),
        ],
    )

    assert estimate.metadata["source_truth_pricing_compiler"]["workload_family"] == "capital_markets_risk_engine"
    bindings = estimate.metadata["pricing_driver_bindings"]
    missing = {item["driver_name"] for item in bindings if item["status"] in {"missing", "assumed"}}
    assert {"monte_carlo_paths", "shared_storage_tb", "low_latency_cache_gb"} & missing
    assert estimate.metadata["pricing_ledger"]["summary"]["procurement_ready"] is False
    assert any(item["code"] == "pricing.not_procurement_ready" for item in estimate.metadata["pricing_sanity_findings"])


@pytest.mark.asyncio
async def test_pass1b_binds_cloudfront_rate_and_keeps_unquantified_media_not_estimated(monkeypatch):
    def fake_bind(self, dimension, *, region_code):
        if dimension.service_name == "Amazon CloudFront":
            return AwsRateBinding(
                service_name=dimension.service_name,
                aws_service_code=dimension.aws_service_code,
                sku="SKU-CLOUDFRONT-DTO",
                usage_type="DataTransfer-Out-Bytes",
                operation="",
                product_family="Data Transfer",
                rate_code="RATE-CLOUDFRONT-DTO",
                unit="GB",
                begin_range="0",
                end_range="Inf",
                price_per_unit="0.01",
                currency="USD",
                effective_date="2026-01-01T00:00:00Z",
                source="price_list_query_api",
                confidence="high",
                binding_status="bound",
                notes=["test bound rate"],
            )
        return AwsRateBinding(
            service_name=dimension.service_name,
            aws_service_code=dimension.aws_service_code,
            unit=dimension.unit,
            source="price_list_query_api",
            confidence="low",
            binding_status="not_found",
            notes=["test no exact rate"],
        )

    monkeypatch.setattr("app.services.aws_rate_binding_engine.AwsRateBindingEngine.bind", fake_bind)
    brief = SynthesisEngine().create_initial_brief(GOLDEN_SCENARIOS["live_sports"])

    estimate = await PricingEngine().estimate(
        brief,
        [
            AWSServiceSelection(service="Amazon CloudFront", purpose="cdn", rationale="managed"),
            AWSServiceSelection(service="AWS Lambda@Edge / CloudFront Functions", purpose="edge", rationale="managed"),
            AWSServiceSelection(service="AWS Elemental MediaLive", purpose="encoding", rationale="managed"),
            AWSServiceSelection(service="Amazon S3", purpose="archive", rationale="durable"),
        ],
    )

    ledger = estimate.metadata["pricing_ledger"]
    cloudfront = next(item for item in ledger["line_items"] if item["service_name"] == "Amazon CloudFront")
    s3 = next(item for item in ledger["line_items"] if item["service_name"] == "Amazon S3")
    assert cloudfront["evidence_class"] == "sku_tier_backed"
    assert cloudfront["procurement_ready"] is False
    assert "usage quantities are assumed" in " ".join(cloudfront["limitations"])
    assert cloudfront["unit_price"] == "0.01"
    assert s3["evidence_class"] == "not_estimated"
    assert s3["monthly_total"] is None
    assert next(line for line in estimate.line_items if line.service == "Amazon S3").expected_monthly_usd == 0


@pytest.mark.asyncio
async def test_pass1b_media_assumption_mapping_is_specific(monkeypatch):
    monkeypatch.setattr(
        "app.services.aws_rate_binding_engine.AwsRateBindingEngine.bind",
        lambda self, dimension, *, region_code: AwsRateBinding(
            service_name=dimension.service_name,
            aws_service_code=dimension.aws_service_code,
            unit=dimension.unit,
            binding_status="not_found",
            notes=["test no exact rate"],
        ),
    )
    brief = SynthesisEngine().create_initial_brief(GOLDEN_SCENARIOS["live_sports"])

    estimate = await PricingEngine().estimate(
        brief,
        [
            AWSServiceSelection(service="Amazon CloudFront", purpose="cdn", rationale="managed"),
            AWSServiceSelection(service="AWS Elemental MediaLive", purpose="encoding", rationale="managed"),
        ],
    )

    assumptions = {item["id"]: item for item in estimate.metadata["assumption_ledger"]["assumptions"]}
    bindings = {item["driver_name"]: item for item in estimate.metadata["pricing_driver_bindings"]}
    viewer_assumption = assumptions[bindings["average_viewer_hours_per_month"]["assumption_id"]]
    channel_assumption = assumptions[bindings["live_channel_count"]["assumption_id"]]
    assert "viewer engagement" in viewer_assumption["statement"].lower()
    assert "bitrate" not in viewer_assumption["statement"].lower()
    assert "one live channel" in channel_assumption["statement"].lower()
    medialive = next(item for item in estimate.metadata["service_usage_dimensions"] if item["service_name"] == "AWS Elemental MediaLive")
    assert set(medialive["assumption_ids"]) == {bindings["live_channel_count"]["assumption_id"], bindings["event_hours_per_month"]["assumption_id"]}


def test_pass1b_dossier_cost_range_suppresses_unsafe_headline():
    pricing = {
        "low_monthly_usd": 1,
        "expected_monthly_usd": 2,
        "high_monthly_usd": 3,
        "metadata": {"pricing_can_be_displayed_as_headline": False},
    }

    text = _cost_range(pricing)

    assert "not headline-safe" in text
    assert "$1-$3" not in text


def test_generic_quantity_graph_uses_direct_tb_per_month_storage_without_domain_terms():
    facts = CanonicalFactsLedger(facts=[
        CanonicalFact(
            name="explicit_quantity_tb_artifact_data_per_month",
            value=2.5,
            unit="tb_artifact_data_per_month",
            source="user_input",
            source_text="2.5 TB artifact data per month",
            confidence="high",
            used_by=["pricing"],
            validation_status="confirmed",
        ),
        CanonicalFact(
            name="retention_years",
            value=4,
            unit="years",
            source="user_input",
            source_text="4-year retention",
            confidence="high",
            used_by=["pricing"],
            validation_status="confirmed",
        ),
    ])

    context = _generic_quantity_context(facts)

    assert context["storage_gb_month_by_class"]["all"] == 2.5 * 1024 * 48
    assert context["storage_gb_month"] == 2.5 * 1024 * 48


def test_generic_s3_dimension_prefers_storage_gb_month_over_record_count_for_direct_storage():
    facts = CanonicalFactsLedger(facts=[
        CanonicalFact(
            name="explicit_quantity_records_per_month",
            value=10_000,
            unit="records_per_month",
            source="user_input",
            source_text="10,000 records per month",
            confidence="high",
            used_by=["pricing"],
            validation_status="confirmed",
        ),
        CanonicalFact(
            name="explicit_quantity_tb_evidence_per_month",
            value=1,
            unit="tb_evidence_per_month",
            source="user_input",
            source_text="1 TB evidence per month",
            confidence="high",
            used_by=["pricing"],
            validation_status="confirmed",
        ),
        CanonicalFact(
            name="retention_years",
            value=2,
            unit="years",
            source="user_input",
            source_text="2-year retention",
            confidence="high",
            used_by=["pricing"],
            validation_status="confirmed",
        ),
    ])

    dimension = _generic_usage_dimension("Amazon S3", None, "us-east-1", facts=facts)

    assert dimension.unit == "GB-month"
    assert dimension.usage_name == "derived object/evidence retention"
    assert dimension.quantity == 24 * 1024


def test_pass1c_drops_stale_confirmed_fact_unknown_finding():
    pricing = PricingAnalysis(
        region="us-east-1",
        low_monthly_usd=0,
        expected_monthly_usd=0,
        high_monthly_usd=0,
        line_items=[],
        main_cost_drivers=[],
        cost_optimization_recommendations=[],
        unknown_variables=["region_traffic_mix"],
        evidence_items=[],
        metadata={
            "canonical_facts": {
                "facts": [
                    {"name": "concurrent_viewers", "value": 25000000},
                    {"name": "region_traffic_mix", "value": None},
                ]
            }
        },
    )
    findings = [
        PricingSanityFinding(
            severity="critical",
            issue="Confirmed Fact Listed As Unknown: concurrent_viewers",
            evidence_from_use_case="25 million concurrent viewers",
            impacted_pricing_driver="concurrent_viewers",
            recommended_fix="Remove concurrent_viewers from unknown variables.",
        ),
        PricingSanityFinding(
            severity="critical",
            issue="Confirmed Fact Listed As Unknown: region_traffic_mix",
            evidence_from_use_case="region traffic mix is still unknown",
            impacted_pricing_driver="region_traffic_mix",
            recommended_fix="Confirm region_traffic_mix.",
        ),
    ]

    filtered = _drop_stale_confirmed_unknown_findings(findings, pricing)

    assert [item.impacted_pricing_driver for item in filtered] == ["region_traffic_mix"]


@pytest.mark.asyncio
async def test_pass1c_ambiguous_candidate_rate_is_not_used_for_monthly_total(monkeypatch):
    def fake_bind(self, dimension, *, region_code):
        return AwsRateBinding(
            service_name=dimension.service_name,
            aws_service_code=dimension.aws_service_code,
            sku="SKU-CANDIDATE",
            usage_type="DataTransfer-Out-Bytes",
            operation="",
            product_family="Data Transfer",
            rate_code="RATE-CANDIDATE",
            unit=dimension.unit,
            price_per_unit="0.01",
            source="price_list_query_api",
            confidence="medium",
            binding_status="ambiguous",
            notes=["multiple candidate rates"],
        )

    monkeypatch.setattr("app.services.aws_rate_binding_engine.AwsRateBindingEngine.bind", fake_bind)
    brief = SynthesisEngine().create_initial_brief(GOLDEN_SCENARIOS["live_sports"])

    estimate = await PricingEngine().estimate(
        brief,
        [AWSServiceSelection(service="Amazon CloudFront", purpose="cdn", rationale="managed")],
    )

    ledger_line = next(item for item in estimate.metadata["pricing_ledger"]["line_items"] if item["service_name"] == "Amazon CloudFront")
    trace = next(line.pricing_trace for line in estimate.line_items if line.service == "Amazon CloudFront")
    assert ledger_line["evidence_class"] == "price_catalog_referenced"
    assert "not used for monthly_total" in " ".join(ledger_line["limitations"])
    assert trace["candidate_rate_used_for_total"] is False
    assert trace["candidate_sku"] == "SKU-CANDIDATE"


@pytest.mark.asyncio
async def test_pass1c_not_found_media_rate_remains_heuristic_not_catalog_referenced(monkeypatch):
    def fake_bind(self, dimension, *, region_code):
        return AwsRateBinding(
            service_name=dimension.service_name,
            aws_service_code=dimension.aws_service_code,
            unit=dimension.unit,
            source="price_list_query_api",
            confidence="low",
            binding_status="not_found",
            notes=["no exact test rate"],
        )

    monkeypatch.setattr("app.services.aws_rate_binding_engine.AwsRateBindingEngine.bind", fake_bind)
    brief = SynthesisEngine().create_initial_brief(GOLDEN_SCENARIOS["live_sports"])

    estimate = await PricingEngine().estimate(
        brief,
        [AWSServiceSelection(service="AWS Elemental MediaTailor", purpose="ads", rationale="managed")],
    )

    ledger_line = next(item for item in estimate.metadata["pricing_ledger"]["line_items"] if item["service_name"] == "AWS Elemental MediaTailor")
    assert ledger_line["evidence_class"] == "heuristic"
    assert "No exact AWS SKU/tier rate was found" in " ".join(ledger_line["limitations"])


def test_pass1c_dossier_readiness_respects_internal_only_status():
    status = _dossier_readiness(
        {"status": "internal_only"},
        DossierConsistencyCheck(passed=True),
        pricing_score=7,
        architecture_score=9,
    )

    assert status == DossierReadinessStatus.internal_only


@pytest.mark.asyncio
async def test_generic_open_world_pricing_uses_authority_resolver_when_live_enabled(monkeypatch):
    monkeypatch.setenv("ARCHWAY_ENABLE_AWS_PRICING_MCP", "true")
    get_settings.cache_clear()
    calls = []

    def fake_bind(self, dimension, *, region_code):
        calls.append((dimension.service_name, dimension.required_rate_dimensions))
        return AwsRateBinding(
            service_name=dimension.service_name,
            aws_service_code=dimension.aws_service_code,
            sku="SKU-KINESIS",
            usage_type="USE1-PUT-Units",
            operation="PutRecords",
            product_family="Amazon Kinesis Data Streams",
            rate_code="RATE-KINESIS",
            unit="requests",
            price_per_unit="0.01",
            source="price_list_query_api",
            confidence="high",
            binding_status="bound",
            notes=["test authoritative rate"],
        )

    monkeypatch.setattr("app.services.aws_rate_binding_engine.AwsRateBindingEngine.bind", fake_bind)
    brief = SynthesisEngine().create_initial_brief(
        "Monitor industrial telemetry with 1,000,000 events per month and retain audit evidence for 3 years."
    )

    estimate = await PricingEngine().estimate(
        brief,
        [AWSServiceSelection(service="Amazon Kinesis Data Streams", purpose="stream telemetry", rationale="managed stream")],
    )

    assert calls
    assert calls[0][0] == "Amazon Kinesis Data Streams"
    assert calls[0][1]["productFamily"] == "Kinesis Streams"
    binding = estimate.metadata["aws_rate_bindings"][0]
    assert binding["binding_status"] == "bound"
    assert binding["source"] == "price_list_query_api"
    assert estimate.metadata["service_usage_dimensions"][0]["required_rate_dimensions"]["productFamily"] == "Kinesis Streams"


@pytest.mark.asyncio
async def test_generic_open_world_pricing_stays_offline_without_live_authority(monkeypatch):
    monkeypatch.setenv("ARCHWAY_ENABLE_AWS_PRICING_MCP", "false")
    monkeypatch.delenv("ARCHWAY_AWS_PRICING_MCP_COMMAND", raising=False)
    monkeypatch.delenv("ARCHWAY_AWS_PRICING_MCP_URL", raising=False)
    get_settings.cache_clear()

    def fail_bind(self, dimension, *, region_code):
        raise AssertionError("generic pricing must not call live authority when pricing authority is disabled")

    monkeypatch.setattr("app.services.aws_rate_binding_engine.AwsRateBindingEngine.bind", fail_bind)
    brief = SynthesisEngine().create_initial_brief(
        "Monitor 1,000 industrial machines with telemetry every 30 seconds and retain audit evidence for 3 years."
    )

    estimate = await PricingEngine().estimate(
        brief,
        [AWSServiceSelection(service="Amazon Kinesis Data Streams", purpose="stream telemetry", rationale="managed stream")],
    )

    binding = estimate.metadata["aws_rate_bindings"][0]
    assert binding["binding_status"] == "unsupported"
    assert binding["source"] == "unbound"
    assert "Live pricing authority is disabled" in " ".join(binding["notes"])


def test_architecture_summary_drops_low_signal_latency_fragments():
    summary = _architecture_summary(
        "Validate bounded workflow",
        context={
            "latency_slos": [{"target": "within 2 minutes, seconds, unknown"}],
            "quantities": ["18,500 assets", "10 seconds", "seconds", "unknown", "10 seconds"],
        },
        production=False,
    )

    assert "within 2 minutes, seconds, unknown" not in summary
    assert "within 2 minutes" in summary
    assert "seconds, unknown" not in summary
    assert "18,500 assets" in summary
