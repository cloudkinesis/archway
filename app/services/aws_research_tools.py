from urllib.parse import urlparse

from app.core.config import get_settings
from app.domain.evidence import EvidenceMode, source_allowed_for_mode
from app.models.domain import EvidenceItem, SessionPhase
from app.services.mcp_http import MCPHTTPClient, mcp_result_to_evidence
from app.services.mcp_stdio import MCPStdioClient
from app.services.pricing_filter_mapper import PricingFilterPlan, pricing_filter_plan_for_service
from app.services.tavily import TavilySearchClient
from app.tooling.registry import ToolPolicyEngine, build_tool_registry


AWS_DOCS_DOMAINS = ["docs.aws.amazon.com", "aws.amazon.com"]
AWS_PRICING_DOMAINS = ["aws.amazon.com"]
AWS_OFFICIAL_HOSTS = {"aws.amazon.com", "docs.aws.amazon.com"}
AWS_MANAGED_MCP_HOST_SUFFIX = ".api.aws"


class AWSDocsAdapter:
    def __init__(self):
        self.settings = get_settings()
        self.policy = ToolPolicyEngine(build_tool_registry())

    async def search(self, query: str, session_id: str) -> list[EvidenceItem]:
        if self.settings.enable_aws_docs_mcp and self.settings.aws_docs_mcp_url:
            self.policy.assert_allowed("aws_docs_mcp", SessionPhase.research, {"query": query}, session_id)
            try:
                client = MCPHTTPClient(
                    server_url=self.settings.aws_docs_mcp_url,
                    auth_token=self.settings.aws_docs_mcp_auth_token,
                    server_name="AWS Documentation MCP",
                    session_id=session_id,
                )
                result = await client.call_tool(*_docs_tool_call(self.settings.aws_docs_mcp_url, query))
                return mcp_result_to_evidence(
                    result=result,
                    source_type="aws_docs",
                    tool_name=_docs_tool_label(self.settings.aws_docs_mcp_url),
                    fallback_title="AWS documentation result",
                    confidence="high",
                )
            except Exception as exc:
                fallback = await _official_aws_web_fallback(
                    query=query,
                    session_id=session_id,
                    source_type="aws_docs",
                    tool_name="AWS Documentation official web fallback",
                    include_domains=AWS_DOCS_DOMAINS,
                    max_results=5,
                )
                return [
                    EvidenceItem(
                        source_type="mcp",
                        title="AWS Documentation MCP failed over to official web fallback",
                        quote_or_summary=f"AWS Documentation MCP failed with {type(exc).__name__}; Archway used read-only official AWS web evidence instead.",
                        tool_name="AWS Documentation MCP",
                        confidence="low",
                    ),
                    *fallback,
                ]
        return await _official_aws_web_fallback(
            query=query,
            session_id=session_id,
            source_type="aws_docs",
            tool_name="AWS Documentation official web fallback",
            include_domains=AWS_DOCS_DOMAINS,
            max_results=5,
        )


class AWSPricingAdapter:
    def __init__(self):
        self.settings = get_settings()
        self.policy = ToolPolicyEngine(build_tool_registry())

    async def lookup(self, services: list[str], region: str, session_id: str) -> list[EvidenceItem]:
        if self.settings.enable_aws_pricing_mcp and self.settings.aws_pricing_mcp_command:
            self.policy.assert_allowed(
                "aws_pricing_mcp",
                SessionPhase.research,
                {"services": services, "region": region, "transport": "stdio"},
                session_id,
            )
            try:
                return await self._lookup_aws_labs_pricing_mcp(services, region, session_id)
            except Exception as exc:
                fallback = await self._pricing_web_fallback(services, region, session_id)
                return [
                    EvidenceItem(
                        source_type="mcp",
                        title="AWS Labs Pricing MCP failed over to official web fallback",
                        quote_or_summary=f"AWS Labs Pricing MCP failed with {type(exc).__name__}; Archway used read-only official AWS pricing pages instead.",
                        tool_name="AWS Labs Pricing MCP",
                        confidence="low",
                    ),
                    *fallback,
                ]
        if self.settings.enable_aws_pricing_mcp and self.settings.aws_pricing_mcp_url:
            self.policy.assert_allowed(
                "aws_pricing_mcp",
                SessionPhase.research,
                {"services": services, "region": region},
                session_id,
            )
            try:
                client = MCPHTTPClient(
                    server_url=self.settings.aws_pricing_mcp_url,
                    auth_token=self.settings.aws_pricing_mcp_auth_token,
                    server_name="AWS Pricing MCP",
                    session_id=session_id,
                )
                tool_name, arguments, label, confidence = _pricing_tool_call(self.settings.aws_pricing_mcp_url, services, region)
                result = await client.call_tool(tool_name, arguments)
                return mcp_result_to_evidence(
                    result=result,
                    source_type="aws_pricing",
                    tool_name=label,
                    fallback_title="AWS pricing result",
                    confidence=confidence,
                )
            except Exception as exc:
                fallback = await self._pricing_web_fallback(services, region, session_id)
                return [
                    EvidenceItem(
                        source_type="mcp",
                        title="AWS Pricing MCP failed over to official web fallback",
                        quote_or_summary=f"AWS Pricing MCP failed with {type(exc).__name__}; Archway used read-only official AWS pricing pages instead.",
                        tool_name="AWS Pricing MCP",
                        confidence="low",
                    ),
                    *fallback,
                ]
        if self.settings.enable_aws_pricing_reference_mcp and self.settings.aws_pricing_reference_mcp_url:
            self.policy.assert_allowed(
                "aws_pricing_reference_mcp",
                SessionPhase.research,
                {"services": services, "region": region},
                session_id,
            )
            client = MCPHTTPClient(
                server_url=self.settings.aws_pricing_reference_mcp_url,
                auth_token=self.settings.aws_pricing_reference_mcp_auth_token,
                server_name="AWS Pricing reference MCP",
                session_id=session_id,
            )
            tool_name, arguments, label, confidence = _pricing_tool_call(
                self.settings.aws_pricing_reference_mcp_url,
                services,
                region,
            )
            result = await client.call_tool(tool_name, arguments)
            return mcp_result_to_evidence(
                result=result,
                source_type="aws_pricing",
                tool_name=label,
                fallback_title="AWS pricing reference result",
                confidence=confidence,
            )
        return await _official_aws_web_fallback(
            query=f"AWS pricing pages for {', '.join(dict.fromkeys(services[:8])) or 'AWS services'} in {region}",
            session_id=session_id,
            source_type="aws_pricing",
            tool_name="AWS Pricing official web fallback",
            include_domains=AWS_PRICING_DOMAINS,
            max_results=6,
            require_pricing_page=True,
        )

    async def _pricing_web_fallback(self, services: list[str], region: str, session_id: str) -> list[EvidenceItem]:
        service_terms = ", ".join(dict.fromkeys(services[:8])) or "AWS services"
        return await _official_aws_web_fallback(
            query=f"AWS pricing pages for {service_terms} in {region}",
            session_id=session_id,
            source_type="aws_pricing",
            tool_name="AWS Pricing official web fallback",
            include_domains=AWS_PRICING_DOMAINS,
            max_results=6,
            require_pricing_page=True,
        )

    async def _lookup_aws_labs_pricing_mcp(self, services: list[str], region: str, session_id: str) -> list[EvidenceItem]:
        plans = _unique_pricing_plans(services, region)
        if not plans:
            raise RuntimeError("No supported AWS Price List service-code mappings were found for selected services.")
        client = MCPStdioClient(
            command=self.settings.aws_pricing_mcp_command or "",
            args=self.settings.aws_pricing_mcp_args,
            env={
                "FASTMCP_LOG_LEVEL": "ERROR",
                "AWS_PROFILE": self.settings.aws_pricing_mcp_aws_profile,
                "AWS_REGION": self.settings.aws_pricing_mcp_aws_region,
            },
            server_name="AWS Labs Pricing MCP",
            session_id=session_id,
            timeout_seconds=120,
        )
        calls = [("get_pricing", _aws_labs_pricing_arguments(plan, region)) for plan in plans[:12]]
        results = await client.call_tools(calls)
        evidence: list[EvidenceItem] = []
        for plan, result in zip(plans, results, strict=False):
            body = _compact_mcp_tool_result(result)
            evidence.append(
                EvidenceItem(
                    source_type="aws_pricing",
                    title=f"AWS Labs Pricing MCP result for {plan.service_name}",
                    quote_or_summary=(
                        f"AWS Labs Pricing MCP returned live Price List data for service recommendation '{plan.service_name}' "
                        f"using service_code={plan.service_code}, region={region}, filters={plan.filters}. Result excerpt: {body}"
                    )[:1600],
                    tool_name="AWS Labs Pricing MCP",
                    confidence="high",
                )
            )
        if not evidence:
            raise RuntimeError("AWS Labs Pricing MCP returned no pricing evidence.")
        return evidence


async def _official_aws_web_fallback(
    *,
    query: str,
    session_id: str,
    source_type: str,
    tool_name: str,
    include_domains: list[str],
    max_results: int,
    require_pricing_page: bool = False,
) -> list[EvidenceItem]:
    settings = get_settings()
    if not settings.enable_aws_official_web_fallback:
        raise PermissionError("Official AWS web fallback is disabled.")
    if not settings.enable_web_search or not settings.tavily_api_key:
        raise PermissionError("Official AWS web fallback requires configured Tavily web search.")
    response = await TavilySearchClient().search(
        query,
        session_id,
        max_results=max_results,
        include_domains=include_domains,
        purpose="aws_official_fallback",
    )
    evidence: list[EvidenceItem] = []
    for result in response.results:
        url = str(result.url) if result.url else ""
        if not _is_allowed_aws_url(url, require_pricing_page=require_pricing_page):
            continue
        evidence.append(
            EvidenceItem(
                source_type=source_type,
                title=result.title,
                url=result.url,
                quote_or_summary=result.content or "Official AWS page returned for this research query.",
                tool_name=tool_name,
                confidence="medium",
            )
        )
    if not evidence and response.answer:
        evidence.append(
            EvidenceItem(
                source_type=source_type,
                title=f"Official AWS search summary: {query}",
                quote_or_summary=(
                    response.answer[:900]
                    + " Official AWS web fallback returned a summary but no URL-qualified result; refresh with AWS MCP before relying on this claim."
                )[:1200],
                tool_name=tool_name,
                confidence="low",
            )
        )
    if not evidence:
        raise RuntimeError("Official AWS web fallback returned no URL-qualified AWS evidence.")
    return evidence


def _is_allowed_aws_url(url: str, *, require_pricing_page: bool) -> bool:
    if not url:
        return False
    if not source_allowed_for_mode("aws_pricing" if require_pricing_page else "aws_docs", url, EvidenceMode.AWS_OFFICIAL_ONLY):
        return False
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in AWS_OFFICIAL_HOSTS:
        return False
    if require_pricing_page and "/pricing" not in parsed.path.lower():
        return False
    return True


def _is_managed_aws_mcp_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.lower().endswith(AWS_MANAGED_MCP_HOST_SUFFIX) and parsed.path.rstrip("/") == "/mcp"


def _docs_tool_call(url: str, query: str) -> tuple[str, dict]:
    if _is_managed_aws_mcp_url(url):
        return "aws___search_documentation", {"search_phrase": query, "topics": ["general"], "limit": 5}
    return "search_documentation", {"query": query, "limit": 5}


def _docs_tool_label(url: str) -> str:
    if _is_managed_aws_mcp_url(url):
        return "AWS Managed MCP documentation search"
    return "AWS Documentation MCP"


def _pricing_tool_call(url: str, services: list[str], region: str) -> tuple[str, dict, str, str]:
    if _is_managed_aws_mcp_url(url):
        service_terms = ", ".join(dict.fromkeys(services[:8])) or "AWS services"
        return (
            "aws___search_documentation",
            {
                "search_phrase": f"AWS pricing and cost guidance for {service_terms} in {region}",
                "topics": ["general", "reference_documentation"],
                "limit": 5,
            },
            "AWS Managed MCP pricing documentation search",
            "medium",
        )
    return "lookup_pricing", {"services": services, "region": region}, "AWS Pricing MCP", "high"


def _unique_pricing_plans(services: list[str], region: str) -> list[PricingFilterPlan]:
    plans: list[PricingFilterPlan] = []
    seen: set[tuple[str, str]] = set()
    for service in services:
        plan = pricing_filter_plan_for_service(service, region_code=region)
        if not plan:
            continue
        key = (plan.service_name.lower(), plan.service_code)
        if key in seen:
            continue
        seen.add(key)
        plans.append(plan)
    return plans


def _aws_labs_pricing_arguments(plan: PricingFilterPlan, region: str) -> dict:
    filters = [{"Field": field, "Type": "EQUALS", "Value": value} for field, value in plan.filters.items()]
    return {
        "service_code": plan.service_code,
        "region": region,
        "filters": filters,
        "max_results": 5,
        "max_allowed_characters": 12000,
        "output_options": {
            "pricing_terms": ["OnDemand", "FlatRate"],
            "exclude_free_products": True,
        },
    }


def _compact_mcp_tool_result(result: dict) -> str:
    content = result.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        if parts:
            return " ".join(parts)[:900]
    try:
        import json

        return json.dumps(result, sort_keys=True)[:900]
    except Exception:
        return str(result)[:900]
