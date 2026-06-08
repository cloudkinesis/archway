import asyncio

from app.core.config import get_settings
from app.models.domain import HealthStatus
from app.services.health import HealthService
from app.services.llm.base import LLMTask, LLMTaskType
from app.services.llm.model_router import ModelRouter


def test_bedrock_health_is_explicitly_degraded_without_model(monkeypatch):
    monkeypatch.setenv("ARCHWAY_LLM_PROVIDER", "bedrock")
    monkeypatch.delenv("ARCHWAY_BEDROCK_MODEL_ID", raising=False)
    get_settings.cache_clear()

    result = asyncio.run(HealthService()._bedrock_sonnet_check())

    assert result.id == "bedrock_sonnet"
    assert result.status == HealthStatus.degraded
    assert result.details["configured"] is False


def test_model_router_uses_deterministic_fallback_when_not_configured(monkeypatch):
    monkeypatch.setenv("ARCHWAY_LLM_PROVIDER", "deterministic")
    get_settings.cache_clear()

    result = asyncio.run(ModelRouter().complete(LLMTask(task_type=LLMTaskType.deep_use_case_understanding), []))

    assert result.provider == "deterministic"
    assert result.validated is False
    assert result.warnings
