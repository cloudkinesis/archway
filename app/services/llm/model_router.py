from __future__ import annotations

from pydantic import BaseModel

from app.core.config import get_settings
from app.services.llm.base import LLMMessage, LLMResult, LLMTask, LLMTaskType
from app.services.llm.bedrock_provider import BedrockProvider
from app.services.llm.ollama_provider import OllamaProvider


SONNET_TASKS = {
    LLMTaskType.discovery_planner,
    LLMTaskType.deep_use_case_understanding,
    LLMTaskType.synthesis_question_generation,
    LLMTaskType.metric_sanity_review,
    LLMTaskType.capability_review,
    LLMTaskType.pricing_filter_discovery,
    LLMTaskType.service_decision_reasoning,
    LLMTaskType.research_synthesis,
    LLMTaskType.deep_dossier_section_writing,
    LLMTaskType.architecture_critique,
    LLMTaskType.dossier_quality_review,
    LLMTaskType.executive_summary_writing,
    LLMTaskType.live_use_case_analyst,
    LLMTaskType.live_pricing_dimension,
    LLMTaskType.live_research_synthesis,
    LLMTaskType.live_architecture_candidate,
    LLMTaskType.live_diagram_planning,
    LLMTaskType.live_narrative_synthesis,
    LLMTaskType.live_reviewer_critique,
    LLMTaskType.open_world_understanding,
    LLMTaskType.llm_judge_review,
}


class ModelRouter:
    async def complete(
        self,
        task: LLMTask,
        messages: list[LLMMessage],
        response_schema: type[BaseModel] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_seconds: int | None = None,
    ) -> LLMResult:
        settings = get_settings()
        provider_name = settings.llm_provider.lower()
        if provider_name == "bedrock" and task.task_type in SONNET_TASKS:
            provider = BedrockProvider()
            return await provider.complete(task, messages, response_schema=response_schema, temperature=temperature if temperature is not None else settings.bedrock_temperature_default, max_tokens=max_tokens, timeout_seconds=timeout_seconds)
        if provider_name == "ollama":
            return await OllamaProvider().complete(task, messages, response_schema=response_schema, temperature=temperature if temperature is not None else 0.2, max_tokens=max_tokens, timeout_seconds=timeout_seconds)
        return LLMResult(provider="deterministic", model_id="none", text="", parsed=None, validated=False, warnings=["LLM provider is deterministic/not configured; premium task skipped."])
