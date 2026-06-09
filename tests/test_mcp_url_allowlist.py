"""MCP URL allowlist / token-egress hardening.

Tokens must never be sent to arbitrary external MCP hosts. Local/private endpoints
work by default; external hosts must be explicitly allowlisted (or globally opted-in).
No live network — blocked endpoints fail closed before any HTTP call.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.core.config import get_settings
from app.services.mcp_http import MCPHTTPClient
from app.services.mcp_security import (
    McpEndpointBlocked,
    mcp_security_status,
    sanitize_mcp_url,
    validate_mcp_endpoint_url,
)


@pytest.fixture(autouse=True)
def _clean_settings():
    for key in ("ARCHWAY_MCP_ALLOW_LOCALHOST", "ARCHWAY_MCP_ALLOW_PRIVATE_NETWORK",
                "ARCHWAY_MCP_ALLOW_EXTERNAL", "ARCHWAY_MCP_ALLOWED_HOSTS",
                "ARCHWAY_AWS_PRICING_MCP_URL", "ARCHWAY_AWS_PRICING_MCP_AUTH_TOKEN",
                "ARCHWAY_AWS_DOCS_MCP_URL", "ARCHWAY_AWS_DOCS_MCP_AUTH_TOKEN"):
        import os
        os.environ.pop(key, None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ----------------------------- URL validation ----------------------------- #
def test_localhost_mcp_url_allowed_by_default():
    r = validate_mcp_endpoint_url("http://localhost:8931/mcp")
    assert r.classification == "localhost" and r.allowed and r.credentials_allowed


def test_loopback_ip_allowed_by_default():
    assert validate_mcp_endpoint_url("http://127.0.0.1:9000/mcp").credentials_allowed
    assert validate_mcp_endpoint_url("http://[::1]:9000/mcp").credentials_allowed


def test_private_ip_allowed_by_default():
    for url in ("http://10.2.3.4:8080/mcp", "http://192.168.1.10/mcp", "http://172.16.5.9/mcp"):
        r = validate_mcp_endpoint_url(url)
        assert r.classification == "private_network" and r.credentials_allowed, url


def test_external_url_blocked_by_default():
    r = validate_mcp_endpoint_url("https://evil.example.com/mcp")
    assert r.classification == "untrusted_external"
    assert r.allowed is False and r.credentials_allowed is False
    assert r.reason == "untrusted_external_host"


def test_external_allowlisted_host_allowed():
    r = validate_mcp_endpoint_url("https://pricing-mcp.company.net/mcp",
                                  allowed_hosts=["pricing-mcp.company.net"])
    assert r.classification == "allowed_external" and r.allowed and r.credentials_allowed


def test_external_allowed_by_global_flag_is_explicit_optin():
    # allow_external=True is an explicit opt-in to trust ALL external hosts.
    r = validate_mcp_endpoint_url("https://anything.example.com/mcp", allow_external=True)
    assert r.allowed and r.credentials_allowed and r.reason == "external_allowed_by_flag"


def test_aws_managed_suffix_trusted_by_default():
    r = validate_mcp_endpoint_url("https://pricing.api.aws/mcp")
    assert r.classification == "allowed_external" and r.credentials_allowed
    assert r.reason == "aws_managed_endpoint"


def test_unsupported_scheme_blocked():
    for url in ("file:///etc/passwd", "ftp://host/mcp", "javascript:alert(1)", "data:text/plain,hi"):
        r = validate_mcp_endpoint_url(url)
        assert r.classification == "unsupported_scheme" and not r.credentials_allowed, url


def test_invalid_url_blocked():
    for url in ("not a url", "http://", "", None):
        r = validate_mcp_endpoint_url(url)
        assert not r.allowed and not r.credentials_allowed


def test_embedded_credentials_blocked():
    r = validate_mcp_endpoint_url("https://user:pass@example.com/mcp")
    assert not r.allowed and not r.credentials_allowed
    assert r.reason == "embedded_credentials"


def test_url_sanitization_removes_query_and_credentials():
    out = sanitize_mcp_url("https://user:secretpass@mcp.example.com:8443/mcp?token=ABCDEF&x=1#frag")
    assert "secretpass" not in out and "ABCDEF" not in out and "token" not in out
    assert out == "https://mcp.example.com:8443/mcp"


# ----------------------------- header / token safety ---------------------- #
def _client(url, token, monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    return MCPHTTPClient(server_url=url, auth_token=token, server_name="Test MCP", session_id="s1")


def test_untrusted_external_mcp_does_not_attach_bearer_token(monkeypatch):
    calls = {"n": 0}

    async def _boom(*args, **kwargs):
        calls["n"] += 1
        raise AssertionError("network call attempted to untrusted host")

    monkeypatch.setattr(httpx.AsyncClient, "post", _boom)
    client = _client("https://evil.example.com/mcp", "SUPERSECRETTOKEN", monkeypatch)
    with pytest.raises(McpEndpointBlocked):
        asyncio.run(client.call_tool("search", {"q": "x"}))
    assert calls["n"] == 0  # no network
    assert "Authorization" not in client._headers()  # token never attached


def test_allowlisted_external_mcp_can_attach_bearer_token(monkeypatch):
    client = _client("https://mcp.company.net/mcp", "TOK", monkeypatch,
                     ARCHWAY_MCP_ALLOWED_HOSTS="mcp.company.net")
    assert client.validation.credentials_allowed
    assert client._headers().get("Authorization") == "Bearer TOK"


def test_invalid_mcp_url_disables_client_without_network(monkeypatch):
    calls = {"n": 0}

    async def _boom(*args, **kwargs):
        calls["n"] += 1
        raise AssertionError("network attempted")

    monkeypatch.setattr(httpx.AsyncClient, "post", _boom)
    client = _client("not a url", "TOK", monkeypatch)
    with pytest.raises(McpEndpointBlocked):
        asyncio.run(client.call_tool("search", {}))
    assert calls["n"] == 0


# ----------------------------- client / fallback / status ------------------ #
def test_pricing_mcp_unsafe_url_fails_closed_without_network(monkeypatch):
    # The pricing MCP call site wraps this in try/except -> heuristic/snapshot fallback.
    calls = {"n": 0}

    async def _boom(*args, **kwargs):
        calls["n"] += 1
        raise AssertionError("network attempted")

    monkeypatch.setattr(httpx.AsyncClient, "post", _boom)
    client = _client("https://pricing.evil.example.com/mcp", "PRICETOKEN", monkeypatch)
    with pytest.raises(McpEndpointBlocked):
        asyncio.run(client.call_tool("get_pricing", {}))
    assert calls["n"] == 0


def test_docs_mcp_unsafe_url_fails_closed_without_network(monkeypatch):
    calls = {"n": 0}

    async def _boom(*args, **kwargs):
        calls["n"] += 1
        raise AssertionError("network attempted")

    monkeypatch.setattr(httpx.AsyncClient, "post", _boom)
    client = _client("https://docs.evil.example.com/mcp", "DOCSTOKEN", monkeypatch)
    with pytest.raises(McpEndpointBlocked):
        asyncio.run(client.call_tool("search_documentation", {}))
    assert calls["n"] == 0


def test_mcp_security_status_reports_disabled_for_unsafe_url(monkeypatch):
    monkeypatch.setenv("ARCHWAY_AWS_PRICING_MCP_URL", "https://evil.example.com/mcp")
    monkeypatch.setenv("ARCHWAY_AWS_PRICING_MCP_AUTH_TOKEN", "SECRET")
    get_settings.cache_clear()
    status = mcp_security_status(get_settings())
    entry = status["aws_pricing_mcp"]
    assert entry["enabled"] is False
    assert entry["reason"] == "untrusted_external_host"
    assert entry["credentials_sent"] is False
    assert entry["host"] == "evil.example.com"


def test_diagnostics_do_not_leak_mcp_token(monkeypatch):
    monkeypatch.setenv("ARCHWAY_AWS_PRICING_MCP_URL", "https://evil.example.com/mcp?token=LEAKTOKEN")
    monkeypatch.setenv("ARCHWAY_AWS_PRICING_MCP_AUTH_TOKEN", "BEARER_SECRET_VALUE")
    get_settings.cache_clear()
    blob = json.dumps(mcp_security_status(get_settings()))
    assert "BEARER_SECRET_VALUE" not in blob
    assert "LEAKTOKEN" not in blob  # query string stripped from sanitized endpoint


def test_allowed_private_mcp_does_not_break_existing_local_dev(monkeypatch):
    client = _client("http://localhost:8931/mcp", "LOCALTOKEN", monkeypatch)
    assert client.validation.credentials_allowed
    assert client._headers().get("Authorization") == "Bearer LOCALTOKEN"
    # And an explicitly disabled localhost flag fails closed.
    client2 = _client("http://localhost:8931/mcp", "LOCALTOKEN", monkeypatch,
                      ARCHWAY_MCP_ALLOW_LOCALHOST="false")
    assert client2.validation.credentials_allowed is False
