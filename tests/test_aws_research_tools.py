from app.core.config import get_settings
from app.models.domain import EvidenceItem
from app.services.aws_research_tools import AWSDocsAdapter, AWSPricingAdapter, _is_allowed_aws_url
from app.services.tavily import TavilySearchResponse, TavilySearchResult
import pytest


def test_official_aws_url_filter_rejects_non_aws_and_non_pricing_pages():
    assert _is_allowed_aws_url("https://docs.aws.amazon.com/iot/latest/developerguide/what-is-aws-iot.html", require_pricing_page=False)
    assert _is_allowed_aws_url("https://aws.amazon.com/kinesis/data-streams/pricing/", require_pricing_page=True)
    assert not _is_allowed_aws_url("https://example.com/aws/pricing", require_pricing_page=False)
    assert not _is_allowed_aws_url("https://aws.amazon.com/kinesis/data-streams/", require_pricing_page=True)


async def _fake_search(_self, query, session_id, *, max_results=5, include_domains=None, purpose="general_web"):
    return TavilySearchResponse(
        query=query,
        results=[
            TavilySearchResult(
                title="AWS IoT docs",
                url="https://docs.aws.amazon.com/iot/latest/developerguide/what-is-aws-iot.html",
                content="Official AWS IoT documentation.",
            ),
            TavilySearchResult(
                title="Third party",
                url="https://example.com/aws-iot",
                content="Should be ignored.",
            ),
            TavilySearchResult(
                title="Kinesis pricing",
                url="https://aws.amazon.com/kinesis/data-streams/pricing/",
                content="Official AWS Kinesis pricing page.",
            ),
        ],
    )


async def _failing_mcp(_self, tool_name, arguments):
    raise RuntimeError("down")


async def _fake_stdio_calls(self, calls):
    assert calls[0][0] == "get_pricing"
    arguments = calls[0][1]
    assert arguments["service_code"] == "AmazonKinesis"
    assert arguments["region"] == "us-east-1"
    assert {"Field": "productFamily", "Type": "EQUALS", "Value": "Kinesis Streams"} in arguments["filters"]
    return [{"content": [{"type": "text", "text": "Live pricing rows for Amazon Kinesis Data Streams."}]}]


@pytest.mark.asyncio
async def test_docs_adapter_uses_official_web_fallback_when_mcp_absent(monkeypatch):
    monkeypatch.delenv("ARCHWAY_AWS_DOCS_MCP_URL", raising=False)
    monkeypatch.setenv("ARCHWAY_TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("ARCHWAY_ENABLE_WEB_SEARCH", "true")
    monkeypatch.setenv("ARCHWAY_TAVILY_MAX_CALLS_PER_SESSION", "10")
    monkeypatch.setenv("ARCHWAY_ENABLE_AWS_OFFICIAL_WEB_FALLBACK", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("app.services.tavily.TavilySearchClient.search", _fake_search)

    evidence = await AWSDocsAdapter().search("AWS IoT architecture", "sess_test")

    assert evidence
    assert all(item.source_type == "aws_docs" for item in evidence)
    assert all("fallback" in (item.tool_name or "").lower() for item in evidence)
    assert all(str(item.url).startswith(("https://docs.aws.amazon.com", "https://aws.amazon.com")) for item in evidence if item.url)


@pytest.mark.asyncio
async def test_pricing_adapter_filters_official_pricing_pages(monkeypatch):
    monkeypatch.delenv("ARCHWAY_AWS_PRICING_MCP_URL", raising=False)
    monkeypatch.delenv("ARCHWAY_AWS_DOCS_MCP_URL", raising=False)
    monkeypatch.delenv("ARCHWAY_AWS_PRICING_REFERENCE_MCP_URL", raising=False)
    monkeypatch.setenv("ARCHWAY_ENABLE_AWS_PRICING_REFERENCE_MCP", "false")
    monkeypatch.setenv("ARCHWAY_TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("ARCHWAY_ENABLE_WEB_SEARCH", "true")
    monkeypatch.setenv("ARCHWAY_TAVILY_MAX_CALLS_PER_SESSION", "10")
    monkeypatch.setenv("ARCHWAY_ENABLE_AWS_OFFICIAL_WEB_FALLBACK", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("app.services.tavily.TavilySearchClient.search", _fake_search)

    evidence = await AWSPricingAdapter().lookup(["Amazon Kinesis Data Streams"], "us-east-1", "sess_test")

    assert [item.title for item in evidence] == ["Kinesis pricing"]
    assert all(item.source_type == "aws_pricing" for item in evidence)


@pytest.mark.asyncio
async def test_pricing_adapter_uses_aws_labs_stdio_mcp_when_configured(monkeypatch):
    monkeypatch.setenv("ARCHWAY_ENABLE_AWS_PRICING_MCP", "true")
    monkeypatch.setenv("ARCHWAY_AWS_PRICING_MCP_COMMAND", "uvx")
    monkeypatch.setenv("ARCHWAY_AWS_PRICING_MCP_ARGS", "awslabs.aws-pricing-mcp-server@latest")
    monkeypatch.setenv("ARCHWAY_AWS_PRICING_MCP_AWS_PROFILE", "default")
    monkeypatch.setenv("ARCHWAY_AWS_PRICING_MCP_AWS_REGION", "us-east-1")
    get_settings.cache_clear()
    monkeypatch.setattr("app.services.mcp_stdio.MCPStdioClient.call_tools", _fake_stdio_calls)

    evidence = await AWSPricingAdapter().lookup(["Amazon Kinesis Data Streams"], "us-east-1", "sess_test")

    assert evidence[0].source_type == "aws_pricing"
    assert evidence[0].tool_name == "AWS Labs Pricing MCP"
    assert evidence[0].confidence == "high"
    assert "service recommendation 'Amazon Kinesis Data Streams'" in evidence[0].quote_or_summary


@pytest.mark.asyncio
async def test_configured_mcp_failure_records_failover_notice(monkeypatch):
    monkeypatch.setenv("ARCHWAY_AWS_DOCS_MCP_URL", "https://example.com/mcp")
    monkeypatch.setenv("ARCHWAY_TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("ARCHWAY_ENABLE_WEB_SEARCH", "true")
    monkeypatch.setenv("ARCHWAY_TAVILY_MAX_CALLS_PER_SESSION", "10")
    monkeypatch.setenv("ARCHWAY_ENABLE_AWS_OFFICIAL_WEB_FALLBACK", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("app.services.aws_research_tools.MCPHTTPClient.call_tool", _failing_mcp)
    monkeypatch.setattr("app.services.tavily.TavilySearchClient.search", _fake_search)

    evidence = await AWSDocsAdapter().search("AWS IoT architecture", "sess_test")

    assert isinstance(evidence[0], EvidenceItem)
    assert evidence[0].source_type == "mcp"
    assert "failed over" in evidence[0].title
    assert any(item.source_type == "aws_docs" for item in evidence[1:])
