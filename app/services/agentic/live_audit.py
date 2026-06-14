from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.llm.base import LLMTaskType


LiveCallStatus = Literal[
    "accepted",
    "downgraded",
    "rejected",
    "skipped",
    "failed",
    "not_attempted",
    "setup_required",
]


class BudgetState(BaseModel):
    calls_used: int = 0
    max_calls: int = 0
    state: Literal["available", "budget_exhausted"] = "available"


class LiveCallAudit(BaseModel):
    provider: str
    model_id: str | None = None
    task_type: LLMTaskType
    lane: str
    session_id: str | None = None
    canonical_fact_snapshot_hash_used: str | None = None
    duration_ms: int | None = None
    token_usage: dict[str, Any] | None = None
    retry_count: int = 0
    validated: bool = False
    prompt_hash: str | None = None
    response_hash: str | None = None
    original_response_hash: str | None = None
    repaired_response_hash: str | None = None
    parse_error: str | None = None
    repair_attempted: bool = False
    repair_count: int = 0
    status: LiveCallStatus
    error_type: str | None = None
    error_message: str | None = None
    skip_reason: str | None = None
    budget_state: BudgetState = Field(default_factory=BudgetState)
    token_usage_unavailable: bool = False
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class LiveCallResult(BaseModel):
    audit: LiveCallAudit
    parsed: Any = None
    text: str = ""

    @property
    def ok(self) -> bool:
        return self.audit.status in {"accepted", "downgraded"} and self.parsed is not None


def is_real_bedrock_call(audit: LiveCallAudit) -> bool:
    return (
        audit.provider == "bedrock"
        and bool(audit.model_id)
        and bool(audit.prompt_hash)
        and bool(audit.response_hash)
        and audit.duration_ms is not None
        and bool(audit.status)
    )
