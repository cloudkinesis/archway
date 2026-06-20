from __future__ import annotations

import asyncio
import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.logging import hash_payload
from app.services.agentic.live_audit import BudgetState, LiveCallAudit, LiveCallResult
from app.services.llm.base import LLMMessage, LLMResult, LLMTask, LLMTaskType
from app.services.llm.model_router import ModelRouter


SETUP_REQUIRED_MESSAGE = (
    "Live agentic demo unavailable: ARCHWAY_BEDROCK_MAIN_MODEL_ID/ARCHWAY_BEDROCK_MODEL_ID is not configured "
    "(llm_provider must be 'bedrock'). Continuing in deterministic mode; a "
    "diagnostic package will still be generated."
)

_BUDGET_LOCK = threading.Lock()
_BUDGET_USED: dict[str, int] = defaultdict(int)

_LIVE_SENSITIVE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "ssn"),
    (re.compile(r"(?i)\bMRN[:#]?\s*\d+"), "medical_record_number"),
    (re.compile(r"(?i)\b(?:account|acct|routing|card)\s*(?:number|#)?\s*[:=]?\s*\d{6,}\b"), "account_number"),
    (re.compile(r"\bAKIA[0-9A-Z]{12,}\b"), "aws_access_key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private_key"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}"), "bearer_token"),
    (re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|client_secret|access[_-]?key|auth[_-]?token|session[_-]?token)\b\s*[:=]\s*\S"), "credential_assignment"),
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"), "iban"),
)


@dataclass
class LiveRunContext:
    session_id: str | None = None
    raw_use_case: str | None = None
    canonical_fact_snapshot_hash: str | None = None
    audits: list[LiveCallAudit] = field(default_factory=list)

    @property
    def budget_key(self) -> str:
        return self.session_id or "_"

    def add(self, audit: LiveCallAudit) -> None:
        self.audits.append(audit)


def reset_live_budget(session_id: str | None = None) -> None:
    with _BUDGET_LOCK:
        if session_id is None:
            _BUDGET_USED.clear()
        else:
            _BUDGET_USED.pop(session_id or "_", None)


def live_demo_setup_ready(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return settings.agentic_mode == "live_demo" and settings.llm_provider.lower() == "bedrock" and bool(settings.bedrock_main_model_id or settings.bedrock_model_id)


def live_demo_sensitivity_reason(text: str | None) -> str | None:
    if not text:
        return None
    for pattern, reason in _LIVE_SENSITIVE_PATTERNS:
        if pattern.search(text):
            return f"sensitive_value:{reason}"
    return None


def live_call(
    task_type: LLMTaskType,
    messages: list[LLMMessage],
    response_schema: type[BaseModel],
    *,
    session_id: str | None,
    lane: str,
    run_context: LiveRunContext | None = None,
    sensitivity_text: str | None = None,
) -> LiveCallResult:
    settings = get_settings()
    run_context = run_context or LiveRunContext(session_id=session_id, raw_use_case=sensitivity_text)
    prompt_hash = "sha256:" + hash_payload({"messages": [message.model_dump(mode="json") for message in messages]})

    if settings.agentic_mode != "live_demo":
        return _finish(run_context, LiveCallAudit(
            provider="disabled",
            task_type=task_type,
            lane=lane,
            session_id=session_id,
            canonical_fact_snapshot_hash_used=run_context.canonical_fact_snapshot_hash,
            prompt_hash=prompt_hash,
            status="not_attempted",
            skip_reason=f"agentic_mode:{settings.agentic_mode}",
            budget_state=_budget_state(settings, run_context),
        ))

    if settings.llm_provider.lower() != "bedrock" or not (settings.bedrock_main_model_id or settings.bedrock_model_id):
        return _finish(run_context, LiveCallAudit(
            provider="setup_required",
            task_type=task_type,
            lane=lane,
            session_id=session_id,
            canonical_fact_snapshot_hash_used=run_context.canonical_fact_snapshot_hash,
            prompt_hash=prompt_hash,
            status="setup_required",
            error_type="bedrock_not_configured",
            error_message=SETUP_REQUIRED_MESSAGE,
            budget_state=_budget_state(settings, run_context),
            warnings=[SETUP_REQUIRED_MESSAGE],
        ))

    sensitive = live_demo_sensitivity_reason(sensitivity_text)
    if sensitive:
        return _finish(run_context, LiveCallAudit(
            provider="skipped",
            task_type=task_type,
            lane=lane,
            session_id=session_id,
            canonical_fact_snapshot_hash_used=run_context.canonical_fact_snapshot_hash,
            prompt_hash=prompt_hash,
            status="skipped",
            skip_reason=sensitive,
            budget_state=_budget_state(settings, run_context),
        ))

    if not _reserve_budget(settings, run_context):
        return _finish(run_context, LiveCallAudit(
            provider="not_attempted",
            task_type=task_type,
            lane=lane,
            session_id=session_id,
            canonical_fact_snapshot_hash_used=run_context.canonical_fact_snapshot_hash,
            prompt_hash=prompt_hash,
            status="not_attempted",
            skip_reason="budget_exhausted",
            budget_state=_budget_state(settings, run_context, exhausted=True),
        ))

    try:
        result = _run_coro_blocking(lambda: ModelRouter().complete(
            LLMTask(task_type=task_type, session_id=session_id, name=lane),
            messages,
            response_schema=response_schema,
            temperature=0,
            max_tokens=settings.bedrock_max_tokens,
            timeout_seconds=settings.bedrock_timeout_seconds,
        ))
    except Exception as exc:  # noqa: BLE001 - live lanes must downgrade, not abort
        return _finish(run_context, LiveCallAudit(
            provider="bedrock",
            model_id=settings.bedrock_main_model_id or settings.bedrock_model_id,
            task_type=task_type,
            lane=lane,
            session_id=session_id,
            canonical_fact_snapshot_hash_used=run_context.canonical_fact_snapshot_hash,
            prompt_hash=prompt_hash,
            status="failed",
            error_type=type(exc).__name__,
            error_message=_safe_error(exc),
            budget_state=_budget_state(settings, run_context),
        ))

    return _result_from_llm(result, response_schema, prompt_hash, settings, run_context, task_type, lane, session_id)


def _result_from_llm(
    result: LLMResult,
    response_schema: type[BaseModel],
    prompt_hash: str,
    settings: Settings,
    run_context: LiveRunContext,
    task_type: LLMTaskType,
    lane: str,
    session_id: str | None,
) -> LiveCallResult:
    response_hash = "sha256:" + hash_payload(result.text or result.parsed or "")
    warnings = list(result.warnings)
    token_unavailable = result.token_usage is None
    if token_unavailable:
        warnings.append("token_usage_unavailable")
    provider = result.provider
    model_id = result.model_id or settings.bedrock_main_model_id or settings.bedrock_model_id
    parsed = result.parsed
    validated = bool(result.validated and isinstance(parsed, response_schema))
    original_response_hash = response_hash
    repaired_response_hash = None
    repair_attempted = False
    repair_count = 0
    parse_error = None if validated else _schema_error_message(result, response_schema)
    if provider == "bedrock" and not validated and settings.agentic_schema_repair_retries > 0:
        repair_attempted = True
        repair = _attempt_schema_repair(
            result,
            response_schema,
            settings,
            run_context,
            task_type,
            lane,
            session_id,
            parse_error=parse_error,
        )
        if repair is not None:
            repair_count = 1
            warnings.append(f"schema_repair_attempted:{parse_error or 'structured_output_invalid'}")
            warnings.extend(repair.warnings)
            repaired_response_hash = "sha256:" + hash_payload(repair.text or repair.parsed or "")
            response_hash = repaired_response_hash
            result = repair
            parsed = repair.parsed
            validated = bool(repair.validated and isinstance(parsed, response_schema))
            token_unavailable = repair.token_usage is None
            provider = repair.provider
            model_id = repair.model_id or settings.bedrock_main_model_id or settings.bedrock_model_id
    status = "accepted" if provider == "bedrock" and validated else "rejected"
    # Distinguish a transport/connectivity failure (provider unreachable) from a genuine
    # schema-invalid response. Both arrive here as not-validated, but conflating them
    # mislabels a network outage as "the model returned bad JSON" and hides config errors
    # (e.g. a wrong model id, which raises a permanent ClientError, NOT a transport error).
    if status == "accepted":
        error_type = None
        error_message = None
    elif getattr(result, "transport_error", False):
        error_type = "provider_unavailable"
        error_message = f"Live Bedrock provider is unavailable: {warnings[-1] if warnings else 'transport failure'}"
    else:
        error_type = "structured_output_invalid"
        error_message = "Live Bedrock response did not validate against the lane schema."
    audit = LiveCallAudit(
        provider=provider,
        model_id=model_id,
        task_type=task_type,
        lane=lane,
        session_id=session_id,
        canonical_fact_snapshot_hash_used=run_context.canonical_fact_snapshot_hash,
        duration_ms=result.duration_ms,
        token_usage=result.token_usage,
        retry_count=result.retry_count,
        validated=validated,
        prompt_hash=prompt_hash,
        response_hash=response_hash,
        original_response_hash=original_response_hash if repair_attempted else None,
        repaired_response_hash=repaired_response_hash,
        parse_error=parse_error,
        repair_attempted=repair_attempted,
        repair_count=repair_count,
        status=status,
        error_type=error_type,
        error_message=error_message,
        budget_state=_budget_state(settings, run_context),
        token_usage_unavailable=token_unavailable,
        warnings=warnings,
    )
    return _finish(run_context, audit, parsed=parsed if status == "accepted" else None, text=result.text)


def _schema_error_message(result: LLMResult, response_schema: type[BaseModel]) -> str:
    schema_name = getattr(response_schema, "__name__", "response_schema")
    if result.parsed is None:
        return f"{schema_name}: response was not parsed or did not match structured output."
    return f"{schema_name}: parsed object type {type(result.parsed).__name__} did not validate."


def _attempt_schema_repair(
    result: LLMResult,
    response_schema: type[BaseModel],
    settings: Settings,
    run_context: LiveRunContext,
    task_type: LLMTaskType,
    lane: str,
    session_id: str | None,
    *,
    parse_error: str | None,
) -> LLMResult | None:
    if not _reserve_budget(settings, run_context):
        return None
    schema = response_schema.model_json_schema()
    messages = [
        LLMMessage(
            role="system",
            content=(
                "Repair the previous response into valid JSON for the requested schema. "
                "Return JSON only. Do not include markdown, commentary, or fields outside the schema."
            ),
        ),
        LLMMessage(
            role="user",
            content=(
                f"Schema name: {getattr(response_schema, '__name__', 'response_schema')}\n"
                f"Schema JSON: {schema}\n"
                f"Validation error: {parse_error or 'structured_output_invalid'}\n"
                f"Original response:\n{(result.text or '')[:18000]}"
            ),
        ),
    ]
    try:
        return _run_coro_blocking(lambda: ModelRouter().complete(
            LLMTask(task_type=task_type, session_id=session_id, name=f"{lane}_schema_repair"),
            messages,
            response_schema=response_schema,
            temperature=0,
            max_tokens=settings.bedrock_max_tokens,
            timeout_seconds=settings.bedrock_timeout_seconds,
        ))
    except Exception:
        return None


def _reserve_budget(settings: Settings, run_context: LiveRunContext) -> bool:
    with _BUDGET_LOCK:
        used = _BUDGET_USED[run_context.budget_key]
        if used >= settings.agentic_max_bedrock_calls:
            return False
        _BUDGET_USED[run_context.budget_key] = used + 1
        return True


def _budget_state(settings: Settings, run_context: LiveRunContext, *, exhausted: bool = False) -> BudgetState:
    with _BUDGET_LOCK:
        used = _BUDGET_USED.get(run_context.budget_key, 0)
    state = "budget_exhausted" if exhausted or used >= settings.agentic_max_bedrock_calls else "available"
    return BudgetState(calls_used=used, max_calls=settings.agentic_max_bedrock_calls, state=state)


def _finish(run_context: LiveRunContext, audit: LiveCallAudit, *, parsed: Any = None, text: str = "") -> LiveCallResult:
    run_context.add(audit)
    return LiveCallResult(audit=audit, parsed=parsed, text=text)


def _safe_error(exc: Exception) -> str:
    return str(exc).splitlines()[0][:220]


def _run_coro_blocking(factory):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(factory())
        except BaseException as exc:  # noqa: BLE001 - re-raised on calling thread
            error["error"] = exc

    thread = threading.Thread(target=_runner, name="archway-live-agent", daemon=True)
    thread.start()
    thread.join()
    if "error" in error:
        raise error["error"]
    return result.get("value")
