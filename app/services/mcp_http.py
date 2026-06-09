from typing import Any
from uuid import uuid4
import json

import httpx

from app.core.config import get_settings
from app.core.logging import AuditLogger, hash_payload
from app.models.domain import EvidenceItem
from app.services.mcp_security import (
    McpEndpointBlocked,
    evaluate_mcp_endpoint,
    sanitize_mcp_url,
)


class MCPHTTPClient:
    def __init__(self, *, server_url: str, auth_token: str | None, server_name: str, session_id: str | None):
        self.server_url = server_url
        self.auth_token = auth_token
        self.server_name = server_name
        self.session_id = session_id
        self._mcp_session_id: str | None = None
        # Validate trust eagerly (no network). Credentials are only ever attached to a
        # trusted endpoint; an untrusted endpoint fails closed in call_tool().
        self.validation = evaluate_mcp_endpoint(server_url, get_settings())

    def _ensure_endpoint_trusted(self) -> None:
        if not self.validation.credentials_allowed:
            # Token-safe warning: sanitized URL, host, reason — never the token itself.
            AuditLogger(self.session_id).event(
                "research",
                "mcp_endpoint_blocked",
                server_name=self.server_name,
                endpoint=sanitize_mcp_url(self.server_url),
                host=self.validation.host,
                classification=self.validation.classification,
                reason=self.validation.reason,
                credentials_sent=False,
            )
            raise McpEndpointBlocked(self.validation)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        # Fail closed BEFORE building headers or making any network call.
        self._ensure_endpoint_trusted()
        request_payload = {
            "jsonrpc": "2.0",
            "id": uuid4().hex,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        AuditLogger(self.session_id).event(
            "research",
            "mcp_tool_call_started",
            tool_name=f"{self.server_name}:{tool_name}",
            inputs_hash=hash_payload({"tool_name": tool_name, "arguments": arguments}),
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(self.server_url, json=request_payload, headers=self._headers())
            payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            if _requires_mcp_session(payload):
                await self._initialize_session(client)
                response = await client.post(self.server_url, json=request_payload, headers=self._headers())
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            message = payload["error"].get("message", "MCP tool returned an error")
            raise RuntimeError(message)
        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("MCP tool returned an unsupported result shape.")
        AuditLogger(self.session_id).event(
            "research",
            "mcp_tool_call_completed",
            tool_name=f"{self.server_name}:{tool_name}",
            output_hash=hash_payload(result),
        )
        return result

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        # Defense in depth: only ever attach the bearer token to a trusted endpoint.
        if self.auth_token and self.validation.credentials_allowed:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        if self._mcp_session_id:
            headers["Mcp-Session-Id"] = self._mcp_session_id
        return headers

    async def _initialize_session(self, client: httpx.AsyncClient) -> None:
        payload = {
            "jsonrpc": "2.0",
            "id": uuid4().hex,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "archway", "version": "0.1"},
            },
        }
        response = await client.post(self.server_url, json=payload, headers=self._headers())
        response.raise_for_status()
        self._mcp_session_id = response.headers.get("mcp-session-id") or response.headers.get("Mcp-Session-Id")
        if not self._mcp_session_id:
            raise RuntimeError("MCP server requires a session but did not return an MCP session id.")


def _requires_mcp_session(payload: dict[str, Any]) -> bool:
    error = payload.get("error")
    if not isinstance(error, dict):
        return False
    return "session id is required" in str(error.get("message", "")).lower()


def mcp_result_to_evidence(
    *,
    result: dict[str, Any],
    source_type: str,
    tool_name: str,
    fallback_title: str,
    confidence: str = "medium",
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    candidates = _extract_candidates(result)
    for index, item in enumerate(candidates, start=1):
        if isinstance(item, str):
            items.append(
                EvidenceItem(
                    source_type=source_type,
                    title=f"{fallback_title} {index}",
                    quote_or_summary=_clean_text(item),
                    tool_name=tool_name,
                    confidence=confidence,
                )
            )
            continue
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or f"{fallback_title} {index}")
        url = item.get("url") or item.get("uri") or item.get("source")
        summary = item.get("content") or item.get("text") or item.get("summary") or item.get("snippet") or item.get("context") or item.get("description") or ""
        if not summary and item.get("json"):
            summary = str(item["json"])
        items.append(
            EvidenceItem(
                source_type=source_type,
                title=_clean_text(title)[:240],
                url=url if isinstance(url, str) and url.startswith(("http://", "https://")) else None,
                quote_or_summary=_clean_text(str(summary))[:1200] or "MCP tool returned this source.",
                tool_name=tool_name,
                confidence=confidence,
            )
        )
    return items


def _extract_candidates(result: dict[str, Any]) -> list[Any]:
    if isinstance(result.get("results"), list):
        return result["results"]
    if isinstance(result.get("items"), list):
        return result["items"]
    nested_content = result.get("content")
    if isinstance(nested_content, dict):
        nested_result = nested_content.get("result")
        if isinstance(nested_result, list):
            return nested_result
    content = result.get("content")
    if isinstance(content, list):
        extracted = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parsed = _json_candidates(text)
                    if parsed is not None:
                        extracted.extend(parsed)
                    else:
                        extracted.append(text)
                else:
                    extracted.append(block.get("content") or block)
            else:
                extracted.append(block)
        return extracted
    if isinstance(content, str):
        parsed = _json_candidates(content)
        if parsed is not None:
            return parsed
        return [content]
    return [result]


def _clean_text(text: str) -> str:
    return " ".join(text.replace("\x00", "").split())


def _json_candidates(text: str) -> list[Any] | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        if isinstance(parsed.get("results"), list):
            return parsed["results"]
        if isinstance(parsed.get("items"), list):
            return parsed["items"]
        content = parsed.get("content")
        if isinstance(content, dict) and isinstance(content.get("result"), list):
            return content["result"]
        if isinstance(content, list):
            return content
    if isinstance(parsed, list):
        return parsed
    return None
