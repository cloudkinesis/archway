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
    diagram_compiler_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv("ARCHWAY_DIAGRAM_COMPILER_PATH", "/Users/arnab/Documents/Archway Diagram Compiler/src")
        )
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
    max_request_bytes: int = 64_000

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
