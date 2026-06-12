"""Deterministic AWS icon asset resolution."""

from pathlib import Path
from shutil import copy2
from typing import Dict, Iterable, Optional, Union

from archway_diagram_compiler.catalog import normalize_service_name
from archway_diagram_compiler.models import LayoutNode, ServiceNode


SERVICE_ICON_FILES: Dict[str, str] = {
    "api_gateway": "api_gateway.svg",
    "alb": "load_balancer.svg",
    "app_runner": "app_runner.svg",
    "appsync": "appsync.svg",
    "athena": "athena.svg",
    "bedrock": "bedrock.svg",
    "bedrock_knowledge_base": "bedrock.svg",
    "cloudfront": "cloudfront.svg",
    "cloudtrail": "cloudtrail.svg",
    "cloudwatch": "cloudwatch.svg",
    "cognito": "cognito.svg",
    "direct_connect": "direct_connect.svg",
    "dynamodb": "dynamodb.svg",
    "ecs": "ecs.svg",
    "efs": "efs.svg",
    "elasticache": "elasticache.svg",
    "eventbridge": "eventbridge.svg",
    "firehose": "firehose.svg",
    "glue": "glue.svg",
    "iot_core": "iot_core.svg",
    "kendra": "kendra.svg",
    "kinesis": "kinesis.svg",
    "kms": "kms.svg",
    "lambda": "lambda.svg",
    "lambda_edge": "lambda.svg",
    "cloudfront_functions": "cloudfront.svg",
    "load_balancer": "load_balancer.svg",
    "msk": "msk.svg",
    "medialive": "kinesis.svg",
    "mediapackage": "s3.svg",
    "mediatailor": "cloudfront.svg",
    "nat_gateway": "transit_gateway.svg",
    "nlb": "load_balancer.svg",
    "opensearch": "opensearch.svg",
    "opensearch_serverless": "opensearch.svg",
    "privatelink_service": "privatelink.svg",
    "private_load_balancer": "load_balancer.svg",
    "rds": "rds.svg",
    "rds_proxy": "rds.svg",
    "redshift": "redshift.svg",
    "route53": "route53.svg",
    "s3": "s3.svg",
    "sagemaker": "sagemaker.svg",
    "secrets_manager": "secrets_manager.svg",
    "security_hub": "security_hub.svg",
    "shield": "shield.svg",
    "sns": "sns.svg",
    "sqs": "sqs.svg",
    "step_functions": "step_functions.svg",
    "transit_gateway": "transit_gateway.svg",
    "vpc_link": "vpc_link.svg",
    "vpn": "vpn.svg",
    "waf": "waf.svg",
    "xray": "xray.svg",
}


def package_icon_dir() -> Path:
    return Path(__file__).resolve().parent / "assets" / "aws-icons" / "64"


def service_icon_filename(service: str) -> Optional[str]:
    return SERVICE_ICON_FILES.get(normalize_service_name(service))


def copy_icon_assets(output_dir: Path, nodes: Iterable[ServiceNode]) -> Dict[str, str]:
    """Copy used AWS icons beside the D2 file and return node-id to relative path."""

    return _copy_icon_assets(output_dir, nodes)


def copy_layout_icon_assets(output_dir: Path, nodes: Iterable[LayoutNode]) -> Dict[str, str]:
    return _copy_icon_assets(output_dir, nodes)


def _copy_icon_assets(output_dir: Path, nodes: Iterable[Union[ServiceNode, LayoutNode]]) -> Dict[str, str]:
    source_dir = package_icon_dir()
    target_dir = output_dir / "aws-icons" / "64"
    icon_paths: Dict[str, str] = {}

    for node in nodes:
        filename = service_icon_filename(node.service)
        if not filename:
            continue
        source = source_dir / filename
        if not source.exists():
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / filename
        if not target.exists():
            copy2(source, target)
        icon_paths[node.id] = f"./aws-icons/64/{filename}"

    return icon_paths
