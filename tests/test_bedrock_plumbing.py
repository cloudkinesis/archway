import asyncio

from app.core.config import get_settings
from app.models.domain import HealthStatus
from app.services.health import HealthService
from app.services.llm.base import LLMTask, LLMTaskType
from app.services.llm.bedrock_provider import _converse_messages, _model_id_for_task
from app.services.llm.model_router import ModelRouter
from app.services.understanding.deep_use_case_understanding import DeepUseCaseUnderstanding


def test_bedrock_health_is_explicitly_degraded_without_model(monkeypatch):
    monkeypatch.setenv("ARCHWAY_LLM_PROVIDER", "bedrock")
    monkeypatch.delenv("ARCHWAY_BEDROCK_MODEL_ID", raising=False)
    monkeypatch.delenv("ARCHWAY_BEDROCK_MAIN_MODEL_ID", raising=False)
    get_settings.cache_clear()

    result = asyncio.run(HealthService()._bedrock_sonnet_check())

    assert result.id == "bedrock_sonnet"
    assert result.status == HealthStatus.degraded
    assert result.details["configured"] is False


def test_bedrock_main_model_env_is_backward_compatible(monkeypatch):
    monkeypatch.setenv("ARCHWAY_BEDROCK_MODEL_ID", "legacy-main-model")
    monkeypatch.delenv("ARCHWAY_BEDROCK_MAIN_MODEL_ID", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.bedrock_model_id == "legacy-main-model"
    assert settings.bedrock_main_model_id == "legacy-main-model"


def test_bedrock_explicit_main_model_env_can_replace_legacy_model(monkeypatch):
    monkeypatch.delenv("ARCHWAY_BEDROCK_MODEL_ID", raising=False)
    monkeypatch.setenv("ARCHWAY_BEDROCK_MAIN_MODEL_ID", "explicit-main-model")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.bedrock_model_id == "explicit-main-model"
    assert settings.bedrock_main_model_id == "explicit-main-model"


def test_bedrock_judge_model_requires_explicit_enablement(monkeypatch):
    monkeypatch.setenv("ARCHWAY_BEDROCK_MAIN_MODEL_ID", "main-model")
    monkeypatch.setenv("ARCHWAY_BEDROCK_JUDGE_MODEL_ID", "judge-model")
    monkeypatch.setenv("ARCHWAY_ENABLE_LLM_JUDGE", "false")
    get_settings.cache_clear()

    settings = get_settings()

    assert _model_id_for_task(settings, LLMTask(task_type=LLMTaskType.llm_judge_review, model_role="judge")) == ""
    assert _model_id_for_task(settings, LLMTask(task_type=LLMTaskType.open_world_understanding)) == "main-model"


def test_bedrock_judge_model_routes_when_enabled(monkeypatch):
    monkeypatch.setenv("ARCHWAY_BEDROCK_MAIN_MODEL_ID", "main-model")
    monkeypatch.setenv("ARCHWAY_BEDROCK_JUDGE_MODEL_ID", "judge-model")
    monkeypatch.setenv("ARCHWAY_ENABLE_LLM_JUDGE", "true")
    get_settings.cache_clear()

    settings = get_settings()

    assert _model_id_for_task(settings, LLMTask(task_type=LLMTaskType.llm_judge_review, model_role="judge")) == "judge-model"
    assert _model_id_for_task(settings, LLMTask(task_type=LLMTaskType.open_world_understanding)) == "main-model"


def test_model_router_uses_deterministic_fallback_when_not_configured(monkeypatch):
    monkeypatch.setenv("ARCHWAY_LLM_PROVIDER", "deterministic")
    get_settings.cache_clear()

    result = asyncio.run(ModelRouter().complete(LLMTask(task_type=LLMTaskType.deep_use_case_understanding), []))

    assert result.provider == "deterministic"
    assert result.validated is False
    assert result.warnings


def test_deep_understanding_bedrock_prompt_requests_instance_not_schema():
    messages, _ = _converse_messages([], DeepUseCaseUnderstanding)

    instruction = messages[-1]["content"][0]["text"]

    assert "JSON object INSTANCE" in instruction
    assert "workload_families" in instruction
    assert '"$defs"' not in instruction
