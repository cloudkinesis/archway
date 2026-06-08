import pytest


@pytest.fixture(autouse=True)
def deterministic_llm_by_default(monkeypatch):
    monkeypatch.setenv("ARCHWAY_LLM_PROVIDER", "deterministic")
    monkeypatch.delenv("ARCHWAY_BEDROCK_MODEL_ID", raising=False)
    monkeypatch.setenv("ARCHWAY_ENABLE_WEB_SEARCH", "false")
    monkeypatch.setenv("ARCHWAY_ENABLE_COMPETITOR_WEB_SEARCH", "false")
    monkeypatch.setenv("ARCHWAY_TAVILY_MAX_CALLS_PER_SESSION", "0")
    monkeypatch.setenv("ARCHWAY_ENABLE_AWS_PRICING_MCP", "false")
    monkeypatch.delenv("ARCHWAY_AWS_PRICING_MCP_URL", raising=False)
    monkeypatch.delenv("ARCHWAY_AWS_PRICING_MCP_COMMAND", raising=False)
    from app.core.config import get_settings

    get_settings.cache_clear()
