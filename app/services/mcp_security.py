"""Centralized MCP endpoint URL trust validation.

Archway treats MCP endpoints as privileged integration points: bearer/API tokens
must NEVER be sent to arbitrary or untrusted external URLs. This module classifies an
MCP URL (local / private / allowlisted-external / untrusted-external / invalid /
unsupported-scheme) and decides whether credentials may be attached — fail closed for
anything not explicitly trusted.

Pure/offline: parses and classifies URLs only. No network calls.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from ipaddress import ip_address
from typing import Iterable, Literal
from urllib.parse import urlparse

ALLOWED_SCHEMES = ("http", "https")
# AWS-managed MCP endpoints (e.g. *.api.aws/mcp) are an intentional built-in trusted
# suffix — this preserves existing AWS Docs/Pricing MCP behavior. It is the only
# suffix allowlist in this branch; everything else external must be explicit.
TRUSTED_EXTERNAL_SUFFIXES = (".api.aws",)
_LOCALHOST_NAMES = {"localhost"}

Classification = Literal[
    "localhost",
    "private_network",
    "allowed_external",
    "untrusted_external",
    "invalid",
    "unsupported_scheme",
]


@dataclass(frozen=True)
class McpUrlValidationResult:
    url: str
    is_valid: bool
    allowed: bool
    classification: Classification
    host: str | None
    scheme: str | None
    reason: str
    credentials_allowed: bool

    def to_dict(self) -> dict:
        return asdict(self)


class McpEndpointBlocked(RuntimeError):
    """Raised when an MCP endpoint is not trusted enough to call / attach credentials."""

    def __init__(self, result: McpUrlValidationResult):
        self.result = result
        super().__init__(f"MCP endpoint blocked ({result.reason}): {sanitize_mcp_url(result.url)}")


def sanitize_mcp_url(url: str | None) -> str:
    """Return scheme://host[:port]/path — never userinfo, query, or fragment (token-safe)."""
    if not url:
        return "<missing_url>"
    try:
        parsed = urlparse(str(url).strip())
    except ValueError:
        return "<invalid_url>"
    if not parsed.scheme or not parsed.hostname:
        return "<invalid_url>"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme.lower()}://{parsed.hostname.lower()}{port}{parsed.path or ''}"


def _result(url, *, is_valid, allowed, classification, host, scheme, reason, credentials_allowed):
    return McpUrlValidationResult(
        url=str(url) if url is not None else "",
        is_valid=is_valid,
        allowed=allowed,
        classification=classification,
        host=host,
        scheme=scheme,
        reason=reason,
        credentials_allowed=credentials_allowed,
    )


def validate_mcp_endpoint_url(
    url: str | None,
    *,
    allowed_hosts: Iterable[str] = (),
    allow_localhost: bool = True,
    allow_private_network: bool = True,
    allow_external: bool = False,
) -> McpUrlValidationResult:
    """Classify an MCP URL and decide whether credentials may be attached. Never raises."""
    if not url or not str(url).strip():
        return _result(url, is_valid=False, allowed=False, classification="invalid",
                       host=None, scheme=None, reason="missing_url", credentials_allowed=False)

    raw = str(url).strip()
    try:
        parsed = urlparse(raw)
    except ValueError:
        return _result(raw, is_valid=False, allowed=False, classification="invalid",
                       host=None, scheme=None, reason="invalid_url", credentials_allowed=False)

    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        return _result(raw, is_valid=False, allowed=False, classification="unsupported_scheme",
                       host=None, scheme=scheme or None, reason="unsupported_scheme", credentials_allowed=False)

    # Embedded credentials (https://user:pass@host) are never trusted — fail closed.
    if parsed.username or parsed.password:
        return _result(raw, is_valid=False, allowed=False, classification="invalid",
                       host=(parsed.hostname or "").lower() or None, scheme=scheme,
                       reason="embedded_credentials", credentials_allowed=False)

    host = (parsed.hostname or "").strip().lower()
    if not host:
        return _result(raw, is_valid=False, allowed=False, classification="invalid",
                       host=None, scheme=scheme, reason="invalid_url", credentials_allowed=False)

    allowed_hosts_norm = {h.strip().lower() for h in (allowed_hosts or ()) if h and str(h).strip()}

    # localhost names
    if host in _LOCALHOST_NAMES or host.endswith(".localhost"):
        return _result(raw, is_valid=True, allowed=allow_localhost, classification="localhost",
                       host=host, scheme=scheme,
                       reason="localhost" if allow_localhost else "localhost_disabled",
                       credentials_allowed=allow_localhost)

    # IP literals (loopback / private / public) via the stdlib, not string prefixes.
    try:
        ip = ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if ip.is_loopback:
            return _result(raw, is_valid=True, allowed=allow_localhost, classification="localhost",
                           host=host, scheme=scheme,
                           reason="loopback_ip" if allow_localhost else "localhost_disabled",
                           credentials_allowed=allow_localhost)
        if ip.is_private or ip.is_link_local:
            return _result(raw, is_valid=True, allowed=allow_private_network, classification="private_network",
                           host=host, scheme=scheme,
                           reason="private_network" if allow_private_network else "private_network_disabled",
                           credentials_allowed=allow_private_network)
        # public IP falls through to external handling below

    # Explicit host allowlist
    if host in allowed_hosts_norm:
        return _result(raw, is_valid=True, allowed=True, classification="allowed_external",
                       host=host, scheme=scheme, reason="allowlisted_host", credentials_allowed=True)

    # Built-in AWS-managed trusted suffix (preserves existing AWS MCP behavior)
    if any(host == suffix.lstrip(".") or host.endswith(suffix) for suffix in TRUSTED_EXTERNAL_SUFFIXES):
        return _result(raw, is_valid=True, allowed=True, classification="allowed_external",
                       host=host, scheme=scheme, reason="aws_managed_endpoint", credentials_allowed=True)

    # Global opt-in for any external host (explicit, off by default)
    if allow_external:
        return _result(raw, is_valid=True, allowed=True, classification="allowed_external",
                       host=host, scheme=scheme, reason="external_allowed_by_flag", credentials_allowed=True)

    # Default: external host is untrusted — block and never send credentials.
    return _result(raw, is_valid=True, allowed=False, classification="untrusted_external",
                   host=host, scheme=scheme, reason="untrusted_external_host", credentials_allowed=False)


def evaluate_mcp_endpoint(url: str | None, settings) -> McpUrlValidationResult:
    """Validate an MCP URL using the app settings' trust flags."""
    return validate_mcp_endpoint_url(
        url,
        allowed_hosts=getattr(settings, "mcp_allowed_hosts", ()) or (),
        allow_localhost=getattr(settings, "mcp_allow_localhost", True),
        allow_private_network=getattr(settings, "mcp_allow_private_network", True),
        allow_external=getattr(settings, "mcp_allow_external", False),
    )


def mcp_endpoint_security_entry(url: str | None, settings, *, has_token: bool) -> dict:
    """Token-safe diagnostic entry for one MCP endpoint (no token, sanitized URL)."""
    result = evaluate_mcp_endpoint(url, settings)
    return {
        "enabled": result.credentials_allowed if has_token else result.allowed,
        "classification": result.classification,
        "reason": result.reason,
        "host": result.host,
        "endpoint": sanitize_mcp_url(url) if url else None,
        "credentials_sent": bool(has_token) and result.credentials_allowed,
    }


def mcp_security_status(settings) -> dict:
    """Structured, token-safe MCP trust status for diagnostics/export. No network calls."""
    return {
        "aws_docs_mcp": mcp_endpoint_security_entry(
            getattr(settings, "aws_docs_mcp_url", None), settings,
            has_token=bool(getattr(settings, "aws_docs_mcp_auth_token", None)),
        ),
        "aws_pricing_mcp": mcp_endpoint_security_entry(
            getattr(settings, "aws_pricing_mcp_url", None), settings,
            has_token=bool(getattr(settings, "aws_pricing_mcp_auth_token", None)),
        ),
        "aws_pricing_reference_mcp": mcp_endpoint_security_entry(
            getattr(settings, "aws_pricing_reference_mcp_url", None), settings,
            has_token=bool(getattr(settings, "aws_pricing_reference_mcp_auth_token", None)),
        ),
    }
