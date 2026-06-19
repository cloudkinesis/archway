from __future__ import annotations

from decimal import Decimal

from app.core.config import get_settings
from app.domain.source_of_truth import AwsRateBinding, PricingLedger, PricingLedgerSummary, ServiceUsageDimension
from app.services.pricing_authority_resolver import PricingAuthorityResolver
from app.services.source_truth_pricing_compiler import _ledger_limitations, _pricing_ledger


def _dimension(**overrides) -> ServiceUsageDimension:
    payload = {
        "service_name": "Example AWS Service",
        "usage_name": "storage gb",
        "aws_service_code": "ExampleService",
        "quantity": Decimal("100"),
        "unit": "GB",
        "formula": "confirmed_assets * payload_gb",
    }
    payload.update(overrides)
    return ServiceUsageDimension(**payload)


def _price_list(*, sku: str = "SKU1", price: str = "0.023", unit: str = "GB", product_family: str = "Storage"):
    return {
        "PriceList": [
            {
                "product": {
                    "sku": sku,
                    "productFamily": product_family,
                    "attributes": {
                        "regionCode": "us-east-1",
                        "usagetype": "USE1-Storage",
                        "operation": "Storage",
                    },
                },
                "terms": {
                    "OnDemand": {
                        f"{sku}.JRTCKXETXF": {
                            "sku": sku,
                            "effectiveDate": "2026-01-01T00:00:00Z",
                            "priceDimensions": {
                                f"{sku}.JRTCKXETXF.6YS6EN2CT7": {
                                    "unit": unit,
                                    "beginRange": "0",
                                    "endRange": "Inf",
                                    "pricePerUnit": {"USD": price},
                                }
                            },
                        }
                    }
                },
            }
        ]
    }


def test_pricing_authority_resolver_binds_single_structured_mcp_rate(monkeypatch):
    monkeypatch.setenv("ARCHWAY_ENABLE_AWS_PRICING_MCP", "true")
    monkeypatch.setenv("ARCHWAY_AWS_PRICING_MCP_COMMAND", "fake-mcp")
    get_settings.cache_clear()
    monkeypatch.setattr("app.services.pricing_authority_resolver._resolved_mcp_command", lambda command: "fake-mcp")
    monkeypatch.setattr(
        "app.services.pricing_authority_resolver._call_aws_labs_pricing_mcp",
        lambda dimension, region_code, **kwargs: {"content": [{"type": "text", "text": __import__("json").dumps(_price_list())}]},
    )
    monkeypatch.setattr(
        "app.services.pricing_authority_resolver._get_products",
        lambda dimension, region_code: (_ for _ in ()).throw(AssertionError("query API should not be called")),
    )

    binding = PricingAuthorityResolver().resolve(_dimension(), region_code="us-east-1")

    assert binding.binding_status == "bound"
    assert binding.source == "pricing_mcp"
    assert binding.sku == "SKU1"
    assert binding.price_per_unit == Decimal("0.023")
    assert "AWS Pricing MCP" in " ".join(binding.notes)


def test_pricing_authority_resolver_rejects_unstructured_mcp_text_and_falls_back(monkeypatch):
    monkeypatch.setenv("ARCHWAY_ENABLE_AWS_PRICING_MCP", "true")
    monkeypatch.setenv("ARCHWAY_AWS_PRICING_MCP_COMMAND", "fake-mcp")
    get_settings.cache_clear()
    monkeypatch.setattr("app.services.pricing_authority_resolver._resolved_mcp_command", lambda command: "fake-mcp")
    monkeypatch.setattr(
        "app.services.pricing_authority_resolver._call_aws_labs_pricing_mcp",
        lambda dimension, region_code, **kwargs: {"content": [{"type": "text", "text": "Storage is usually charged per GB-month."}]},
    )
    monkeypatch.setattr(
        "app.services.pricing_authority_resolver._get_products",
        lambda dimension, region_code: _price_list(sku="SKU2", price="0.03"),
    )

    binding = PricingAuthorityResolver().resolve(_dimension(), region_code="us-east-1")

    assert binding.binding_status == "bound"
    assert binding.source == "price_list_query_api"
    assert binding.sku == "SKU2"
    assert any("text summaries are not rate authority" in note for note in binding.notes)


def test_pricing_authority_resolver_preflights_missing_mcp_command_and_falls_back(monkeypatch):
    monkeypatch.setenv("ARCHWAY_ENABLE_AWS_PRICING_MCP", "true")
    monkeypatch.setenv("ARCHWAY_AWS_PRICING_MCP_COMMAND", "/missing/bin/uvx")
    get_settings.cache_clear()
    monkeypatch.setattr("app.services.pricing_authority_resolver._get_products", lambda dimension, region_code: _price_list())

    binding = PricingAuthorityResolver().resolve(_dimension(), region_code="us-east-1")

    assert binding.binding_status == "bound"
    assert binding.source == "price_list_query_api"
    assert any("configured but not executable" in note for note in binding.notes)


def test_pricing_authority_resolver_does_not_choose_ambiguous_rates(monkeypatch):
    monkeypatch.delenv("ARCHWAY_AWS_PRICING_MCP_COMMAND", raising=False)
    monkeypatch.setenv("ARCHWAY_ENABLE_AWS_PRICING_MCP", "false")
    get_settings.cache_clear()
    payload = _price_list(sku="SKU1", price="0.01")
    payload["PriceList"].append(_price_list(sku="SKU2", price="0.02")["PriceList"][0])
    monkeypatch.setattr("app.services.pricing_authority_resolver._get_products", lambda dimension, region_code: payload)

    binding = PricingAuthorityResolver().resolve(_dimension(), region_code="us-east-1")

    assert binding.binding_status == "ambiguous"
    assert binding.confidence == "medium"
    assert any("did not silently choose" in note for note in binding.notes)


def test_pricing_authority_resolver_matches_compact_price_list_request_units(monkeypatch):
    monkeypatch.delenv("ARCHWAY_AWS_PRICING_MCP_COMMAND", raising=False)
    monkeypatch.setenv("ARCHWAY_ENABLE_AWS_PRICING_MCP", "false")
    get_settings.cache_clear()
    payload = _price_list(sku="SKU-PUT", price="0.000000014", unit="PutRequest", product_family="Kinesis Streams")
    product = payload["PriceList"][0]["product"]
    product["attributes"]["usagetype"] = "PutRequestPayloadUnits"
    product["attributes"]["operation"] = "PutRequest"
    monkeypatch.setattr("app.services.pricing_authority_resolver._get_products", lambda dimension, region_code: payload)

    binding = PricingAuthorityResolver().resolve(
        _dimension(
            service_name="Amazon Kinesis Data Streams",
            usage_name="PUT request payload units for telemetry events",
            aws_service_code="AmazonKinesis",
            unit="requests",
            required_rate_dimensions={"productFamily": "Kinesis Streams"},
        ),
        region_code="us-east-1",
    )

    assert binding.binding_status == "bound"
    assert binding.source == "price_list_query_api"
    assert binding.usage_type == "PutRequestPayloadUnits"
    assert binding.unit == "PutRequest"


def test_bound_rate_with_assumed_quantity_is_not_procurement_ready():
    dimension = _dimension(assumption_ids=["asmp_1"])
    rate = AwsRateBinding(
        service_name=dimension.service_name,
        aws_service_code=dimension.aws_service_code,
        sku="SKU1",
        usage_type="USE1-Storage",
        operation="Storage",
        product_family="Storage",
        rate_code="RATE1",
        unit="GB",
        price_per_unit=Decimal("0.02"),
        source="pricing_mcp",
        confidence="high",
        binding_status="bound",
    )
    pricing = type("Pricing", (), {
        "line_items": [type("Line", (), {"service": dimension.service_name, "expected_monthly_usd": 999})()],
    })()

    ledger = _pricing_ledger(pricing, [dimension], [rate], type("Assumptions", (), {"assumptions": []})())
    line = ledger.line_items[0]

    assert isinstance(ledger, PricingLedger)
    assert isinstance(ledger.summary, PricingLedgerSummary)
    assert line.monthly_total == Decimal("2.00")
    assert line.evidence_class == "sku_tier_backed"
    assert line.procurement_ready is False
    assert ledger.summary.procurement_ready is False
    assert "usage quantities are assumed" in " ".join(line.limitations)


def test_bound_rate_with_confirmed_quantity_can_be_procurement_ready():
    dimension = _dimension()
    rate = AwsRateBinding(
        service_name=dimension.service_name,
        aws_service_code=dimension.aws_service_code,
        sku="SKU1",
        usage_type="USE1-Storage",
        operation="Storage",
        product_family="Storage",
        rate_code="RATE1",
        unit="GB",
        price_per_unit=Decimal("0.02"),
        source="pricing_mcp",
        confidence="high",
        binding_status="bound",
    )
    pricing = type("Pricing", (), {
        "line_items": [type("Line", (), {"service": dimension.service_name, "expected_monthly_usd": 999})()],
    })()

    ledger = _pricing_ledger(pricing, [dimension], [rate], type("Assumptions", (), {"assumptions": []})())

    assert ledger.line_items[0].procurement_ready is True
    assert ledger.summary.procurement_ready is True
    assert _ledger_limitations(dimension, rate, True, "sku_tier_backed") == []
