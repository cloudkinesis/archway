from app.models.domain import HealthCheckResult, HealthStatus
from app.core.config import get_settings
from app.services.health import HealthService, _REMOTE_CHECK_CACHE


def test_remote_health_checks_are_cached_until_forced():
    _REMOTE_CHECK_CACHE.clear()
    calls = {"count": 0}

    async def check():
        calls["count"] += 1
        return HealthCheckResult(id="remote", label="Remote", status=HealthStatus.ready, required=False, reason="ok")

    service = HealthService()
    first = _run(service._cached_remote_check("remote", check, force=False))
    second = _run(service._cached_remote_check("remote", check, force=False))
    third = _run(service._cached_remote_check("remote", check, force=True))

    assert calls["count"] == 2
    assert first.details["cached"] is False
    assert second.details["cached"] is True
    assert third.details["cached"] is False


def test_open_world_live_mode_health_reports_default_audit_floor(monkeypatch):
    for key in (
        "ARCHWAY_ENABLE_OPEN_WORLD_UNDERSTANDING",
        "ARCHWAY_AGENTIC_MODE",
        "ARCHWAY_LLM_PROVIDER",
        "ARCHWAY_BEDROCK_MODEL_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()

    result = HealthService()._open_world_live_mode_check()

    assert result.id == "open_world_live_mode"
    assert result.status == HealthStatus.degraded
    assert "deterministic/audit intake floor" in result.reason
    assert result.details["enable_open_world_understanding"] is False


def test_open_world_live_mode_health_reports_live_bedrock_ready(monkeypatch):
    monkeypatch.setenv("ARCHWAY_ENABLE_OPEN_WORLD_UNDERSTANDING", "true")
    monkeypatch.setenv("ARCHWAY_AGENTIC_MODE", "live_demo")
    monkeypatch.setenv("ARCHWAY_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("ARCHWAY_BEDROCK_MODEL_ID", "us.amazon.nova-pro-v1:0")
    get_settings.cache_clear()

    result = HealthService()._open_world_live_mode_check()

    assert result.status == HealthStatus.ready
    assert "Live Bedrock open-world intake is enabled" in result.reason
    assert result.details["agentic_mode"] == "live_demo"


def _run(coro):
    import asyncio

    return asyncio.run(coro)
