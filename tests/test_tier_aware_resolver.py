from __future__ import annotations
from decimal import Decimal
from app.domain.source_of_truth import ServiceUsageDimension
from app.services.pricing_authority_resolver import PricingAuthorityResolver, select_tier_by_quantity
from app.domain.pricing_evidence import PriceDimensionEvidence

def test_select_tier_by_quantity():
    dimensions = [
        PriceDimensionEvidence(
            service_code="AmazonS3",
            sku="SKU1",
            unit="GB",
            begin_range="0",
            end_range="51200",
            price_per_unit=Decimal("0.023"),
            currency="USD",
            term_type="OnDemand",
            source="pricing_mcp",
            source_reference="ref1"
        ),
        PriceDimensionEvidence(
            service_code="AmazonS3",
            sku="SKU1",
            unit="GB",
            begin_range="51200",
            end_range="512000",
            price_per_unit=Decimal("0.022"),
            currency="USD",
            term_type="OnDemand",
            source="pricing_mcp",
            source_reference="ref2"
        ),
        PriceDimensionEvidence(
            service_code="AmazonS3",
            sku="SKU1",
            unit="GB",
            begin_range="512000",
            end_range="Inf",
            price_per_unit=Decimal("0.021"),
            currency="USD",
            term_type="OnDemand",
            source="pricing_mcp",
            source_reference="ref3"
        ),
    ]

    res = select_tier_by_quantity(dimensions, Decimal("10000"))
    assert len(res) == 1
    assert res[0].price_per_unit == Decimal("0.023")

    res = select_tier_by_quantity(dimensions, Decimal("60000"))
    assert len(res) == 1
    assert res[0].price_per_unit == Decimal("0.022")

    res = select_tier_by_quantity(dimensions, Decimal("51200"))
    assert len(res) == 1
    assert res[0].price_per_unit == Decimal("0.022")

    res = select_tier_by_quantity(dimensions, Decimal("1000000"))
    assert len(res) == 1
    assert res[0].price_per_unit == Decimal("0.021")

    res = select_tier_by_quantity(dimensions, None)
    assert len(res) == 3


def test_pricing_authority_resolver_resolves_tiered_pricing(monkeypatch):
    monkeypatch.setenv("ARCHWAY_ENABLE_AWS_PRICING_MCP", "true")
    monkeypatch.setenv("ARCHWAY_AWS_PRICING_MCP_COMMAND", "fake-mcp")
    monkeypatch.setattr("app.services.pricing_authority_resolver._resolved_mcp_command", lambda command: "fake-mcp")
    
    def mock_mcp(dimension, region_code, **kwargs):
        payload = {
            "PriceList": [
                {
                    "product": {
                        "sku": "SKU1",
                        "productFamily": "Storage",
                        "attributes": {
                            "regionCode": "us-east-1",
                            "usagetype": "USE1-Storage",
                            "operation": "Storage",
                        },
                    },
                    "terms": {
                        "OnDemand": {
                            "SKU1.JRTCKXETXF": {
                                "sku": "SKU1",
                                "effectiveDate": "2026-01-01T00:00:00Z",
                                "priceDimensions": {
                                    "SKU1.JRTCKXETXF.6YS6EN2CT7": {
                                        "unit": "GB",
                                        "beginRange": "0",
                                        "endRange": "51200",
                                        "pricePerUnit": {"USD": "0.023"},
                                    },
                                    "SKU1.JRTCKXETXF.7YS6EN2CT7": {
                                        "unit": "GB",
                                        "beginRange": "51200",
                                        "endRange": "512000",
                                        "pricePerUnit": {"USD": "0.022"},
                                    }
                                },
                            }
                        }
                    },
                }
            ]
        }
        return {"content": [{"type": "text", "text": __import__("json").dumps(payload)}]}

    monkeypatch.setattr("app.services.pricing_authority_resolver._call_aws_labs_pricing_mcp", mock_mcp)

    dimension = ServiceUsageDimension(
        service_name="Amazon S3",
        usage_name="S3 Standard storage",
        aws_service_code="AmazonS3",
        quantity=Decimal("60000"),
        unit="GB",
        formula="some_formula"
    )

    binding = PricingAuthorityResolver().resolve(dimension, region_code="us-east-1")
    assert binding.binding_status == "bound"
    assert binding.price_per_unit == Decimal("0.02285333")
    assert binding.is_tiered is True


def test_tiered_binding_not_procurement_ready():
    from app.services.source_truth_pricing_compiler import _pricing_ledger
    from app.domain.source_of_truth import AwsRateBinding, AssumptionLedger
    from app.models.domain import PricingAnalysis, PricingLineItem
    
    pricing = PricingAnalysis(
        region="us-east-1",
        low_monthly_usd=1000,
        expected_monthly_usd=1371,
        high_monthly_usd=1500,
        line_items=[
            PricingLineItem(
                service="Amazon S3",
                unit_basis="GB",
                expected_monthly_usd=1371,
                low_monthly_usd=1000,
                high_monthly_usd=1500,
                assumptions=[],
                evidence_ids=[]
            )
        ],
        main_cost_drivers=[],
        unknown_variables=[],
        cost_optimization_recommendations=[],
        evidence_items=[]
    )
    
    usage_dimensions = [
        ServiceUsageDimension(
            service_name="Amazon S3",
            usage_name="S3 Standard storage",
            aws_service_code="AmazonS3",
            quantity=Decimal("60000"),
            unit="GB",
            formula="some_formula"
        )
    ]
    
    rate_bindings = [
        AwsRateBinding(
            service_name="Amazon S3",
            aws_service_code="AmazonS3",
            sku="SKU1",
            price_per_unit=Decimal("0.02285333"),
            binding_status="bound",
            is_tiered=True
        )
    ]
    
    ledger = _pricing_ledger(pricing, usage_dimensions, rate_bindings, AssumptionLedger())
    assert len(ledger.line_items) == 1
    assert ledger.line_items[0].procurement_ready is False
    assert ledger.line_items[0].confidence == "low"


def test_malformed_tier_bounds_fail_closed():
    dimensions = [
        PriceDimensionEvidence(
            service_code="AmazonS3",
            sku="SKU1",
            unit="GB",
            begin_range="0",
            end_range="abc",  # malformed end range
            price_per_unit=Decimal("0.023"),
            currency="USD",
            term_type="OnDemand",
            source="pricing_mcp",
            source_reference="ref1"
        )
    ]
    
    import pytest
    with pytest.raises(ValueError, match="Malformed tier bound"):
        select_tier_by_quantity(dimensions, Decimal("10"))


def test_resolver_with_malformed_bounds_fails_closed(monkeypatch):
    monkeypatch.setenv("ARCHWAY_ENABLE_AWS_PRICING_MCP", "true")
    monkeypatch.setenv("ARCHWAY_AWS_PRICING_MCP_COMMAND", "fake-mcp")
    monkeypatch.setattr("app.services.pricing_authority_resolver._resolved_mcp_command", lambda command: "fake-mcp")
    
    def mock_mcp(dimension, region_code, **kwargs):
        payload = {
            "PriceList": [
                {
                    "product": {
                        "sku": "SKU1",
                        "productFamily": "Storage",
                        "attributes": {
                            "regionCode": "us-east-1",
                            "usagetype": "USE1-Storage",
                            "operation": "Storage",
                        },
                    },
                    "terms": {
                        "OnDemand": {
                            "SKU1.JRTCKXETXF": {
                                "sku": "SKU1",
                                "effectiveDate": "2026-01-01T00:00:00Z",
                                "priceDimensions": {
                                    "SKU1.JRTCKXETXF.6YS6EN2CT7": {
                                        "unit": "GB",
                                        "beginRange": "0",
                                        "endRange": "malformed_value",
                                        "pricePerUnit": {"USD": "0.023"},
                                    },
                                    "SKU1.JRTCKXETXF.7YS6EN2CT7": {
                                        "unit": "GB",
                                        "beginRange": "malformed_value",
                                        "endRange": "inf",
                                        "pricePerUnit": {"USD": "0.022"},
                                    }
                                },
                            }
                        }
                    },
                }
            ]
        }
        return {"content": [{"type": "text", "text": __import__("json").dumps(payload)}]}
        
    monkeypatch.setattr("app.services.pricing_authority_resolver._call_aws_labs_pricing_mcp", mock_mcp)

    dimension = ServiceUsageDimension(
        service_name="Amazon S3",
        usage_name="S3 Standard storage",
        aws_service_code="AmazonS3",
        quantity=Decimal("60000"),
        unit="GB",
        formula="some_formula"
    )

    binding = PricingAuthorityResolver().resolve(dimension, region_code="us-east-1")
    assert binding.binding_status == "unsupported"
    assert binding.confidence == "none"

