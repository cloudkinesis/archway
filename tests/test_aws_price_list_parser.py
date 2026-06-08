from decimal import Decimal

from app.services.aws_price_list_parser import parse_price_list_offer, parse_price_list_query_response
from app.services.pricing_filter_mapper import pricing_filter_plan_for_service
from app.services.aws_price_list import AWSPriceListBulkClient


def test_price_list_parser_extracts_tiered_on_demand_dimensions():
    payload = {
        "products": {
            "SKU1": {
                "sku": "SKU1",
                "productFamily": "Amazon Kinesis Data Streams",
                "attributes": {
                    "usagetype": "USE1-PUTPayloadUnits",
                    "operation": "PutRecords",
                    "location": "US East (N. Virginia)",
                    "regionCode": "us-east-1",
                },
            }
        },
        "terms": {
            "OnDemand": {
                "SKU1": {
                    "SKU1.JRTCKXETXF": {
                        "effectiveDate": "2026-01-01T00:00:00Z",
                        "offerTermCode": "JRTCKXETXF",
                        "priceDimensions": {
                            "SKU1.JRTCKXETXF.RATE1": {
                                "unit": "Requests",
                                "beginRange": "0",
                                "endRange": "1000000",
                                "pricePerUnit": {"USD": "0.0140000000"},
                            },
                            "SKU1.JRTCKXETXF.RATE2": {
                                "unit": "Requests",
                                "beginRange": "1000000",
                                "endRange": "Inf",
                                "pricePerUnit": {"USD": "0.0110000000"},
                            },
                        },
                    }
                }
            }
        },
    }

    result = parse_price_list_offer(
        payload,
        service_code="AmazonKinesis",
        source_reference="mock-offer",
        filters={"regionCode": "us-east-1"},
    )

    assert not result.failures
    assert len(result.dimensions) == 2
    assert result.dimensions[0].sku == "SKU1"
    assert result.dimensions[0].begin_range == "0"
    assert result.dimensions[1].end_range == "Inf"
    assert result.dimensions[0].price_per_unit == Decimal("0.0140000000")


def test_price_list_parser_reports_ambiguous_matching_skus():
    payload = {
        "products": {
            "SKU1": {"sku": "SKU1", "attributes": {"regionCode": "us-east-1"}},
            "SKU2": {"sku": "SKU2", "attributes": {"regionCode": "us-east-1"}},
        },
        "terms": {"OnDemand": {"SKU1": {}, "SKU2": {}}},
    }

    result = parse_price_list_offer(payload, service_code="AWSLambda", source_reference="mock", filters={"regionCode": "us-east-1"})

    assert result.ambiguous_skus == ["SKU1", "SKU2"]
    assert "Matched products did not include parseable OnDemand price dimensions." in result.failures


def test_price_list_query_response_parser_handles_stringified_products():
    response = {
        "PriceList": [
            '{"product":{"sku":"SKU1","attributes":{"regionCode":"us-east-1","usagetype":"USE1-Requests"}},"terms":{"OnDemand":{"SKU1":{"SKU1.TERM":{"effectiveDate":"2026-01-01T00:00:00Z","offerTermCode":"TERM","priceDimensions":{"SKU1.TERM.RATE":{"unit":"Requests","beginRange":"0","endRange":"Inf","pricePerUnit":{"USD":"0.0000002"}}}}}}}}'
        ]
    }

    result = parse_price_list_query_response(response, service_code="AWSLambda", source_reference="query", filters={"regionCode": "us-east-1"})

    assert len(result.dimensions) == 1
    assert result.dimensions[0].source == "price_list_query_api"


def test_pricing_filter_mapper_maps_common_aws_service_names():
    plan = pricing_filter_plan_for_service("Amazon Managed Service for Apache Flink", region_code="us-west-2")

    assert plan is not None
    assert plan.service_code == "AmazonKinesisAnalytics"
    assert plan.filters["regionCode"] == "us-west-2"


def test_price_list_bulk_matching_prefers_explicit_service_code_over_fuzzy_match():
    index = {
        "offers": {
            "AmazonKinesisVideo": {
                "offerCode": "AmazonKinesisVideo",
                "currentVersionUrl": "/offers/v1.0/aws/AmazonKinesisVideo/current/index.json",
            },
            "AmazonKinesis": {
                "offerCode": "AmazonKinesis",
                "currentVersionUrl": "/offers/v1.0/aws/AmazonKinesis/current/index.json",
            },
        }
    }

    matches = AWSPriceListBulkClient().match_services(["Amazon Kinesis Data Streams"], index)

    assert matches[0][1].offer_code == "AmazonKinesis"
