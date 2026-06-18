from functools import lru_cache
from pathlib import Path
import os
import shlex
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


def _tavily_key_from_env() -> str | None:
    direct = os.getenv("ARCHWAY_TAVILY_API_KEY")
    if direct:
        return direct
    mcp_url = os.getenv("ARCHWAY_TAVILY_MCP_URL")
    if not mcp_url:
        return None
    parsed = urlparse(mcp_url)
    values = parse_qs(parsed.query).get("tavilyApiKey") or parse_qs(parsed.query).get("apiKey")
    return values[0] if values else None


def _tavily_budget_default() -> int:
    if os.getenv("ARCHWAY_TAVILY_MAX_CALLS_PER_SESSION"):
        return max(0, int(os.getenv("ARCHWAY_TAVILY_MAX_CALLS_PER_SESSION", "0")))
    if os.getenv("ARCHWAY_ENABLE_COMPETITOR_WEB_SEARCH", "false") == "true":
        return 1
    return 0


class Settings(BaseModel):
    env: str = Field(default_factory=lambda: os.getenv("ARCHWAY_ENV", "development"))
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            item.strip()
            for item in os.getenv(
                "ARCHWAY_CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            ).split(",")
            if item.strip()
        ]
    )
    data_dir: Path = Field(default_factory=lambda: Path(os.getenv("ARCHWAY_DATA_DIR", ".archway")))
    ollama_url: str = Field(default_factory=lambda: os.getenv("ARCHWAY_OLLAMA_URL", "http://localhost:11434"))
    ollama_model: str = Field(default_factory=lambda: os.getenv("ARCHWAY_OLLAMA_MODEL", "llama3.1"))
    # Explicit external compiler override only (debug/fallback). The default
    # runtime imports the vendored package from packages/archway_diagram_compiler/src;
    # see app/services/diagram_compiler_adapter.py.
    diagram_compiler_path: Path | None = Field(
        default_factory=lambda: Path(os.getenv("ARCHWAY_DIAGRAM_COMPILER_PATH")) if os.getenv("ARCHWAY_DIAGRAM_COMPILER_PATH") else None
    )
    compiler_total_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("ARCHWAY_COMPILER_TOTAL_TIMEOUT_SECONDS", "120"))
    )
    compiler_max_concurrent_jobs: int = Field(
        default_factory=lambda: max(1, int(os.getenv("ARCHWAY_COMPILER_MAX_CONCURRENT_JOBS", "1")))
    )
    tavily_api_key: str | None = Field(default_factory=_tavily_key_from_env)
    tavily_api_url: str = Field(default_factory=lambda: os.getenv("ARCHWAY_TAVILY_API_URL", "https://api.tavily.com/search"))
    tavily_mcp_url_configured: bool = Field(default_factory=lambda: bool(os.getenv("ARCHWAY_TAVILY_MCP_URL")))
    enable_web_search: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_ENABLE_WEB_SEARCH", "false") == "true"
    )
    enable_competitor_web_search: bool = Field(default_factory=lambda: os.getenv("ARCHWAY_ENABLE_COMPETITOR_WEB_SEARCH", "false") == "true")
    tavily_max_calls_per_session: int = Field(default_factory=_tavily_budget_default)
    aws_docs_mcp_url: str | None = Field(default_factory=lambda: os.getenv("ARCHWAY_AWS_DOCS_MCP_URL") or None)
    aws_docs_mcp_auth_token: str | None = Field(default_factory=lambda: os.getenv("ARCHWAY_AWS_DOCS_MCP_AUTH_TOKEN") or None)
    aws_pricing_mcp_url: str | None = Field(default_factory=lambda: os.getenv("ARCHWAY_AWS_PRICING_MCP_URL") or None)
    aws_pricing_mcp_auth_token: str | None = Field(default_factory=lambda: os.getenv("ARCHWAY_AWS_PRICING_MCP_AUTH_TOKEN") or None)
    aws_pricing_mcp_command: str | None = Field(default_factory=lambda: os.getenv("ARCHWAY_AWS_PRICING_MCP_COMMAND") or None)
    aws_pricing_mcp_args: list[str] = Field(default_factory=lambda: shlex.split(os.getenv("ARCHWAY_AWS_PRICING_MCP_ARGS", "")))
    aws_pricing_mcp_aws_profile: str = Field(default_factory=lambda: os.getenv("ARCHWAY_AWS_PRICING_MCP_AWS_PROFILE", os.getenv("AWS_PROFILE", "default")))
    aws_pricing_mcp_aws_region: str = Field(default_factory=lambda: os.getenv("ARCHWAY_AWS_PRICING_MCP_AWS_REGION", os.getenv("AWS_REGION", "us-east-1")))
    pricing_authority_timeout_seconds: int = Field(default_factory=lambda: int(os.getenv("ARCHWAY_PRICING_AUTHORITY_TIMEOUT_SECONDS", "120")))
    aws_pricing_reference_mcp_url: str | None = Field(
        default_factory=lambda: os.getenv("ARCHWAY_AWS_PRICING_REFERENCE_MCP_URL") or os.getenv("ARCHWAY_AWS_DOCS_MCP_URL") or None
    )
    aws_pricing_reference_mcp_auth_token: str | None = Field(default_factory=lambda: os.getenv("ARCHWAY_AWS_PRICING_REFERENCE_MCP_AUTH_TOKEN") or None)
    enable_aws_docs_mcp: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_ENABLE_AWS_DOCS_MCP", "false") == "true"
        or bool(os.getenv("ARCHWAY_AWS_DOCS_MCP_URL"))
    )
    enable_aws_pricing_mcp: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_ENABLE_AWS_PRICING_MCP", "false") == "true"
        or bool(os.getenv("ARCHWAY_AWS_PRICING_MCP_URL"))
        or bool(os.getenv("ARCHWAY_AWS_PRICING_MCP_COMMAND"))
    )
    enable_aws_pricing_reference_mcp: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_ENABLE_AWS_PRICING_REFERENCE_MCP", "true") == "true"
        and bool(os.getenv("ARCHWAY_AWS_PRICING_REFERENCE_MCP_URL") or os.getenv("ARCHWAY_AWS_DOCS_MCP_URL"))
    )
    enable_aws_official_web_fallback: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_ENABLE_AWS_OFFICIAL_WEB_FALLBACK", "false") == "true"
    )
    # MCP endpoint trust controls. Tokens are only ever attached to trusted endpoints:
    # localhost + private network by default; external hosts must be explicitly
    # allowlisted (or globally opted-in). Arbitrary external hosts are fail-closed.
    mcp_allow_localhost: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_MCP_ALLOW_LOCALHOST", "true") == "true"
    )
    mcp_allow_private_network: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_MCP_ALLOW_PRIVATE_NETWORK", "true") == "true"
    )
    mcp_allow_external: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_MCP_ALLOW_EXTERNAL", "false") == "true"
    )
    mcp_allowed_hosts: list[str] = Field(
        default_factory=lambda: [
            item.strip().lower()
            for item in os.getenv("ARCHWAY_MCP_ALLOWED_HOSTS", "").split(",")
            if item.strip()
        ]
    )
    aws_price_list_bulk_index_url: str = Field(
        default_factory=lambda: os.getenv(
            "ARCHWAY_AWS_PRICE_LIST_BULK_INDEX_URL",
            "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/index.json",
        )
    )
    llm_provider: str = Field(default_factory=lambda: os.getenv("ARCHWAY_LLM_PROVIDER", "deterministic"))
    bedrock_region: str = Field(default_factory=lambda: os.getenv("ARCHWAY_BEDROCK_REGION", "us-east-1"))
    bedrock_model_id: str | None = Field(default_factory=lambda: os.getenv("ARCHWAY_BEDROCK_MODEL_ID") or None)
    bedrock_use_inference_profile: bool = Field(default_factory=lambda: os.getenv("ARCHWAY_BEDROCK_USE_INFERENCE_PROFILE", "false") == "true")
    bedrock_max_tokens: int = Field(default_factory=lambda: int(os.getenv("ARCHWAY_BEDROCK_MAX_TOKENS", "8192")))
    bedrock_timeout_seconds: int = Field(default_factory=lambda: int(os.getenv("ARCHWAY_BEDROCK_TIMEOUT_SECONDS", "120")))
    bedrock_retry_count: int = Field(default_factory=lambda: int(os.getenv("ARCHWAY_BEDROCK_RETRY_COUNT", "2")))
    bedrock_temperature_default: float = Field(default_factory=lambda: float(os.getenv("ARCHWAY_BEDROCK_TEMPERATURE_DEFAULT", "0.2")))
    bedrock_enable_structured_output: bool = Field(default_factory=lambda: os.getenv("ARCHWAY_BEDROCK_ENABLE_STRUCTURED_OUTPUT", "true") == "true")
    agentic_mode: str = Field(default_factory=lambda: os.getenv("ARCHWAY_AGENTIC_MODE", "audit"))
    agentic_max_bedrock_calls: int = Field(default_factory=lambda: max(0, int(os.getenv("ARCHWAY_AGENTIC_MAX_BEDROCK_CALLS", "12"))))
    agentic_schema_repair_retries: int = Field(
        default_factory=lambda: max(0, int(os.getenv("ARCHWAY_AGENTIC_SCHEMA_REPAIR_RETRIES", "1")))
    )
    max_request_bytes: int = 64_000
    # In-memory job lifecycle TTL/eviction (best-effort cleanup of terminal jobs).
    job_completed_ttl_seconds: int = Field(default_factory=lambda: int(os.getenv("ARCHWAY_JOB_COMPLETED_TTL_SECONDS", "3600")))
    job_failed_ttl_seconds: int = Field(default_factory=lambda: int(os.getenv("ARCHWAY_JOB_FAILED_TTL_SECONDS", "21600")))
    job_max_retained: int = Field(default_factory=lambda: int(os.getenv("ARCHWAY_JOB_MAX_RETAINED", "500")))
    # Frontier-model domain prior (advisory only). Default OFF -> deterministic
    # Discovery Planner is the default; the model prior is an explicit opt-in and is
    # quarantined to interview questions + a generic fallback-family candidate only.
    enable_frontier_domain_prior: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_ENABLE_FRONTIER_DOMAIN_PRIOR", "false") == "true"
    )
    frontier_domain_prior_max_calls_per_session: int = Field(
        default_factory=lambda: max(0, int(os.getenv("ARCHWAY_FRONTIER_DOMAIN_PRIOR_MAX_CALLS_PER_SESSION", "1")))
    )
    # Pilot: attach a supplemental SKU-backed pricing trace (legal/document RAG only).
    # Default OFF. When off, pricing behavior is byte/behavior equivalent to baseline.
    # Does NOT reuse the domain-pack registry flag.
    enable_sku_pricing_pilot: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_ENABLE_SKU_PRICING_PILOT", "false") == "true"
    )
    sku_pricing_snapshot_path: str | None = Field(
        default_factory=lambda: os.getenv("ARCHWAY_SKU_PRICING_SNAPSHOT_PATH") or None
    )
    # Capability accelerator packs (advisory intake/question hints only). Default OFF;
    # with the flag off, CapabilityRouter behavior is byte/behavior equivalent.
    enable_capability_accelerator_packs: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_ENABLE_CAPABILITY_ACCELERATOR_PACKS", "false") == "true"
    )
    # Default scenario simulations at export time (deterministic what-ifs). Default OFF;
    # scenario artifacts appear only when explicit overrides are passed or this is on.
    enable_default_scenario_simulations: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_ENABLE_DEFAULT_SCENARIO_SIMULATIONS", "false") == "true"
    )
    # D21 agentic proposal lanes. Default OFF. Phase 0 may emit deterministic
    # raw/audit traces; live model lanes require later evaluation gates.
    enable_agentic_repair_planner: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_ENABLE_AGENTIC_REPAIR_PLANNER", "false") == "true"
    )
    enable_agentic_research: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_ENABLE_AGENTIC_RESEARCH", "false") == "true"
    )
    enable_agentic_use_case_analyst: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_ENABLE_AGENTIC_USE_CASE_ANALYST", "false") == "true"
    )
    enable_agentic_pricing: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_ENABLE_AGENTIC_PRICING", "false") == "true"
    )
    enable_agentic_narrative: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_ENABLE_AGENTIC_NARRATIVE", "false") == "true"
    )
    enable_agentic_reviewer: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_ENABLE_AGENTIC_REVIEWER", "false") == "true"
    )
    enable_agentic_diagram_planner: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_ENABLE_AGENTIC_DIAGRAM_PLANNER", "false") == "true"
    )
    enable_agentic_architecture: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_ENABLE_AGENTIC_ARCHITECTURE", "false") == "true"
    )
    # D23 open-world understanding. Default OFF: deterministic synthesis/profile
    # behavior remains the offline floor. When enabled in live_demo mode, Bedrock
    # proposes canonical use-case understanding before deterministic validation.
    enable_open_world_understanding: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_ENABLE_OPEN_WORLD_UNDERSTANDING", "false") == "true"
    )
    disable_domain_refiners: bool = Field(
        default_factory=lambda: os.getenv("ARCHWAY_DISABLE_DOMAIN_REFINERS", "false") == "true"
    )

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "archway.sqlite3"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.sessions_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    return settings
