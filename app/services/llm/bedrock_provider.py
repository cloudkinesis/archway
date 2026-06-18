from __future__ import annotations

from datetime import datetime, timezone
import json
import time
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.config import get_settings
from app.core.logging import hash_payload
from app.services.llm.base import LLMCallTelemetry, LLMMessage, LLMResult, LLMTask, LLMTaskType
from app.services.llm.telemetry import llm_telemetry_store


class BedrockProvider:
    provider_name = "bedrock"

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
        warnings: list[str] = []
        status = "succeeded"
        parsed = None
        text = ""
        validated = False
        retry_count = 0
        token_usage = None
        model_id = settings.bedrock_model_id or ""
        try:
            if not model_id:
                raise RuntimeError("ARCHWAY_BEDROCK_MODEL_ID is not configured.")
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "bedrock-runtime",
                region_name=settings.bedrock_region,
                config=Config(read_timeout=timeout_seconds or settings.bedrock_timeout_seconds, retries={"max_attempts": settings.bedrock_retry_count}),
            )
            bedrock_messages, system_messages = _converse_messages(messages, response_schema)
            for attempt in range(settings.bedrock_retry_count + 1):
                retry_count = attempt
                response = client.converse(
                    modelId=model_id,
                    messages=bedrock_messages,
                    system=system_messages,
                    inferenceConfig={
                        "maxTokens": max_tokens or settings.bedrock_max_tokens,
                        "temperature": temperature,
                    },
                )
                usage = response.get("usage") or {}
                token_usage = {"input_tokens": usage.get("inputTokens"), "output_tokens": usage.get("outputTokens")}
                output_message = ((response.get("output") or {}).get("message") or {})
                text = "".join(block.get("text", "") for block in output_message.get("content", []) if block.get("text"))
                if not response_schema:
                    break
                try:
                    parsed = response_schema.model_validate_json(_extract_json(text))
                    validated = True
                    break
                except ValidationError as exc:
                    warnings.append(f"Structured output validation failed on attempt {attempt + 1}: {exc.errors()[:3]}")
                    if attempt >= settings.bedrock_retry_count:
                        raise
                    bedrock_messages.append({"role": "assistant", "content": [{"text": text}]})
                    bedrock_messages.append({"role": "user", "content": [{"text": "The JSON failed schema validation. Return corrected JSON only."}]})
        except Exception as exc:
            status = "failed"
            warnings.append(f"Bedrock call failed: {type(exc).__name__}: {exc}")
        completed = datetime.now(timezone.utc)
        duration_ms = int((time.monotonic() - t0) * 1000)
        llm_telemetry_store.add(LLMCallTelemetry(
            session_id=task.session_id,
            task_type=task.task_type.value,
            provider=self.provider_name,
            model_id=model_id or "not_configured",
            started_at=started,
            completed_at=completed,
            duration_ms=duration_ms,
            input_tokens=(token_usage or {}).get("input_tokens"),
            output_tokens=(token_usage or {}).get("output_tokens"),
            schema_validated=validated,
            retry_count=retry_count,
            status=status,
            schema_name=response_schema.__name__ if response_schema else None,
            prompt_hash=hash_payload({"messages": [message.model_dump() for message in messages]}),
            warnings=warnings,
        ))
        return LLMResult(provider=self.provider_name, model_id=model_id or "not_configured", text=text, parsed=parsed, validated=validated, retry_count=retry_count, duration_ms=duration_ms, token_usage=token_usage, warnings=warnings)

    async def health_check(self) -> tuple[bool, str, dict[str, Any]]:
        settings = get_settings()
        if not settings.bedrock_model_id:
            return False, "Bedrock model/inference profile is not configured.", {"configured": False}
        result = await self.complete(
            LLMTask(task_type=LLMTaskType.metric_sanity_review, session_id="health_probe", name="bedrock_structured_health"),
            [
                LLMMessage(role="system", content="You are Archway's Bedrock structured-output health probe. Return JSON only."),
                LLMMessage(role="user", content="Confirm that structured semantic review is available for AWS architecture analysis."),
            ],
            response_schema=BedrockHealthProbe,
            temperature=0,
            max_tokens=256,
            timeout_seconds=20,
        )
        details = {
            "configured": True,
            "region": settings.bedrock_region,
            "model_id": settings.bedrock_model_id,
            "structured_output": settings.bedrock_enable_structured_output,
            "usage": result.token_usage,
            "warnings": result.warnings,
        }
        if result.validated:
            return True, "Bedrock structured invocation passed.", details
        lowered = " ".join(result.warnings).lower()
        if "invalid_payment_instrument" in lowered or "payment instrument" in lowered:
            status = "invalid_payment_instrument"
        elif "use case details" in lowered:
            status = "model_use_case_details_required"
        elif "accessdenied" in lowered or "not authorized" in lowered:
            status = "permission_denied"
        elif "timeout" in lowered:
            status = "timeout"
        else:
            status = "failed"
        return False, f"Bedrock structured health check {status}.", {**details, "status": status}


def _converse_messages(messages: list[LLMMessage], response_schema: type[BaseModel] | None) -> tuple[list[dict], list[dict]]:
    system = "\n\n".join(message.content for message in messages if message.role == "system")
    bedrock_messages = [{"role": message.role, "content": [{"text": message.content}]} for message in messages if message.role != "system"]
    if response_schema:
        bedrock_messages.append({"role": "user", "content": [{"text": _schema_instruction(response_schema)}]})
    if not bedrock_messages:
        bedrock_messages.append({"role": "user", "content": [{"text": "Return a concise response."}]})
    system_messages = [{"text": system}] if system else []
    return bedrock_messages, system_messages


def _schema_instruction(response_schema: type[BaseModel]) -> str:
    if response_schema.__name__ == "DeepUseCaseUnderstanding":
        return (
            "Return a JSON object INSTANCE only, not a JSON Schema and not markdown. "
            "Do not include '$defs', 'properties', 'title', or 'type' keys unless they are part of the use case text. "
            "Use this exact top-level shape and fill it from the use case:\n"
            "{\n"
            '  "industry": "string",\n'
            '  "domain": "string",\n'
            '  "workload_families": ["string"],\n'
            '  "excluded_patterns": ["string"],\n'
            '  "capabilities": ["string"],\n'
            '  "extracted_metrics": [{"name":"string","value":"string-or-number","unit":"string-or-null","source_text":"string","confidence":"low|medium|high","derived":false,"derivation":null,"pricing_relevance":"none|low|medium|high"}],\n'
            '  "latency_constraints": [{"name":"string","target":"string","latency_class":"string","source_text":"string","architecture_impact":"string","confidence":"low|medium|high"}],\n'
            '  "compliance_constraints": [{"name":"string","source_text":"string","jurisdiction":null,"requires_validation":true,"architecture_impact":"string"}],\n'
            '  "action_flows": [{"action_name":"string","action_type":"string","source_text":"string","impact_level":"low|medium|high|critical","required_controls":["string"],"recommended_failure_behavior":"block|queue_for_review|allow_with_audit|rollback|recommendation_only"}],\n'
            '  "deployment_posture": "public_cloud|hybrid|edge|unknown",\n'
            '  "architecture_implications": ["string"],\n'
            '  "pricing_implications": ["string"],\n'
            '  "dossier_research_questions": ["string"],\n'
            '  "critical_unknowns": ["string"],\n'
            '  "confidence": "low|medium|high",\n'
            '  "concerns": ["string"]\n'
            "}"
        )
    schema = response_schema.model_json_schema()
    required = ", ".join(schema.get("required") or [])
    properties = ", ".join((schema.get("properties") or {}).keys())
    return (
        "Return JSON only: a data object instance matching the requested schema, not the schema definition. "
        "Do not include '$defs', 'properties', 'title', or 'type' keys unless the output model explicitly requires them. "
        f"Required top-level fields: {required or 'none'}. Top-level fields: {properties}. "
        f"Schema reference: {json.dumps(schema)}"
    )


def _extract_json(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end >= start:
        return cleaned[start:end + 1]
    return cleaned


class BedrockHealthProbe(BaseModel):
    ok: bool
    status: str = "ready"
    notes: list[str] = Field(default_factory=list)
