"""Deterministic production architecture enrichment rules."""

from typing import Dict, Iterable, List, Optional, Set, Tuple

from archway_diagram_compiler._compat import copy_model
from archway_diagram_compiler.enrichment_rule import CompileContext, RuleResult
from archway_diagram_compiler.models import Diagnostic, Flow, SemanticArchitectureSpec, ServiceNode
from archway_diagram_compiler.rule_registry import RuleRegistry


def enrich_production_spec(
    spec: SemanticArchitectureSpec,
) -> Tuple[SemanticArchitectureSpec, List[Diagnostic]]:
    if spec.metadata.get("production_enrichment") is False:
        return spec, []

    nodes = {node.id: copy_model(node, deep=True) for node in spec.nodes}
    flows = [copy_model(flow, deep=True) for flow in spec.flows]
    diagnostics: List[Diagnostic] = []
    context = CompileContext(
        provider="aws",
        enabled_rule_sets=["aws_production_default"],
        metadata={"nodes": nodes, "flows": flows, "diagnostics": diagnostics, "spec_metadata": {**spec.metadata, "title": spec.title}},
    )
    rule_results = AWS_PRODUCTION_RULE_REGISTRY.apply(spec, context)

    enriched = copy_model(
        spec,
        deep=True,
        update={
            "title": _production_title(spec.title),
            "nodes": sorted(nodes.values(), key=lambda item: item.id),
            "flows": sorted(_dedupe_flows(flows), key=lambda item: item.id),
            "metadata": {
                **spec.metadata,
                "diagram_view": "production_logical_service_flow",
                "rule_results": [_model_to_dict(result) for result in rule_results],
            },
        },
    )
    return enriched, diagnostics


def _model_to_dict(model):
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


class _AwsProductionRule:
    provider = "aws"
    default_enabled = True
    rule_set = "aws_production_default"

    def __init__(self, rule_id: str, priority: int, apply_fn, match_fn=None):
        self.id = rule_id
        self.priority = priority
        self._apply_fn = apply_fn
        self._match_fn = match_fn or (lambda spec, context: True)

    def matches(self, spec: SemanticArchitectureSpec, context: CompileContext) -> bool:
        return bool(self._match_fn(spec, context))

    def apply(self, spec: SemanticArchitectureSpec, context: CompileContext) -> RuleResult:
        nodes = context.metadata["nodes"]
        flows = context.metadata["flows"]
        diagnostics = context.metadata["diagnostics"]
        before_nodes = set(nodes)
        before_flows = {flow.id for flow in flows}
        self._apply_fn(spec, context, nodes, flows, diagnostics)
        after_nodes = set(nodes)
        after_flows = {flow.id for flow in flows}
        return RuleResult(
            rule_id=self.id,
            matched=True,
            why=f"{self.id} matched deterministic AWS production rules.",
            changed=before_nodes != after_nodes or before_flows != after_flows,
            added_nodes=sorted(after_nodes - before_nodes),
            added_flows=sorted(after_flows - before_flows),
            diagnostics=list(diagnostics),
        )


def _rule_edge_protection(spec, context, nodes, flows, diagnostics):
    spec_metadata = context.metadata.get("spec_metadata", {})
    if _is_internet_facing(nodes.values(), spec_metadata):
        _ensure_edge_protection(nodes, flows, diagnostics, spec_metadata)


def _rule_cognito(spec, context, nodes, flows, diagnostics):
    _rewrite_cognito_authorizer_flows(nodes, flows, diagnostics)


def _rule_private_api(spec, context, nodes, flows, diagnostics):
    _ensure_private_api_integration(nodes, flows, diagnostics)


def _rule_private_service_access(spec, context, nodes, flows, diagnostics):
    _ensure_private_service_access(nodes, flows, diagnostics)


def _rule_bedrock_kb(spec, context, nodes, flows, diagnostics):
    _expand_bedrock_knowledge_path(nodes, flows, diagnostics)


def _rule_kms_labels(spec, context, nodes, flows, diagnostics):
    _improve_kms_labels(flows)


def _rule_observability_audit(spec, context, nodes, flows, diagnostics):
    _add_observability_and_audit_coverage(nodes, flows, diagnostics)


AWS_PRODUCTION_RULE_REGISTRY = RuleRegistry(
    [
        _AwsProductionRule("aws.edge.ensure_waf_for_public_entry", 10, _rule_edge_protection),
        _AwsProductionRule("aws.auth.cognito_authorizer_association", 20, _rule_cognito),
        _AwsProductionRule("aws.api_gateway.private_integration.vpc_link", 30, _rule_private_api),
        _AwsProductionRule("aws.vpc.endpoint_for_managed_service_from_vpc_workload", 40, _rule_private_service_access),
        _AwsProductionRule("aws.rag.expand_bedrock_knowledge_base_path", 50, _rule_bedrock_kb),
        _AwsProductionRule("aws.security.kms_encryption_association", 60, _rule_kms_labels),
        _AwsProductionRule("aws.observability.cloudwatch_logs_association", 70, _rule_observability_audit),
    ]
)


def _is_internet_facing(nodes: Iterable[ServiceNode], metadata: Dict) -> bool:
    if metadata.get("internet_facing") is not None:
        return bool(metadata["internet_facing"])
    services = {node.service for node in nodes}
    return "cloudfront" in services or "api_gateway" in services or "waf" in services


def _ensure_edge_protection(
    nodes: Dict[str, ServiceNode], flows: List[Flow], diagnostics: List[Diagnostic], spec_metadata: Optional[Dict] = None
) -> None:
    cloudfront = _first_node(nodes.values(), "cloudfront")
    api = _first_node(nodes.values(), "api_gateway")
    if cloudfront is None and api is None:
        return

    user = _first_external_actor(nodes.values()) or _add_node(
        nodes,
        "user",
        _default_actor_label(spec_metadata or {}),
        "external_user",
        "global_edge",
        annotation=True,
    )
    route53 = _add_node(nodes, "route53", "Route 53", "route53", "global_edge")
    waf = _add_node(nodes, "waf", "AWS WAF", "waf", "global_edge")
    shield = _add_node(nodes, "shield", "AWS Shield", "shield", "global_edge")

    edge_target = cloudfront or api
    _remove_direct_flow(flows, user.id, edge_target.id)
    _add_flow(flows, "prod_edge_01", user.id, route53.id, "DNS lookup")
    _add_flow(flows, "prod_edge_02", route53.id, edge_target.id, "resolve application endpoint")
    _add_flow(flows, "prod_edge_03", shield.id, edge_target.id, "DDoS protection")

    if cloudfront is not None and api is not None:
        _add_flow(flows, "prod_edge_04", waf.id, cloudfront.id, "protects CloudFront", metadata={"edge_kind": "control"})
    elif api is not None:
        _add_flow(flows, "prod_edge_04", waf.id, api.id, "protects API", metadata={"edge_kind": "control"})

    diagnostics.append(
        Diagnostic(
            severity="info",
            code="production_edge_protection_added",
            message="Added deterministic User, Route 53, AWS WAF, and AWS Shield edge protection path.",
        )
    )


def _rewrite_cognito_authorizer_flows(
    nodes: Dict[str, ServiceNode], flows: List[Flow], diagnostics: List[Diagnostic]
) -> None:
    cognito = _first_node(nodes.values(), "cognito")
    api = _first_node(nodes.values(), "api_gateway")
    user = nodes.get("user") or _first_external_actor(nodes.values())
    if cognito is None or user is None:
        return

    removed = False
    next_flows: List[Flow] = []
    for flow in flows:
        label = (flow.label or "").lower()
        if api and flow.source == api.id and flow.target == cognito.id and "jwt" in label:
            removed = True
            continue
        next_flows.append(flow)
    flows[:] = next_flows

    _add_flow(flows, "prod_auth_01", user.id, cognito.id, "sign in")
    _add_flow(flows, "prod_auth_02", cognito.id, user.id, "issue JWT")
    if api is not None:
        _add_flow(flows, "prod_auth_03", user.id, api.id, "HTTPS request with JWT")

    if removed:
        diagnostics.append(
            Diagnostic(
                severity="info",
                code="cognito_authorizer_flow_rewritten",
                message="Rewrote API Gateway to Cognito JWT authorizer call as client sign-in and JWT presentation flow.",
            )
        )


def _ensure_private_api_integration(
    nodes: Dict[str, ServiceNode], flows: List[Flow], diagnostics: List[Diagnostic]
) -> None:
    api_nodes = [node for node in nodes.values() if node.service == "api_gateway"]
    if not api_nodes:
        return
    vpc_workload_ids = {
        node.id
        for node in nodes.values()
        if _is_vpc_resident(node.scope) and node.service not in {"vpc_endpoint", "vpc_link"}
    }
    if not vpc_workload_ids:
        return

    for flow in list(flows):
        if flow.source not in {api.id for api in api_nodes} or flow.target not in vpc_workload_ids:
            continue
        workload = nodes[flow.target]
        if workload.service == "lambda":
            flow.label = flow.label or "Lambda invoke"
            continue
        vpc_id = workload.vpc_id or "app-vpc"
        region = workload.region
        vpc_link = _add_node(nodes, f"{workload.id}_vpc_link", "API Gateway VPC Link", "vpc_link", "regional_entry", region=region)
        if workload.service in {"alb", "nlb", "load_balancer", "private_load_balancer"}:
            _remove_flow(flows, flow.id)
            _add_flow(flows, f"{flow.id}_vpc_link", flow.source, vpc_link.id, "private integration")
            _add_flow(flows, f"{flow.id}_lb", vpc_link.id, workload.id, "VPC Link target")
            diagnostics.append(
                Diagnostic(
                    severity="info",
                    code="private_api_integration_added",
                    message="Inserted API Gateway VPC Link before private load balancer target.",
                    node_id=workload.id,
                )
            )
            continue
        lb = _add_node(
            nodes,
            f"{workload.id}_private_lb",
            "Private ALB / NLB",
            "private_load_balancer",
            "vpc_resident",
            region=region,
            vpc_id=vpc_id,
        )
        _remove_flow(flows, flow.id)
        _add_flow(flows, f"{flow.id}_vpc_link", flow.source, vpc_link.id, "private integration")
        _add_flow(flows, f"{flow.id}_lb", vpc_link.id, lb.id, "VPC Link target")
        _add_flow(flows, f"{flow.id}_workload", lb.id, workload.id, flow.label or "forward request")
        diagnostics.append(
            Diagnostic(
                severity="info",
                code="private_api_integration_added",
                message="Inserted API Gateway VPC Link and private load balancer before VPC workload.",
                node_id=workload.id,
            )
        )


def _ensure_private_service_access(
    nodes: Dict[str, ServiceNode], flows: List[Flow], diagnostics: List[Diagnostic]
) -> None:
    endpoint_targets = {
        "bedrock": ("bedrock", "Bedrock interface endpoint", "interface endpoint"),
        "bedrock_knowledge_base": ("bedrock", "Bedrock interface endpoint", "interface endpoint"),
        "opensearch_serverless": ("opensearch", "OpenSearch interface endpoint", "interface endpoint"),
        "opensearch_vector_index": ("opensearch", "OpenSearch interface endpoint", "interface endpoint"),
        "opensearch_hybrid_search": ("opensearch", "OpenSearch interface endpoint", "interface endpoint"),
        "generic_vector_store": ("opensearch", "OpenSearch interface endpoint", "interface endpoint"),
        "dynamodb": ("dynamodb", "DynamoDB gateway endpoint", "gateway endpoint"),
        "secrets_manager": ("secrets_manager", "Secrets Manager interface endpoint", "interface endpoint"),
        "sqs": ("sqs", "SQS interface endpoint", "interface endpoint"),
        "kms": ("kms", "KMS interface endpoint", "interface endpoint"),
        "cloudwatch": ("cloudwatch_logs", "CloudWatch Logs interface endpoint", "interface endpoint"),
        "s3": ("s3", "S3 gateway endpoint", "gateway endpoint"),
    }
    service_by_id = {node.id: node for node in nodes.values()}
    for flow in list(flows):
        source = service_by_id.get(flow.source)
        target = service_by_id.get(flow.target)
        if source is None or target is None:
            continue
        if not _is_vpc_resident(source.scope) or target.service not in endpoint_targets:
            continue
        endpoint_family, endpoint_name, label = endpoint_targets[target.service]
        endpoint = _add_node(
            nodes,
            f"{source.id}_{endpoint_family}_endpoint",
            endpoint_name,
            "vpc_endpoint",
            "vpc_resident",
            region=source.region,
            vpc_id=source.vpc_id,
            metadata={"target_node_id": target.id, "target_node_ids": [target.id], "endpoint_type": label, "endpoint_family": endpoint_family},
        )
        target_node_ids = list(endpoint.metadata.get("target_node_ids") or [])
        if target.id not in target_node_ids:
            target_node_ids.append(target.id)
            endpoint.metadata["target_node_ids"] = sorted(target_node_ids)
        _remove_flow(flows, flow.id)
        _add_flow(flows, f"{flow.id}_endpoint", source.id, endpoint.id, label)
        _add_flow(
            flows,
            f"{flow.id}_service",
            endpoint.id,
            target.id,
            flow.label,
            metadata={"endpoint_access_path": True},
        )
        diagnostics.append(
            Diagnostic(
                severity="info",
                code="private_service_endpoint_added",
                message=f"Inserted {endpoint_name} for private access to {target.name}.",
                node_id=source.id,
            )
        )


def _expand_bedrock_knowledge_path(
    nodes: Dict[str, ServiceNode], flows: List[Flow], diagnostics: List[Diagnostic]
) -> None:
    bedrock = _first_node(nodes.values(), "bedrock")
    if bedrock is None:
        return
    vague_targets = [
        flow
        for flow in flows
        if flow.source == bedrock.id
        and not _is_embedding_or_ingestion_flow(flow, bedrock)
        and (
            "knowledge" in (nodes.get(flow.target).name.lower() if nodes.get(flow.target) else "")
            or "index" in (nodes.get(flow.target).name.lower() if nodes.get(flow.target) else "")
            or nodes.get(flow.target, ServiceNode(id="x", name="x", service="x")).service == "kendra"
        )
    ]
    if not vague_targets:
        return

    region = bedrock.region
    kb = _add_node(nodes, "bedrock_knowledge_base", "Amazon Bedrock Knowledge Base", "bedrock_knowledge_base", "regional_managed_ai", region=region)
    vector = _add_node(
        nodes,
        "opensearch_vector_index",
        "OpenSearch Serverless vector index",
        "opensearch_serverless",
        "regional_managed_data",
        region=region,
    )
    for flow in vague_targets:
        old_target = flow.target
        _remove_flow(flows, flow.id)
        if old_target in nodes:
            _remove_node_if_only_vague_index(nodes, flows, old_target)
        _add_flow(flows, f"{flow.id}_kb", bedrock.id, kb.id, "retrieve with knowledge base")
        _add_flow(flows, f"{flow.id}_vector", kb.id, vector.id, "vector search")

    s3 = _first_node(nodes.values(), "s3")
    if s3 is not None:
        _add_flow(flows, "prod_kb_01", kb.id, s3.id, "source documents")

    diagnostics.append(
        Diagnostic(
            severity="info",
            code="bedrock_knowledge_base_expanded",
            message="Expanded vague knowledge index into Bedrock Knowledge Base and OpenSearch Serverless vector index.",
        )
    )


def _is_embedding_or_ingestion_flow(flow: Flow, source: ServiceNode) -> bool:
    label = (flow.label or "").lower()
    role = str(source.metadata.get("role") or source.metadata.get("ai_role") or "").lower()
    return (
        "embedding" in label
        or "ingestion" in label
        or "chunk" in label
        or role in {"embedding_model", "embedding_job", "document_ingestion", "document_chunker"}
    )


def _improve_kms_labels(flows: List[Flow]) -> None:
    for flow in flows:
        if flow.label and flow.label.lower() == "decrypt":
            flow.label = "envelope encryption / decrypt secret"


def _contains_ai_or_model_services(nodes: Iterable[ServiceNode]) -> bool:
    ai_services = {
        "bedrock",
        "bedrock_knowledge_base",
        "kendra",
        "opensearch",
        "opensearch_serverless",
        "sagemaker",
    }
    ai_roles = {
        "agent",
        "ai",
        "embedding_job",
        "embedding_model",
        "foundation_model",
        "model",
        "rag",
        "retrieval",
        "vector_store",
    }
    for node in nodes:
        role_values = {
            str(node.metadata.get(key, "")).lower()
            for key in ("role", "ai_role", "category", "semantic_role")
        }
        if node.service in ai_services or role_values & ai_roles:
            return True
    return False


def _add_observability_and_audit_coverage(
    nodes: Dict[str, ServiceNode], flows: List[Flow], diagnostics: List[Diagnostic]
) -> None:
    cloudwatch = _first_node(nodes.values(), "cloudwatch")
    cloudtrail = _first_node(nodes.values(), "cloudtrail")
    audit_bucket = None
    if cloudtrail is not None:
        audit_bucket = _add_node(
            nodes,
            "audit_log_bucket",
            "Audit S3 bucket",
            "s3",
            "regional_managed_data",
            region=cloudtrail.region,
            metadata={"audit_log_bucket": True},
        )
    covered = {"cloudwatch", "cloudtrail", "vpc_endpoint", "route53", "shield"}

    if cloudwatch is not None:
        telemetry_label = (
            "Application and model telemetry"
            if _contains_ai_or_model_services(nodes.values())
            else "Application telemetry"
        )
        sources = [
            node.name
            for node in sorted(nodes.values(), key=lambda item: item.id)
            if not node.annotation
            and node.id != cloudwatch.id
            and node.service not in covered
            and node.service in {"api_gateway", "waf", "bedrock", "ecs", "lambda", "private_load_balancer"}
        ]
        if sources:
            summary = _add_node(
                nodes,
                "observability_sources",
                telemetry_label,
                "annotation",
                "observability",
                region=cloudwatch.region,
                annotation=True,
                metadata={"observability_sources": sources},
            )
            _add_flow(flows, "prod_observe_summary", summary.id, cloudwatch.id, "logs / metrics")
        diagnostics.append(
            Diagnostic(
                severity="info",
                code="observability_coverage_added",
                message="Added CloudWatch log and metric coverage for production-facing services.",
            )
        )

    if cloudtrail is not None and audit_bucket is not None:
        for flow in list(flows):
            if flow.source == cloudtrail.id and nodes.get(flow.target, audit_bucket).service == "s3":
                _remove_flow(flows, flow.id)
        sources = [
            node.name
            for node in sorted(nodes.values(), key=lambda item: item.id)
            if not node.annotation
            and node.service not in {"cloudwatch", "cloudtrail", "vpc_endpoint"}
            and not node.metadata.get("audit_log_bucket")
            and node.scope
            in {"regional_entry", "regional_identity", "regional_managed_ai", "regional_managed_data", "regional_security"}
        ]
        if sources:
            summary = _add_node(
                nodes,
                "audit_sources",
                "Audited service activity",
                "annotation",
                "audit",
                region=cloudtrail.region,
                annotation=True,
                metadata={"audit_sources": sources},
            )
            _add_flow(flows, "prod_audit_summary", summary.id, cloudtrail.id, "API activity")
        _add_flow(flows, "prod_audit_bucket", cloudtrail.id, audit_bucket.id, "audit log delivery")
        diagnostics.append(
            Diagnostic(
                severity="info",
                code="audit_coverage_added",
                message="Added CloudTrail audit coverage for regional managed services.",
            )
        )


def _production_title(title: str) -> str:
    suffix = "Production logical service flow"
    return title if suffix.lower() in title.lower() else f"{title} - {suffix}"


def _first_node(nodes: Iterable[ServiceNode], service: str) -> Optional[ServiceNode]:
    matches = sorted((node for node in nodes if node.service == service), key=lambda item: item.id)
    return matches[0] if matches else None


def _first_external_actor(nodes: Iterable[ServiceNode]) -> Optional[ServiceNode]:
    matches = sorted(
        (
            node
            for node in nodes
            if node.service in {"external_actor", "external_user"}
            or node.metadata.get("role") in {"user", "external_actor"}
        ),
        key=lambda item: item.id,
    )
    return matches[0] if matches else None


def _default_actor_label(metadata: Dict) -> str:
    domain = str(metadata.get("domain") or "").lower()
    title = str(metadata.get("title") or "").lower()
    if domain == "compliance" or "compliance" in title:
        return "Compliance Analyst"
    return "User"


def _add_node(
    nodes: Dict[str, ServiceNode],
    node_id: str,
    name: str,
    service: str,
    scope: str,
    region: Optional[str] = None,
    vpc_id: Optional[str] = None,
    annotation: bool = False,
    metadata: Optional[Dict] = None,
) -> ServiceNode:
    if node_id not in nodes:
        nodes[node_id] = ServiceNode(
            id=node_id,
            name=name,
            service=service,
            scope=scope,
            region=region,
            vpc_id=vpc_id,
            annotation=annotation,
            metadata=metadata or {},
        )
    return nodes[node_id]


def _add_flow(
    flows: List[Flow],
    flow_id: str,
    source: str,
    target: str,
    label: Optional[str] = None,
    metadata: Optional[Dict] = None,
) -> None:
    if source == target:
        return
    if any(flow.source == source and flow.target == target and (flow.label or "") == (label or "") for flow in flows):
        return
    flows.append(Flow(id=flow_id, source=source, target=target, label=label, metadata=metadata or {}))


def _remove_flow(flows: List[Flow], flow_id: str) -> None:
    flows[:] = [flow for flow in flows if flow.id != flow_id]


def _remove_direct_flow(flows: List[Flow], source: str, target: str) -> None:
    flows[:] = [flow for flow in flows if not (flow.source == source and flow.target == target)]


def _remove_node_if_only_vague_index(nodes: Dict[str, ServiceNode], flows: List[Flow], node_id: str) -> None:
    node = nodes.get(node_id)
    if node is None:
        return
    if node.service not in {"kendra"} and "knowledge" not in node.name.lower() and "index" not in node.name.lower():
        return
    if any(flow.source == node_id or flow.target == node_id for flow in flows):
        return
    nodes.pop(node_id, None)


def _dedupe_flows(flows: Iterable[Flow]) -> List[Flow]:
    seen: Set[Tuple[str, str, str, str]] = set()
    deduped: List[Flow] = []
    for flow in flows:
        key = (flow.source, flow.target, flow.label or "", flow.protocol or "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(flow)
    return deduped


def _is_vpc_resident(scope: Optional[str]) -> bool:
    return scope in {"vpc_workload", "vpc_data", "vpc_resident"}
