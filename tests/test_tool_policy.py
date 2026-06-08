import pytest

from app.models.domain import SessionPhase
from app.core.config import get_settings
from app.tooling.registry import ToolPolicyEngine, build_tool_registry


def test_tool_policy_blocks_disabled_tool(monkeypatch):
    monkeypatch.delenv("ARCHWAY_TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("ARCHWAY_TAVILY_MCP_URL", raising=False)
    monkeypatch.setenv("ARCHWAY_ENABLE_WEB_SEARCH", "false")
    get_settings.cache_clear()
    policy = ToolPolicyEngine(build_tool_registry())

    with pytest.raises(PermissionError):
        policy.assert_allowed("web_search", SessionPhase.research, {"q": "test"})


def test_tool_policy_allows_local_read_only_tool():
    policy = ToolPolicyEngine(build_tool_registry())

    entry = policy.assert_allowed("local_policy", SessionPhase.research, {"q": "test"})

    assert entry.read_only is True
    assert entry.write_capable is False
