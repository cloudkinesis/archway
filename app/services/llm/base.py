from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field


class LLMTaskType(str, Enum):
    session_title = "session_title"
    quick_extraction = "quick_extraction"
    discovery_planner = "discovery_planner"
    deep_use_case_understanding = "deep_use_case_understanding"
    synthesis_question_generation = "synthesis_question_generation"
    metric_sanity_review = "metric_sanity_review"
    capability_review = "capability_review"
    pricing_filter_discovery = "pricing_filter_discovery"
    service_decision_reasoning = "service_decision_reasoning"
    research_synthesis = "research_synthesis"
    deep_dossier_section_writing = "deep_dossier_section_writing"
    architecture_critique = "architecture_critique"
    dossier_quality_review = "dossier_quality_review"
    executive_summary_writing = "executive_summary_writing"
    live_use_case_analyst = "live_use_case_analyst"
    live_pricing_dimension = "live_pricing_dimension"
    live_research_synthesis = "live_research_synthesis"
    live_architecture_candidate = "live_architecture_candidate"
    live_diagram_planning = "live_diagram_planning"
    live_narrative_synthesis = "live_narrative_synthesis"
    live_reviewer_critique = "live_reviewer_critique"
    open_world_understanding = "open_world_understanding"
    llm_judge_review = "llm_judge_review"


class LLMTask(BaseModel):
    task_type: LLMTaskType
    session_id: str | None = None
    name: str | None = None
    model_role: Literal["main", "judge"] = "main"


class LLMMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMResult(BaseModel):
    provider: str
    model_id: str
    text: str
    parsed: Any = None
    validated: bool = False
    retry_count: int = 0
    duration_ms: int = 0
    token_usage: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    # True only for connectivity/transport failures (endpoint unreachable, connect/read
    # timeout). NEVER set for permanent client errors (ValidationException, AccessDenied,
    # Throttling) — those are real, non-transient failures that must not be masked as
    # "provider unavailable / retry when online".
    transport_error: bool = False


class StructuredLLMCallResult(BaseModel):
    task_type: LLMTaskType
    provider: str
    model_id: str
    schema_name: str
    validated: bool
    retry_count: int
    duration_ms: int
    token_usage: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


class LLMCallTelemetry(BaseModel):
    call_id: str = Field(default_factory=lambda: f"llm_{uuid4().hex[:12]}")
    session_id: str | None = None
    task_type: str
    provider: str
    model_id: str
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: str | None = None
    schema_validated: bool
    retry_count: int
    status: str
    schema_name: str | None = None
    prompt_hash: str | None = None
    warnings: list[str] = Field(default_factory=list)


class LLMProvider(Protocol):
    async def complete(
        self,
        task: LLMTask,
        messages: list[LLMMessage],
        response_schema: type[BaseModel] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        timeout_seconds: int | None = None,
    ) -> LLMResult:
        ...
