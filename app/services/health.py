import sqlite3
import time

import httpx

from app.core.config import get_settings
from app.models.domain import HealthCheckResult, HealthStatus, HealthSummary
from app.services.diagram_compiler_adapter import DiagramCompilerAdapter
from app.services.tavily import TavilySearchClient
from app.services.aws_price_list import AWSPriceListBulkClient
from app.services.aws_price_list_query import AWSPriceListQueryClient
from app.services.llm.bedrock_provider import BedrockProvider
from app.services.mcp_stdio import MCPStdioClient
from app.tooling.registry import build_tool_registry


_REMOTE_CHECK_TTL_SECONDS = 60
_REMOTE_CHECK_CACHE: dict[str, tuple[float, HealthCheckResult]] = {}


class HealthService:
    async def check(self, force_remote: bool = False) -> HealthSummary:
        checks = [
            self._backend_check(),
            self._database_check(),
            self._artifact_dir_check(),
            self._log_dir_check(),
            await self._cached_remote_check("ollama", self._ollama_check, force_remote),
            self._mcp_registry_check(),
            self._safe_markdown_check(),
            self._security_policy_check(),
            await self._cached_remote_check("tavily", self._tavily_check, force_remote),
            await self._cached_remote_check("aws_price_list_bulk", self._aws_price_list_bulk_check, force_remote),
            await self._cached_remote_check("aws_price_list_query", self._aws_price_list_query_check, force_remote),
            await self._cached_remote_check("aws_labs_pricing_mcp", self._aws_labs_pricing_mcp_check, force_remote),
            await self._cached_remote_check("bedrock_sonnet", self._bedrock_sonnet_check, force_remote),
            self._open_world_live_mode_check(),
            DiagramCompilerAdapter().get_compiler_health(),
        ]
        checks.extend(self._tool_checks())
        required_failed = any(check.required and check.status == HealthStatus.failed for check in checks)
        required_degraded = any(check.required and check.status == HealthStatus.degraded for check in checks)
        status = HealthStatus.failed if required_failed else HealthStatus.degraded if required_degraded else HealthStatus.ready
        return HealthSummary(status=status, can_continue=not required_failed, limited_mode_available=not required_failed, checks=checks)

    def _backend_check(self) -> HealthCheckResult:
        return HealthCheckResult(id="backend", label="Backend API", status=HealthStatus.ready, required=True, reason="FastAPI application is responding.")

    def _database_check(self) -> HealthCheckResult:
        settings = get_settings()
        try:
            with sqlite3.connect(settings.database_path) as db:
                db.execute("SELECT 1")
            return HealthCheckResult(id="database", label="Local session database", status=HealthStatus.ready, required=True, reason="SQLite database is available.")
        except Exception as exc:
            return HealthCheckResult(id="database", label="Local session database", status=HealthStatus.failed, required=True, reason=str(exc))

    def _artifact_dir_check(self) -> HealthCheckResult:
        return self._writable_dir_check("artifact_dir", "Artifact directory", get_settings().sessions_dir, required=True)

    def _log_dir_check(self) -> HealthCheckResult:
        return self._writable_dir_check("log_dir", "Log directory", get_settings().logs_dir, required=True)

    async def _ollama_check(self) -> HealthCheckResult:
        settings = get_settings()
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                response = await client.get(f"{settings.ollama_url.rstrip('/')}/api/tags")
            if response.status_code != 200:
                raise RuntimeError(f"Ollama returned HTTP {response.status_code}")
            models = [item.get("name", "") for item in response.json().get("models", [])]
            available = any(settings.ollama_model in model for model in models)
            return HealthCheckResult(
                id="ollama",
                label="Local Ollama model",
                status=HealthStatus.ready if available else HealthStatus.degraded,
                required=False,
                reason="Configured model is available." if available else f"Ollama is reachable, but {settings.ollama_model} was not listed.",
                details={"model": settings.ollama_model},
            )
        except Exception as exc:
            return HealthCheckResult(id="ollama", label="Local Ollama", status=HealthStatus.degraded, required=False, reason=f"Ollama is unavailable: {exc}")

    async def _cached_remote_check(self, key: str, check, force: bool) -> HealthCheckResult:
        cached = _REMOTE_CHECK_CACHE.get(key)
        now = time.monotonic()
        if not force and cached and now - cached[0] < _REMOTE_CHECK_TTL_SECONDS:
            result = cached[1].model_copy(deep=True)
            result.details = {**result.details, "cached": True}
            return result
        result = await check()
        result.details = {**result.details, "cached": False}
        _REMOTE_CHECK_CACHE[key] = (now, result)
        return result

    def _mcp_registry_check(self) -> HealthCheckResult:
        entries = build_tool_registry()
        return HealthCheckResult(
            id="mcp_registry",
            label="MCP/tool registry configuration",
            status=HealthStatus.ready,
            required=True,
            reason="Tool registry loaded with read-only defaults.",
            details={"tools": [entry.model_dump(mode="json") for entry in entries]},
        )

    def _safe_markdown_check(self) -> HealthCheckResult:
        return HealthCheckResult(id="safe_markdown", label="Safe markdown renderer", status=HealthStatus.ready, required=True, reason="Frontend uses DOMPurify with markdown rendering.")

    def _security_policy_check(self) -> HealthCheckResult:
        return HealthCheckResult(id="security_policy", label="Security policy", status=HealthStatus.ready, required=True, reason="Security headers, request limits, CORS allowlist, and rate limiting are enabled.")

    async def _tavily_check(self) -> HealthCheckResult:
        settings = get_settings()
        if not settings.tavily_api_key:
            return HealthCheckResult(
                id="tavily",
                label="Tavily web search",
                status=HealthStatus.degraded,
                required=False,
                reason="Tavily API key is not configured.",
                details={"configured": False},
            )
        ok, reason = await TavilySearchClient().health_check()
        return HealthCheckResult(
            id="tavily",
            label="Tavily web search",
            status=HealthStatus.ready if ok else HealthStatus.degraded,
            required=False,
            reason=reason,
            details={"configured": True, "source": "mcp_url" if settings.tavily_mcp_url_configured else "api_key"},
        )

    async def _aws_price_list_bulk_check(self) -> HealthCheckResult:
        ok, reason, details = await AWSPriceListBulkClient().health_check()
        return HealthCheckResult(
            id="aws_price_list_bulk",
            label="AWS Price List Bulk API",
            status=HealthStatus.ready if ok else HealthStatus.degraded,
            required=False,
            reason=reason,
            details=details,
        )

    async def _aws_price_list_query_check(self) -> HealthCheckResult:
        ok, reason, details = await AWSPriceListQueryClient().health_check()
        return HealthCheckResult(
            id="aws_price_list_query",
            label="AWS Price List Query API",
            status=HealthStatus.ready if ok else HealthStatus.degraded,
            required=False,
            reason=reason,
            details=details,
        )

    async def _aws_labs_pricing_mcp_check(self) -> HealthCheckResult:
        settings = get_settings()
        if not settings.enable_aws_pricing_mcp or not settings.aws_pricing_mcp_command:
            return HealthCheckResult(
                id="aws_labs_pricing_mcp",
                label="AWS Labs Pricing MCP",
                status=HealthStatus.degraded,
                required=False,
                reason="AWS Labs Pricing MCP command is not configured.",
                details={"configured": False, "transport": "stdio"},
            )
        try:
            client = MCPStdioClient(
                command=settings.aws_pricing_mcp_command,
                args=settings.aws_pricing_mcp_args,
                env={
                    "FASTMCP_LOG_LEVEL": "ERROR",
                    "AWS_PROFILE": settings.aws_pricing_mcp_aws_profile,
                    "AWS_REGION": settings.aws_pricing_mcp_aws_region,
                },
                server_name="AWS Labs Pricing MCP",
                session_id=None,
                timeout_seconds=120,
            )
            tools = await client.list_tools()
            tool_names = [tool.get("name") for tool in tools if isinstance(tool.get("name"), str)]
            ready = "get_pricing" in tool_names
            return HealthCheckResult(
                id="aws_labs_pricing_mcp",
                label="AWS Labs Pricing MCP",
                status=HealthStatus.ready if ready else HealthStatus.degraded,
                required=False,
                reason="Canonical AWS Labs pricing MCP is reachable." if ready else "AWS Labs pricing MCP is reachable, but get_pricing was not listed.",
                details={
                    "configured": True,
                    "transport": "stdio",
                    "command": settings.aws_pricing_mcp_command,
                    "tool_count": len(tool_names),
                    "has_get_pricing": ready,
                },
            )
        except Exception as exc:
            return HealthCheckResult(
                id="aws_labs_pricing_mcp",
                label="AWS Labs Pricing MCP",
                status=HealthStatus.degraded,
                required=False,
                reason=f"AWS Labs Pricing MCP is unavailable: {exc}",
                details={"configured": True, "transport": "stdio"},
            )

    async def _bedrock_sonnet_check(self) -> HealthCheckResult:
        settings = get_settings()
        if not settings.bedrock_main_model_id:
            return HealthCheckResult(
                id="bedrock_sonnet",
                label="Bedrock semantic reviewer",
                status=HealthStatus.degraded,
                required=False,
                reason="ARCHWAY_BEDROCK_MAIN_MODEL_ID/ARCHWAY_BEDROCK_MODEL_ID is not configured. Deterministic semantic review remains active.",
                details={
                    "provider": settings.llm_provider,
                    "configured": False,
                    "region": settings.bedrock_region,
                    "main_model_id": None,
                    "judge_model_id": settings.bedrock_judge_model_id,
                    "judge_inference_profile_id": settings.bedrock_judge_inference_profile_id,
                    "judge_enabled": settings.enable_llm_judge,
                },
            )
        ok, reason, details = await BedrockProvider().health_check()
        return HealthCheckResult(
            id="bedrock_sonnet",
            label="Bedrock semantic reviewer",
            status=HealthStatus.ready if ok else HealthStatus.degraded,
            required=False,
            reason=reason,
            details={**details, "provider": settings.llm_provider, "configured": True},
        )

    def _open_world_live_mode_check(self) -> HealthCheckResult:
        settings = get_settings()
        ready = (
            settings.enable_open_world_understanding
            and settings.agentic_mode == "live_demo"
            and settings.llm_provider == "bedrock"
            and bool(settings.bedrock_main_model_id or settings.bedrock_model_id)
        )
        reason = (
            "Live Bedrock open-world intake is enabled for use-case classification."
            if ready
            else "Open-world LLM intake is not active; Archway will use the deterministic/audit intake floor."
        )
        return HealthCheckResult(
            id="open_world_live_mode",
            label="Open-world LLM intake",
            status=HealthStatus.ready if ready else HealthStatus.degraded,
            required=False,
            reason=reason,
            details={
                "enable_open_world_understanding": settings.enable_open_world_understanding,
                "agentic_mode": settings.agentic_mode,
                "llm_provider": settings.llm_provider,
                "bedrock_model_id": settings.bedrock_main_model_id or settings.bedrock_model_id,
                "bedrock_main_model_id": settings.bedrock_main_model_id,
                "bedrock_judge_model_id": settings.bedrock_judge_model_id,
                "bedrock_judge_inference_profile_id": settings.bedrock_judge_inference_profile_id,
                "llm_judge_enabled": settings.enable_llm_judge,
            },
        )

    def _tool_checks(self) -> list[HealthCheckResult]:
        results = []
        for entry in build_tool_registry():
            results.append(
                HealthCheckResult(
                    id=f"tool_{entry.id}",
                    label=entry.name,
                    status=entry.health_status,
                    required=entry.required,
                    reason=entry.degraded_reason or "Tool is enabled and policy controlled.",
                    details={"category": entry.category, "read_only": entry.read_only, "write_capable": entry.write_capable},
                )
            )
        return results

    def _writable_dir_check(self, check_id: str, label: str, path, required: bool) -> HealthCheckResult:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".archway-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return HealthCheckResult(id=check_id, label=label, status=HealthStatus.ready, required=required, reason=f"{label} is writable.")
        except Exception as exc:
            return HealthCheckResult(id=check_id, label=label, status=HealthStatus.failed, required=required, reason=str(exc))
