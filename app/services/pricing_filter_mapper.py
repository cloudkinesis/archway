from dataclasses import dataclass, field


@dataclass(frozen=True)
class PricingFilterPlan:
    service_name: str
    service_code: str
    filters: dict[str, str] = field(default_factory=dict)
    confidence: str = "medium"
    rationale: str = "Mapped from AWS service name to Price List API service code and broad product filters."


_SERVICE_CODE_ALIASES: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("lambda edge", "AmazonCloudFront", {}),
    ("lambda@edge", "AmazonCloudFront", {}),
    ("cloudfront functions", "AmazonCloudFront", {}),
    ("cloudfront function", "AmazonCloudFront", {}),
    ("kinesis data streams", "AmazonKinesis", {"productFamily": "Kinesis Streams"}),
    ("managed service for apache flink", "AmazonKinesisAnalytics", {}),
    ("kinesis data analytics", "AmazonKinesisAnalytics", {}),
    ("sagemaker", "AmazonSageMaker", {}),
    ("simple storage service", "AmazonS3", {}),
    ("amazon s3", "AmazonS3", {}),
    ("s3", "AmazonS3", {}),
    ("cloudwatch", "AmazonCloudWatch", {}),
    ("step functions", "AmazonStates", {}),
    ("eventbridge", "AWSEvents", {}),
    ("simple queue service", "AWSQueueService", {}),
    ("amazon sqs", "AWSQueueService", {}),
    ("dynamodb", "AmazonDynamoDB", {}),
    ("iot core", "AWSIoT", {}),
    ("iot sitewise", "AWSIoTSiteWise", {}),
    ("timestream", "AmazonTimestream", {}),
    ("cloudtrail", "AWSCloudTrail", {}),
    ("kms", "awskms", {}),
    ("api gateway", "AmazonApiGateway", {}),
    ("bedrock", "AmazonBedrock", {}),
    ("rekognition", "AmazonRekognition", {}),
    ("opensearch", "AmazonES", {}),
    ("glue", "AWSGlue", {}),
    ("athena", "AmazonAthena", {}),
    ("redshift", "AmazonRedshift", {}),
    ("sns", "AmazonSNS", {}),
    ("waf", "AWSWAF", {}),
    ("cloudfront", "AmazonCloudFront", {}),
    ("lambda", "AWSLambda", {}),
    ("medialive", "AWSElementalMediaLive", {}),
    ("media live", "AWSElementalMediaLive", {}),
    ("mediapackage", "AWSElementalMediaPackage", {}),
    ("media package", "AWSElementalMediaPackage", {}),
    ("mediatailor", "AWSElementalMediaTailor", {}),
    ("media tailor", "AWSElementalMediaTailor", {}),
    ("batch", "AWSBatch", {}),
    ("amazon fsx for lustre", "AmazonFSx", {"productFamily": "Amazon FSx for Lustre"}),
    ("fsx for lustre", "AmazonFSx", {"productFamily": "Amazon FSx for Lustre"}),
    ("amazon msk", "AmazonMSK", {}),
    ("managed streaming for apache kafka", "AmazonMSK", {}),
    ("elasticache", "AmazonElastiCache", {}),
    ("direct connect", "AWSDirectConnect", {}),
    ("neptune", "AmazonNeptune", {}),
)


def pricing_filter_plan_for_service(service_name: str, *, region_code: str = "us-east-1") -> PricingFilterPlan | None:
    normalized = _normalize(service_name)
    for token, service_code, filters in _SERVICE_CODE_ALIASES:
        if token in normalized:
            mapped = dict(filters)
            mapped.setdefault("regionCode", region_code)
            return PricingFilterPlan(
                service_name=service_name,
                service_code=service_code,
                filters=mapped,
                confidence="high" if token in normalized else "medium",
            )
    return None


def _normalize(value: str) -> str:
    return " ".join(value.lower().replace("/", " ").replace("-", " ").replace("_", " ").split())
