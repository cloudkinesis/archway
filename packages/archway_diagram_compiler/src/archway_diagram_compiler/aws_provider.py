"""AWS provider catalog and placement semantics."""

from typing import Dict, Optional

from archway_diagram_compiler.models import IconRef, ServiceInfo, ServiceNode
from archway_diagram_compiler.provider_catalog import ProviderCatalog


AWS_SERVICE_ALIASES: Dict[str, str] = {
    "amazon api gateway": "api_gateway",
    "api gateway": "api_gateway",
    "apigateway": "api_gateway",
    "aws waf": "waf",
    "amazon cloudfront": "cloudfront",
    "cloudfront": "cloudfront",
    "cloudfront functions": "cloudfront_functions",
    "cloudfront function": "cloudfront_functions",
    "amazon route 53": "route53",
    "route 53": "route53",
    "route53": "route53",
    "amazon cognito": "cognito",
    "cognito": "cognito",
    "application load balancer": "alb",
    "alb": "alb",
    "network load balancer": "nlb",
    "nlb": "nlb",
    "elastic load balancing": "load_balancer",
    "private_load_balancer": "private_load_balancer",
    "private load balancer": "private_load_balancer",
    "ecs": "ecs",
    "amazon ecs": "ecs",
    "eks": "eks",
    "amazon eks": "eks",
    "ec2": "ec2",
    "amazon ec2": "ec2",
    "lambda": "lambda",
    "aws lambda": "lambda",
    "lambda@edge": "lambda_edge",
    "lambda edge": "lambda_edge",
    "aws lambda@edge": "lambda_edge",
    "aws lambda edge": "lambda_edge",
    "s3": "s3",
    "amazon s3": "s3",
    "dynamodb": "dynamodb",
    "amazon dynamodb": "dynamodb",
    "efs": "efs",
    "amazon efs": "efs",
    "elastic file system": "efs",
    "amazon elastic file system": "efs",
    "sqs": "sqs",
    "amazon sqs": "sqs",
    "sns": "sns",
    "amazon sns": "sns",
    "eventbridge": "eventbridge",
    "amazon eventbridge": "eventbridge",
    "step functions": "step_functions",
    "aws step functions": "step_functions",
    "secrets manager": "secrets_manager",
    "aws secrets manager": "secrets_manager",
    "kms": "kms",
    "aws kms": "kms",
    "cloudwatch": "cloudwatch",
    "amazon cloudwatch": "cloudwatch",
    "cloudtrail": "cloudtrail",
    "aws cloudtrail": "cloudtrail",
    "bedrock": "bedrock",
    "amazon bedrock": "bedrock",
    "bedrock agent": "bedrock_agent",
    "amazon bedrock agent": "bedrock_agent",
    "bedrock_agent": "bedrock_agent",
    "bedrock agentcore": "bedrock_agentcore",
    "bedrock_agentcore": "bedrock_agentcore",
    "bedrock knowledge base": "bedrock_knowledge_base",
    "amazon bedrock knowledge base": "bedrock_knowledge_base",
    "bedrock kb": "bedrock_knowledge_base",
    "bedrock_kb": "bedrock_knowledge_base",
    "kb": "bedrock_knowledge_base",
    "guardrail": "bedrock_guardrails",
    "guardrails": "bedrock_guardrails",
    "bedrock guardrail": "bedrock_guardrails",
    "bedrock guardrails": "bedrock_guardrails",
    "bedrock_guardrails": "bedrock_guardrails",
    "agent": "agent_runtime",
    "agent runtime": "agent_runtime",
    "agent_runtime": "agent_runtime",
    "kendra": "kendra",
    "amazon kendra": "kendra",
    "opensearch serverless": "opensearch_serverless",
    "amazon opensearch serverless": "opensearch_serverless",
    "opensearch": "opensearch_serverless",
    "open search": "opensearch_serverless",
    "oss_vector": "opensearch_serverless",
    "opensearch vector index": "opensearch_vector_index",
    "opensearch_vector_index": "opensearch_vector_index",
    "opensearch hybrid search": "opensearch_hybrid_search",
    "opensearch_hybrid_search": "opensearch_hybrid_search",
    "opensearch log analytics": "opensearch_log_analytics_index",
    "opensearch_log_analytics_index": "opensearch_log_analytics_index",
    "log analytics index": "opensearch_log_analytics_index",
    "opensearch application search": "opensearch_application_search_index",
    "opensearch_application_search_index": "opensearch_application_search_index",
    "application search index": "opensearch_application_search_index",
    "opensearch domain": "opensearch_domain",
    "opensearch_domain": "opensearch_domain",
    "vector store": "opensearch_vector_index",
    "vector_store": "opensearch_vector_index",
    "generic vector store": "generic_vector_store",
    "generic_vector_store": "generic_vector_store",
    "external actor": "external_actor",
    "external_actor": "external_actor",
    "external user": "external_actor",
    "external_user": "external_actor",
    "vpc endpoint": "vpc_endpoint",
    "vpc_endpoint": "vpc_endpoint",
    "shield": "shield",
    "aws shield": "shield",
    "aurora": "rds",
    "amazon aurora": "rds",
    "rds proxy": "rds_proxy",
    "amazon rds proxy": "rds_proxy",
    "kinesis": "kinesis",
    "amazon kinesis": "kinesis",
    "firehose": "firehose",
    "kinesis firehose": "firehose",
    "aws elemental medialive": "medialive",
    "amazon elemental medialive": "medialive",
    "medialive": "medialive",
    "media live": "medialive",
    "aws elemental mediapackage": "mediapackage",
    "amazon elemental mediapackage": "mediapackage",
    "mediapackage": "mediapackage",
    "media package": "mediapackage",
    "aws elemental mediatailor": "mediatailor",
    "amazon elemental mediatailor": "mediatailor",
    "mediatailor": "mediatailor",
    "media tailor": "mediatailor",
    "amazon msk": "msk",
    "msk": "msk",
    "glue": "glue",
    "aws glue": "glue",
    "athena": "athena",
    "amazon athena": "athena",
    "redshift": "redshift",
    "amazon redshift": "redshift",
    "sagemaker": "sagemaker",
    "amazon sagemaker": "sagemaker",
    "app runner": "app_runner",
    "aws app runner": "app_runner",
    "appsync": "appsync",
    "aws appsync": "appsync",
    "elasticache": "elasticache",
    "amazon elasticache": "elasticache",
    "transit gateway": "transit_gateway",
    "aws transit gateway": "transit_gateway",
    "direct connect": "direct_connect",
    "aws direct connect": "direct_connect",
    "vpn": "vpn",
    "nat gateway": "nat_gateway",
    "iot core": "iot_core",
    "aws iot core": "iot_core",
    "iot": "iot_core",
    "x-ray": "xray",
    "xray": "xray",
    "aws x-ray": "xray",
    "security hub": "security_hub",
    "aws security hub": "security_hub",
    "privatelink": "privatelink_service",
    "aws privatelink": "privatelink_service",
    "private link": "privatelink_service",
    "third party llm endpoint": "third_party_llm_endpoint",
    "third_party_llm_endpoint": "third_party_llm_endpoint",
    "custom vector store": "custom_vector_store",
    "custom_vector_store": "custom_vector_store",
    "custom eval service": "custom_eval_service",
    "custom_eval_service": "custom_eval_service",
    "made up ai service": "made_up_ai_service",
    "made_up_ai_service": "made_up_ai_service",
}


AWS_SERVICE_INFO: Dict[str, ServiceInfo] = {
    "route53": ServiceInfo(service="route53", provider="aws", placement_scope="global_edge", category="edge", icon="route53.svg"),
    "cloudfront": ServiceInfo(service="cloudfront", provider="aws", placement_scope="global_edge", category="edge", icon="cloudfront.svg"),
    "cloudfront_functions": ServiceInfo(service="cloudfront_functions", provider="aws", placement_scope="global_edge", category="edge_compute", icon="cloudfront.svg"),
    "waf": ServiceInfo(service="waf", provider="aws", placement_scope="edge_or_regional_control", category="security", icon="waf.svg"),
    "shield": ServiceInfo(service="shield", provider="aws", placement_scope="global_edge_control", category="security", icon="shield.svg"),
    "api_gateway": ServiceInfo(service="api_gateway", provider="aws", placement_scope="regional_entry", category="entry", icon="api_gateway.svg"),
    "cognito": ServiceInfo(service="cognito", provider="aws", placement_scope="regional_identity", category="identity", icon="cognito.svg"),
    "alb": ServiceInfo(service="alb", provider="aws", placement_scope="vpc_resident", category="networking", icon="load_balancer.svg", can_be_vpc_resident=True),
    "nlb": ServiceInfo(service="nlb", provider="aws", placement_scope="vpc_resident", category="networking", icon="load_balancer.svg", can_be_vpc_resident=True),
    "load_balancer": ServiceInfo(service="load_balancer", provider="aws", placement_scope="vpc_resident", category="networking", icon="load_balancer.svg", can_be_vpc_resident=True),
    "private_load_balancer": ServiceInfo(service="private_load_balancer", provider="aws", placement_scope="vpc_resident", category="networking", icon="load_balancer.svg", can_be_vpc_resident=True),
    "ecs": ServiceInfo(service="ecs", provider="aws", placement_scope="vpc_resident", category="compute", icon="ecs.svg", can_be_vpc_resident=True),
    "eks": ServiceInfo(service="eks", provider="aws", placement_scope="vpc_resident", category="compute", icon="ecs.svg", can_be_vpc_resident=True),
    "ec2": ServiceInfo(service="ec2", provider="aws", placement_scope="vpc_resident", category="compute", icon="ecs.svg", can_be_vpc_resident=True),
    "lambda": ServiceInfo(service="lambda", provider="aws", placement_scope="regional_compute", category="compute", icon="lambda.svg", can_be_vpc_resident=True, endpoint_type="interface"),
    "lambda_edge": ServiceInfo(service="lambda_edge", provider="aws", placement_scope="global_edge", category="edge_compute", icon="lambda.svg"),
    "s3": ServiceInfo(service="s3", provider="aws", placement_scope="regional_managed_data", category="data", icon="s3.svg", endpoint_type="gateway"),
    "dynamodb": ServiceInfo(service="dynamodb", provider="aws", placement_scope="regional_managed_data", category="data", icon="dynamodb.svg", endpoint_type="gateway"),
    "opensearch_serverless": ServiceInfo(service="opensearch_serverless", provider="aws", placement_scope="regional_managed_data", category="data", icon="opensearch.svg", endpoint_type="interface"),
    "opensearch_vector_index": ServiceInfo(service="opensearch_vector_index", provider="aws", placement_scope="regional_managed_data", category="data", icon="opensearch.svg", endpoint_type="interface"),
    "opensearch_hybrid_search": ServiceInfo(service="opensearch_hybrid_search", provider="aws", placement_scope="regional_managed_data", category="data", icon="opensearch.svg", endpoint_type="interface"),
    "opensearch_log_analytics_index": ServiceInfo(service="opensearch_log_analytics_index", provider="aws", placement_scope="regional_managed_data", category="observability", icon="opensearch.svg", endpoint_type="interface"),
    "opensearch_application_search_index": ServiceInfo(service="opensearch_application_search_index", provider="aws", placement_scope="regional_managed_data", category="data", icon="opensearch.svg", endpoint_type="interface"),
    "opensearch_domain": ServiceInfo(service="opensearch_domain", provider="aws", placement_scope="regional_managed_data", category="data", icon="opensearch.svg", can_be_vpc_resident=True, endpoint_type="interface"),
    "generic_vector_store": ServiceInfo(service="generic_vector_store", provider="aws", placement_scope="regional_managed_data", category="data", icon="opensearch.svg", endpoint_type="interface"),
    "bedrock": ServiceInfo(service="bedrock", provider="aws", placement_scope="regional_managed_ai", category="ai", icon="bedrock.svg", endpoint_type="interface"),
    "bedrock_agent": ServiceInfo(service="bedrock_agent", provider="aws", placement_scope="regional_managed_ai", category="ai", icon="bedrock.svg", endpoint_type="interface"),
    "bedrock_agentcore": ServiceInfo(service="bedrock_agentcore", provider="aws", placement_scope="regional_managed_ai", category="ai", icon="bedrock.svg", endpoint_type="interface"),
    "bedrock_knowledge_base": ServiceInfo(service="bedrock_knowledge_base", provider="aws", placement_scope="regional_managed_ai", category="ai", icon="bedrock.svg", endpoint_type="interface"),
    "bedrock_guardrails": ServiceInfo(service="bedrock_guardrails", provider="aws", placement_scope="regional_managed_ai", category="ai", icon="bedrock.svg", endpoint_type="interface"),
    "agent_runtime": ServiceInfo(service="agent_runtime", provider="aws", placement_scope="generic_application", category="ai_application", icon="bedrock.svg", can_be_vpc_resident=True),
    "kendra": ServiceInfo(service="kendra", provider="aws", placement_scope="regional_managed_ai", category="ai", icon="kendra.svg"),
    "sqs": ServiceInfo(service="sqs", provider="aws", placement_scope="regional_integration", category="integration", icon="sqs.svg", endpoint_type="interface"),
    "sns": ServiceInfo(service="sns", provider="aws", placement_scope="regional_integration", category="integration", icon="sns.svg", endpoint_type="interface"),
    "eventbridge": ServiceInfo(service="eventbridge", provider="aws", placement_scope="regional_integration", category="integration", icon="eventbridge.svg"),
    "step_functions": ServiceInfo(service="step_functions", provider="aws", placement_scope="regional_orchestration", category="orchestration", icon="step_functions.svg"),
    "secrets_manager": ServiceInfo(service="secrets_manager", provider="aws", placement_scope="regional_security", category="security", icon="secrets_manager.svg", endpoint_type="interface"),
    "kms": ServiceInfo(service="kms", provider="aws", placement_scope="regional_security", category="security", icon="kms.svg", endpoint_type="interface"),
    "cloudwatch": ServiceInfo(service="cloudwatch", provider="aws", placement_scope="regional_observability", category="observability", icon="cloudwatch.svg", endpoint_type="interface"),
    "cloudtrail": ServiceInfo(service="cloudtrail", provider="aws", placement_scope="regional_audit", category="audit", icon="cloudtrail.svg"),
    "external_actor": ServiceInfo(service="external_actor", provider="aws", placement_scope="external_actor", category="external"),
    "vpc_endpoint": ServiceInfo(service="vpc_endpoint", provider="aws", placement_scope="vpc_resident", category="networking", icon="vpc_link.svg", can_be_vpc_resident=True),
    "generic_application": ServiceInfo(service="generic_application", provider="aws", placement_scope="generic_application", category="application"),
    "kinesis": ServiceInfo(service="kinesis", provider="aws", placement_scope="regional_integration", category="streaming", icon="kinesis.svg", endpoint_type="interface"),
    "firehose": ServiceInfo(service="firehose", provider="aws", placement_scope="regional_integration", category="streaming", icon="firehose.svg", endpoint_type="interface"),
    "medialive": ServiceInfo(service="medialive", provider="aws", placement_scope="regional_managed_data", category="media", icon="kinesis.svg"),
    "mediapackage": ServiceInfo(service="mediapackage", provider="aws", placement_scope="regional_managed_data", category="media", icon="s3.svg"),
    "mediatailor": ServiceInfo(service="mediatailor", provider="aws", placement_scope="regional_integration", category="media", icon="cloudfront.svg"),
    "msk": ServiceInfo(service="msk", provider="aws", placement_scope="regional_integration", category="streaming", icon="msk.svg", can_be_vpc_resident=True, endpoint_type="interface"),
    "rds": ServiceInfo(service="rds", provider="aws", placement_scope="regional_managed_data", category="data", icon="rds.svg", can_be_vpc_resident=True, endpoint_type="interface"),
    "rds_proxy": ServiceInfo(service="rds_proxy", provider="aws", placement_scope="vpc_resident", category="data", icon="rds.svg", can_be_vpc_resident=True),
    "glue": ServiceInfo(service="glue", provider="aws", placement_scope="regional_managed_data", category="analytics", icon="glue.svg"),
    "athena": ServiceInfo(service="athena", provider="aws", placement_scope="regional_managed_data", category="analytics", icon="athena.svg"),
    "redshift": ServiceInfo(service="redshift", provider="aws", placement_scope="regional_managed_data", category="analytics", icon="redshift.svg", can_be_vpc_resident=True),
    "sagemaker": ServiceInfo(service="sagemaker", provider="aws", placement_scope="regional_managed_ai", category="ai", icon="sagemaker.svg", endpoint_type="interface"),
    "app_runner": ServiceInfo(service="app_runner", provider="aws", placement_scope="regional_compute", category="application", icon="app_runner.svg"),
    "appsync": ServiceInfo(service="appsync", provider="aws", placement_scope="regional_entry", category="entry", icon="appsync.svg"),
    "elasticache": ServiceInfo(service="elasticache", provider="aws", placement_scope="vpc_resident", category="data_cache", icon="elasticache.svg", can_be_vpc_resident=True),
    "efs": ServiceInfo(service="efs", provider="aws", placement_scope="vpc_resident", category="data", icon="efs.svg", can_be_vpc_resident=True),
    "transit_gateway": ServiceInfo(service="transit_gateway", provider="aws", placement_scope="regional_entry", category="network_connectivity", icon="transit_gateway.svg"),
    "direct_connect": ServiceInfo(service="direct_connect", provider="aws", placement_scope="regional_entry", category="network_connectivity", icon="direct_connect.svg"),
    "vpn": ServiceInfo(service="vpn", provider="aws", placement_scope="regional_entry", category="network_connectivity", icon="vpn.svg"),
    "nat_gateway": ServiceInfo(service="nat_gateway", provider="aws", placement_scope="vpc_resident", category="network_connectivity", icon="transit_gateway.svg", can_be_vpc_resident=True),
    "iot_core": ServiceInfo(service="iot_core", provider="aws", placement_scope="regional_integration", category="integration", icon="iot_core.svg"),
    "xray": ServiceInfo(service="xray", provider="aws", placement_scope="regional_observability", category="observability", icon="xray.svg"),
    "security_hub": ServiceInfo(service="security_hub", provider="aws", placement_scope="regional_security", category="security", icon="security_hub.svg"),
    "privatelink_service": ServiceInfo(service="privatelink_service", provider="aws", placement_scope="regional_entry", category="network_connectivity", icon="privatelink.svg"),
}


class AwsProviderCatalog(ProviderCatalog):
    provider_id = "aws"

    def canonicalize_service(self, service: str) -> str:
        normalized = service.strip().lower().replace("-", "_").replace(" ", "_")
        return AWS_SERVICE_ALIASES.get(service.strip().lower(), AWS_SERVICE_ALIASES.get(normalized, normalized))

    def get_service_info(self, service: str) -> ServiceInfo:
        canonical = self.canonicalize_service(service)
        return AWS_SERVICE_INFO.get(canonical) or self.infer_fallback_service_info(canonical, ServiceNode(id="_", name="_", service=canonical))

    def get_icon(self, service: str) -> IconRef:
        info = self.get_service_info(service)
        return IconRef(service=info.service, path=info.icon, fallback=f"{info.category}.svg")

    def get_default_category(self, service: str) -> str:
        return self.get_service_info(service).category

    def get_placement_scope(self, service: str, node: ServiceNode) -> str:
        canonical = self.canonicalize_service(service)
        info = AWS_SERVICE_INFO.get(canonical) or self.infer_fallback_service_info(canonical, node)
        if info.service == "lambda" and node.vpc_id:
            return "vpc_resident"
        if node.vpc_id and info.can_be_vpc_resident:
            return "vpc_resident"
        return info.placement_scope

    def get_endpoint_type(self, service: str) -> Optional[str]:
        return self.get_service_info(service).endpoint_type

    def is_fallback_service(self, service: str) -> bool:
        return self.canonicalize_service(service) not in AWS_SERVICE_INFO

    def infer_fallback_service_info(self, service: str, node: ServiceNode) -> ServiceInfo:
        canonical = self.canonicalize_service(service)
        lowered = canonical.lower()
        if any(token in lowered for token in ("third_party_llm", "external_llm", "llm_endpoint")):
            return _fallback(canonical, "regional_managed_ai", "external_ai_service", "bedrock.svg", endpoint_type="interface")
        if "custom_vector_store" in lowered:
            return _fallback(canonical, "regional_managed_data", "custom_vector_store", "opensearch.svg", endpoint_type="interface")
        if any(token in lowered for token in ("custom_eval", "eval_service", "evaluation_service")):
            return _fallback(canonical, "regional_managed_ai", "evaluation_service", "bedrock.svg", endpoint_type="interface")
        if any(token in lowered for token in ("made_up_ai", "custom_ai")):
            return _fallback(canonical, "regional_managed_ai", "custom_ai_service", "bedrock.svg", endpoint_type="interface")
        if any(token in lowered for token in ("kinesis", "firehose", "msk", "stream")):
            icon = "firehose.svg" if "firehose" in lowered else "msk.svg" if "msk" in lowered else "kinesis.svg"
            return _fallback(
                canonical,
                "vpc_resident" if node.vpc_id and "msk" in lowered else "regional_integration",
                "streaming",
                icon,
                can_be_vpc_resident="msk" in lowered,
                endpoint_type="interface",
            )
        if any(token in lowered for token in ("rds", "aurora", "database", "db")):
            return _fallback(
                canonical,
                "vpc_resident" if node.vpc_id else "regional_managed_data",
                "data",
                "rds.svg",
                can_be_vpc_resident=True,
                endpoint_type="interface",
            )
        if any(token in lowered for token in ("glue", "athena", "redshift", "emr")):
            if "glue" in lowered:
                icon = "glue.svg"
            elif "athena" in lowered:
                icon = "athena.svg"
            elif "redshift" in lowered:
                icon = "redshift.svg"
            else:
                icon = "s3.svg"
            return _fallback(
                canonical,
                "vpc_resident" if node.vpc_id and "redshift" in lowered else "regional_managed_data",
                "analytics",
                icon,
                can_be_vpc_resident="redshift" in lowered,
            )
        if any(token in lowered for token in ("sagemaker", "bedrock", "agent", "guardrail", "ai", "ml", "model", "embedding")):
            icon = "sagemaker.svg" if "sagemaker" in lowered else "bedrock.svg"
            return _fallback(canonical, "regional_managed_ai", "ai", icon, endpoint_type="interface")
        if any(token in lowered for token in ("opensearch", "vector", "search")):
            return _fallback(canonical, "regional_managed_data", "data", "opensearch.svg", endpoint_type="interface")
        if any(token in lowered for token in ("transit", "directconnect", "direct_connect", "vpn", "nat")):
            if "directconnect" in lowered or "direct_connect" in lowered:
                icon = "direct_connect.svg"
            elif "vpn" in lowered:
                icon = "vpn.svg"
            else:
                icon = "transit_gateway.svg"
            return _fallback(
                canonical,
                "vpc_resident" if node.vpc_id and "nat" in lowered else "regional_entry",
                "network_connectivity",
                icon,
                can_be_vpc_resident="nat" in lowered,
            )
        if any(token in lowered for token in ("app_runner", "amplify", "appsync")):
            icon = "app_runner.svg" if "app_runner" in lowered else "appsync.svg" if "appsync" in lowered else "api_gateway.svg"
            return _fallback(canonical, "regional_entry", "application", icon)
        if any(token in lowered for token in ("cache", "elasticache", "redis")):
            return _fallback(canonical, "vpc_resident", "data_cache", "elasticache.svg", can_be_vpc_resident=True)
        if node.vpc_id:
            return _fallback(canonical, "vpc_resident", "generic_aws", "privatelink.svg", can_be_vpc_resident=True)
        return _fallback(canonical, "regional_managed_data", "generic_aws", None)


def _fallback(
    service: str,
    placement_scope: str,
    category: str,
    icon: Optional[str],
    can_be_vpc_resident: bool = False,
    endpoint_type: Optional[str] = None,
) -> ServiceInfo:
    return ServiceInfo(
        service=service,
        provider="aws",
        placement_scope=placement_scope,
        category=category,
        icon=icon,
        can_be_vpc_resident=can_be_vpc_resident,
        endpoint_type=endpoint_type,
    )


AWS_PROVIDER = AwsProviderCatalog()
