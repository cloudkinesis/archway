from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.models.domain import HealthStatus
from app.services.health import HealthService


class BuildStatusService:
    async def status(self) -> dict[str, Any]:
        settings = get_settings()
        health = await HealthService().check()
        checks = {item.id: item for item in health.checks}
        items = [
            _item("evidence_authority_modes", "Evidence authority modes", HealthStatus.ready, "AWS official, approved third-party, general web, and local-policy evidence boundaries are implemented."),
            _item("citation_gate", "Citation gate", HealthStatus.ready, "Fact and recommendation claims must cite evidence or remain explicit assumptions."),
            _item("price_list_parser", "AWS Price List parser", HealthStatus.ready, "SKU, term, dimension, tier range, unit, currency, and source-reference parsing is covered by tests."),
            _item("pricing_filter_mapper", "Pricing service mapper", HealthStatus.ready, "Common AWS service names map to Price List API service codes and region filters."),
            _item(
                "compiler_timeout_guard",
                "Compiler timeout guard",
                HealthStatus.ready,
                f"Existing D2 compiler calls are bounded at {settings.compiler_total_timeout_seconds:g}s with {settings.compiler_max_concurrent_jobs} concurrent compiler job(s).",
            ),
            _item("golden_regression_export", "Golden regression export", HealthStatus.ready, "Golden scenario matrix is available through the read-only regression export endpoint."),
            _from_health(checks.get("diagram_compiler"), "Existing D2 compiler", "Diagrams render through the configured Archway D2 compiler adapter."),
            _from_health(checks.get("tool_aws_docs_mcp"), "AWS Documentation MCP", "Official AWS documentation evidence route."),
            _from_health(checks.get("aws_price_list_bulk"), "AWS Price List Bulk API", "Official bulk offer index route for pricing evidence."),
            _from_health(checks.get("aws_price_list_query"), "AWS Price List Query API", "Live structured GetProducts route for SKU traceability evidence."),
            _from_health(checks.get("bedrock_sonnet"), "Bedrock semantic reviewer", "Optional premium semantic review route for understanding, pricing sanity, and critique."),
            _from_health(checks.get("tool_aws_pricing_reference_mcp"), "AWS Pricing reference MCP", "Managed AWS MCP route for pricing-page reference evidence only."),
            _from_health(checks.get("tool_aws_pricing_mcp"), "Dedicated AWS Pricing MCP policy", "Read-only policy gate for procurement-grade Pricing MCP route."),
            _from_health(checks.get("aws_labs_pricing_mcp"), "AWS Labs Pricing MCP", "Canonical AWS Labs stdio MCP route for live Price List queries."),
            _item(
                "live_pricing_mcp_configuration",
                "Live Pricing MCP configuration",
                HealthStatus.ready if settings.enable_aws_pricing_mcp and (settings.aws_pricing_mcp_url or settings.aws_pricing_mcp_command) else HealthStatus.degraded,
                "Optional. Configure ARCHWAY_AWS_PRICING_MCP_COMMAND for AWS Labs stdio or ARCHWAY_AWS_PRICING_MCP_URL for HTTP to query a dedicated live Price List MCP.",
                required=False,
            ),
        ]
        required_failed = any(item["required"] and item["status"] == HealthStatus.failed.value for item in items)
        degraded = any(item["status"] != HealthStatus.ready.value for item in items)
        return {
            "status": HealthStatus.failed.value if required_failed else HealthStatus.degraded.value if degraded else HealthStatus.ready.value,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "items": items,
        }


def _from_health(check, label: str, fallback_reason: str) -> dict[str, Any]:
    if not check:
        return _item(label.lower().replace(" ", "_"), label, HealthStatus.degraded, fallback_reason, required=False)
    return _item(check.id, label, check.status, check.reason or fallback_reason, required=check.required, details=check.details)


def _item(id: str, label: str, status: HealthStatus, reason: str, *, required: bool = True, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": id,
        "label": label,
        "status": status.value,
        "required": required,
        "reason": reason,
        "details": details or {},
    }
