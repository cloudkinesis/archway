import pytest

from app.core.config import get_settings
from app.services.research import ResearchOrchestrator
from app.services.research_view_model import build_research_view_model
from app.services.synthesis import SynthesisEngine
from app.services.tavily import TavilySearchResponse, TavilySearchResult, tavily_response_to_evidence
from app.tooling.registry import build_tool_registry


def test_tavily_key_alone_does_not_enable_web_search_registry(monkeypatch):
    monkeypatch.setenv("ARCHWAY_TAVILY_API_KEY", "test-key")
    monkeypatch.delenv("ARCHWAY_TAVILY_MCP_URL", raising=False)
    monkeypatch.setenv("ARCHWAY_ENABLE_WEB_SEARCH", "false")
    get_settings.cache_clear()

    web_entry = next(entry for entry in build_tool_registry() if entry.id == "web_search")

    assert web_entry.enabled is False
    assert web_entry.read_only is True
    assert web_entry.write_capable is False


def test_tavily_requires_explicit_web_search_enablement(monkeypatch):
    monkeypatch.delenv("ARCHWAY_TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("ARCHWAY_TAVILY_MCP_URL", "https://mcp.tavily.com/mcp/?tavilyApiKey=test-key")
    monkeypatch.setenv("ARCHWAY_ENABLE_WEB_SEARCH", "true")
    monkeypatch.setenv("ARCHWAY_ENABLE_COMPETITOR_WEB_SEARCH", "true")
    monkeypatch.setenv("ARCHWAY_TAVILY_MAX_CALLS_PER_SESSION", "1")
    get_settings.cache_clear()

    settings = get_settings()
    web_entry = next(entry for entry in build_tool_registry() if entry.id == "web_search")

    assert settings.tavily_api_key == "test-key"
    assert settings.tavily_mcp_url_configured is True
    assert settings.tavily_max_calls_per_session == 1
    assert web_entry.enabled is True


def test_aws_mcp_urls_enable_aws_tool_registry(monkeypatch):
    monkeypatch.setenv("ARCHWAY_AWS_DOCS_MCP_URL", "https://example.com/aws-docs-mcp")
    monkeypatch.setenv("ARCHWAY_AWS_PRICING_MCP_URL", "https://example.com/aws-pricing-mcp")
    monkeypatch.setenv("ARCHWAY_AWS_PRICING_REFERENCE_MCP_URL", "https://example.com/aws-pricing-reference-mcp")
    get_settings.cache_clear()

    entries = {entry.id: entry for entry in build_tool_registry()}

    assert entries["aws_docs_mcp"].enabled is True
    assert entries["aws_pricing_mcp"].enabled is True
    assert entries["aws_pricing_reference_mcp"].enabled is True
    assert entries["aws_docs_mcp"].read_only is True
    assert entries["aws_pricing_mcp"].write_capable is False


def test_tavily_response_becomes_citable_evidence():
    response = TavilySearchResponse(
        query="aws ai architecture",
        answer="Summary answer",
        results=[
            TavilySearchResult(
                title="AWS reference",
                url="https://aws.amazon.com/ai/",
                content="AWS AI service overview",
            )
        ],
    )

    evidence = tavily_response_to_evidence(response)

    assert len(evidence) == 2
    assert all(item.source_type == "web" for item in evidence)
    assert all(item.tool_name == "Tavily Web Search" for item in evidence)


async def _fake_competitor_search(self, query, session_id, *, max_results=5, include_domains=None, purpose="general_web"):
    assert purpose == "competitor_scan"
    self._consume_budget(session_id, purpose)
    return TavilySearchResponse(
        query=query,
        answer=f"Market scan summary for {query[:40]}",
        results=[
            TavilySearchResult(
                title=f"Competitor platform overview {query[:16]}",
                url=f"https://example.com/competitor-{abs(hash(query)) % 10000}",
                content="Competitor offers adjacent operational analytics capabilities, packaged workflow views, integrations, and buyer-facing operating dashboards.",
            )
        ],
    )


@pytest.mark.asyncio
async def test_competitor_search_runs_when_tavily_is_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("ARCHWAY_TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("ARCHWAY_ENABLE_WEB_SEARCH", "true")
    monkeypatch.setenv("ARCHWAY_ENABLE_COMPETITOR_WEB_SEARCH", "true")
    monkeypatch.setenv("ARCHWAY_TAVILY_MAX_CALLS_PER_SESSION", "2")
    get_settings.cache_clear()
    monkeypatch.setattr("app.services.tavily.TavilySearchClient.search", _fake_competitor_search)

    brief = SynthesisEngine().create_initial_brief("Healthcare OR scheduling analytics across hospitals with PHI controls.")
    report = await ResearchOrchestrator().run_research(brief, "sess_tavily_regression")

    status = report.metadata["competitor_scan"]
    assert status["tavily_enabled"] is True
    assert status["competitor_scan_enabled"] is True
    assert status["queries_attempted"] >= 2
    assert status["queries_executed"] == 2
    assert status["results_returned"] >= 2
    assert status["results_used"] >= 4
    assert status["query_plan"]
    assert "Competitor / market scan completed with Tavily" in report.competitor_analysis
    assert "skipped to preserve quota" not in report.competitor_analysis.lower()

    view_model = build_research_view_model(
        report.session_id,
        report.model_dump(mode="json"),
        None,
        report.pricing_analysis.model_dump(mode="json"),
        None,
    )
    assert view_model is not None
    assert view_model.competitor_scan.status == "completed"
    assert view_model.competitor_scan.analysis_summary
    assert view_model.competitor_scan.aws_positioning_implications
    assert view_model.competitor_scan.competitors
