from decimal import Decimal

from app.core.config import get_settings
from app.domain.source_of_truth import ServiceUsageDimension
from app.services.aws_rate_binding_engine import AwsRateBindingEngine


def test_rate_binding_engine_binds_single_cloudfront_price_dimension(monkeypatch):
    response = {
        "PriceList": [
            '{"product":{"sku":"SKU1","productFamily":"Data Transfer","attributes":{"usagetype":"DataTransfer-Out-Bytes","operation":"","regionCode":"us-east-1"}},"terms":{"OnDemand":{"SKU1":{"SKU1.TERM":{"effectiveDate":"2026-01-01T00:00:00Z","offerTermCode":"TERM","priceDimensions":{"SKU1.TERM.RATE":{"unit":"GB","beginRange":"0","endRange":"Inf","pricePerUnit":{"USD":"0.085"}}}}}}}}'
        ]
    }
    monkeypatch.setenv("ARCHWAY_ENABLE_AWS_PRICING_MCP", "false")
    monkeypatch.delenv("ARCHWAY_AWS_PRICING_MCP_COMMAND", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr("app.services.pricing_authority_resolver._get_products", lambda dimension, region_code: response)
    dimension = ServiceUsageDimension(
        service_name="Amazon CloudFront",
        usage_name="CDN data transfer out",
        aws_service_code="AmazonCloudFront",
        quantity=Decimal("1000"),
        unit="GB",
        formula="viewer_hours_per_month * average_bitrate_mbps * 3600 / 8 / 1024",
    )

    binding = AwsRateBindingEngine().bind(dimension, region_code="us-east-1")

    assert binding.binding_status == "bound"
    assert binding.sku == "SKU1"
    assert binding.rate_code == "SKU1.TERM.RATE"
    assert binding.price_per_unit == Decimal("0.085")
    assert binding.source == "price_list_query_api"


def test_rate_binding_engine_marks_multiple_cloudfront_rates_ambiguous(monkeypatch):
    response = {
        "PriceList": [
            '{"product":{"sku":"SKU1","productFamily":"Data Transfer","attributes":{"usagetype":"DataTransfer-Out-Bytes","operation":"","regionCode":"us-east-1"}},"terms":{"OnDemand":{"SKU1":{"SKU1.TERM":{"priceDimensions":{"SKU1.TERM.RATE":{"unit":"GB","beginRange":"0","endRange":"Inf","pricePerUnit":{"USD":"0.085"}}}}}}}}',
            '{"product":{"sku":"SKU2","productFamily":"Data Transfer","attributes":{"usagetype":"EU-DataTransfer-Out-Bytes","operation":"","regionCode":"eu-west-1"}},"terms":{"OnDemand":{"SKU2":{"SKU2.TERM":{"priceDimensions":{"SKU2.TERM.RATE":{"unit":"GB","beginRange":"0","endRange":"Inf","pricePerUnit":{"USD":"0.09"}}}}}}}}',
        ]
    }
    monkeypatch.setenv("ARCHWAY_ENABLE_AWS_PRICING_MCP", "false")
    monkeypatch.delenv("ARCHWAY_AWS_PRICING_MCP_COMMAND", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr("app.services.pricing_authority_resolver._get_products", lambda dimension, region_code: response)
    dimension = ServiceUsageDimension(
        service_name="Amazon CloudFront",
        usage_name="CDN data transfer out",
        aws_service_code="AmazonCloudFront",
        quantity=Decimal("1000"),
        unit="GB",
        formula="viewer_hours_per_month * average_bitrate_mbps * 3600 / 8 / 1024",
    )

    binding = AwsRateBindingEngine().bind(dimension, region_code="us-east-1")

    assert binding.binding_status == "ambiguous"
    assert binding.sku == "SKU1"
    assert "did not silently choose" in " ".join(binding.notes)
