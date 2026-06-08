from __future__ import annotations

from datetime import datetime, timezone
import json
import time

import httpx
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import hash_payload
from app.services.llm.base import LLMCallTelemetry, LLMMessage, LLMResult, LLMTask
from app.services.llm.telemetry import llm_telemetry_store


class OllamaProvider:
    provider_name = "ollama"

    async def complete(
        self,
        task: LLMTask,
        messages: list[LLMMessage],
        response_schema: type[BaseModel] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        timeout_seconds: int | None = None,
    ) -> LLMResult:
        settings = get_settings()
        started = datetime.now(timezone.utc)
        t0 = time.monotonic()
        prompt = "\n\n".join(f"{message.role}: {message.content}" for message in messages)
        payload = {
            "model": settings.ollama_model,
            "prompt": prompt,
            "stream": False,
            "format": "json" if response_schema else None,
            "options": {"temperature": temperature, **({"num_predict": max_tokens} if max_tokens else {})},
        }
        warnings: list[str] = []
        status = "succeeded"
        text = ""
        parsed = None
        validated = False
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds or 30) as client:
                response = await client.post(f"{settings.ollama_url.rstrip('/')}/api/generate", json=payload)
            response.raise_for_status()
            text = response.json().get("response", "")
            if response_schema:
                parsed = response_schema.model_validate_json(text)
                validated = True
        except Exception as exc:
            status = "failed"
            warnings.append(f"Ollama call failed: {type(exc).__name__}")
        completed = datetime.now(timezone.utc)
        duration_ms = int((time.monotonic() - t0) * 1000)
        llm_telemetry_store.add(LLMCallTelemetry(
            session_id=task.session_id,
            task_type=task.task_type.value,
            provider=self.provider_name,
            model_id=settings.ollama_model,
            started_at=started,
            completed_at=completed,
            duration_ms=duration_ms,
            schema_validated=validated,
            retry_count=0,
            status=status,
            schema_name=response_schema.__name__ if response_schema else None,
            prompt_hash=hash_payload({"messages": [message.model_dump() for message in messages]}),
            warnings=warnings,
        ))
        return LLMResult(provider=self.provider_name, model_id=settings.ollama_model, text=text, parsed=parsed, validated=validated, duration_ms=duration_ms, warnings=warnings)
