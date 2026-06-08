from typing import Literal

from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import AuditLogger, hash_payload
from app.models.domain import HealthStatus, SessionPhase


class RateLimitPolicy(BaseModel):
    requests_per_minute: int = 30


class ToolRegistryEntry(BaseModel):
    id: str
    name: str
    category: Literal["aws_docs", "aws_pricing", "web_search", "aws_api", "security", "local"]
    enabled: bool
    required: bool
    read_only: bool
    write_capable: bool
    auth_required: bool
    health_status: HealthStatus
    rate_limit_policy: RateLimitPolicy | None = None
    allowed_phases: list[SessionPhase]
    degraded_reason: str | None = None


class ToolPolicyEngine:
    def __init__(self, entries: list[ToolRegistryEntry]):
        self.entries = {entry.id: entry for entry in entries}

    def assert_allowed(self, tool_id: str, phase: SessionPhase, payload: object, session_id: str | None = None) -> ToolRegistryEntry:
        entry = self.entries.get(tool_id)
        if entry is None:
            raise PermissionError(f"Tool {tool_id} is not registered.")
        if not entry.enabled:
            raise PermissionError(f"Tool {tool_id} is disabled.")
        if entry.write_capable:
            raise PermissionError(f"Write-capable tool {tool_id} is disabled in Archway V1.")
        if phase not in entry.allowed_phases:
            raise PermissionError(f"Tool {tool_id} is not allowed during {phase.value}.")
        AuditLogger(session_id).event(
            phase.value,
            "tool_policy_allowed",
            tool_name=entry.name,
            inputs_hash=hash_payload(payload),
            read_only=entry.read_only,
        )
        return entry


def build_tool_registry() -> list[ToolRegistryEntry]:
    settings = get_settings()
    return [
        ToolRegistryEntry(
            id="local_policy",
            name="Local AWS Architecture Policy Pack",
            category="local",
            enabled=True,
            required=True,
            read_only=True,
            write_capable=False,
            auth_required=False,
            health_status=HealthStatus.ready,
            allowed_phases=[SessionPhase.research, SessionPhase.architecture],
        ),
        ToolRegistryEntry(
            id="aws_docs_mcp",
            name="AWS Documentation MCP",
            category="aws_docs",
            enabled=settings.enable_aws_docs_mcp and bool(settings.aws_docs_mcp_url),
            required=False,
            read_only=True,
            write_capable=False,
            auth_required=True,
            health_status=HealthStatus.ready if settings.enable_aws_docs_mcp and settings.aws_docs_mcp_url else HealthStatus.degraded,
            degraded_reason=None if settings.enable_aws_docs_mcp and settings.aws_docs_mcp_url else "AWS documentation MCP is not configured; research will use local evidence only.",
            allowed_phases=[SessionPhase.research],
        ),
        ToolRegistryEntry(
            id="aws_pricing_mcp",
            name="AWS Pricing MCP (live Price List)",
            category="aws_pricing",
            enabled=settings.enable_aws_pricing_mcp and bool(settings.aws_pricing_mcp_url or settings.aws_pricing_mcp_command),
            required=False,
            read_only=True,
            write_capable=False,
            auth_required=True,
            health_status=HealthStatus.ready if settings.enable_aws_pricing_mcp and (settings.aws_pricing_mcp_url or settings.aws_pricing_mcp_command) else HealthStatus.degraded,
            degraded_reason=None if settings.enable_aws_pricing_mcp and (settings.aws_pricing_mcp_url or settings.aws_pricing_mcp_command) else "Dedicated AWS Pricing MCP is not configured; live Price List/SKU lookup is unavailable.",
            allowed_phases=[SessionPhase.research],
        ),
        ToolRegistryEntry(
            id="aws_pricing_reference_mcp",
            name="AWS Pricing reference MCP",
            category="aws_pricing",
            enabled=settings.enable_aws_pricing_reference_mcp and bool(settings.aws_pricing_reference_mcp_url),
            required=False,
            read_only=True,
            write_capable=False,
            auth_required=False,
            health_status=HealthStatus.ready if settings.enable_aws_pricing_reference_mcp and settings.aws_pricing_reference_mcp_url else HealthStatus.degraded,
            degraded_reason=None if settings.enable_aws_pricing_reference_mcp and settings.aws_pricing_reference_mcp_url else "AWS managed MCP pricing reference search is not configured; pricing evidence falls back to official web search when available.",
            allowed_phases=[SessionPhase.research],
        ),
        ToolRegistryEntry(
            id="web_search",
            name="Tavily Web Search",
            category="web_search",
            enabled=settings.enable_web_search and bool(settings.tavily_api_key),
            required=False,
            read_only=True,
            write_capable=False,
            auth_required=True,
            health_status=HealthStatus.ready if settings.enable_web_search and settings.tavily_api_key else HealthStatus.degraded,
            degraded_reason=None if settings.enable_web_search and settings.tavily_api_key else "Tavily web search is not configured; competitor scan is marked limited.",
            allowed_phases=[SessionPhase.research],
        ),
    ]
