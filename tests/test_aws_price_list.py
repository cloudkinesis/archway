from app.services.aws_price_list import AWSPriceListBulkClient


def test_price_list_offer_matching_uses_index_not_hardcoded_prices():
    index = {
        "offers": {
            "AmazonKinesis": {
                "offerCode": "AmazonKinesis",
                "currentVersionUrl": "/offers/v1.0/aws/AmazonKinesis/current/index.json",
                "currentRegionIndexUrl": "/offers/v1.0/aws/AmazonKinesis/current/region_index.json",
            },
            "AmazonSageMaker": {
                "offerCode": "AmazonSageMaker",
                "currentVersionUrl": "/offers/v1.0/aws/AmazonSageMaker/current/index.json",
            },
        }
    }

    matches = AWSPriceListBulkClient().match_services(
        ["Amazon Kinesis Data Streams", "Amazon SageMaker", "External workforce management system"],
        index,
    )

    assert [offer.offer_code for _, offer in matches] == ["AmazonKinesis", "AmazonSageMaker"]
    assert matches[0][1].current_version_url == "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonKinesis/current/index.json"
