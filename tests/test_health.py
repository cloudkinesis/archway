from app.models.domain import HealthCheckResult, HealthStatus
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


def _run(coro):
    import asyncio

    return asyncio.run(coro)
