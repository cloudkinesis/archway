from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from uuid import uuid4

from app.core.logging import AuditLogger, hash_payload


class MCPStdioClient:
    def __init__(self, *, command: str, args: list[str], env: dict[str, str] | None, server_name: str, session_id: str | None, timeout_seconds: float = 45.0):
        self.command = command
        self.args = args
        self.env = env or {}
        self.server_name = server_name
        self.session_id = session_id
        self.timeout_seconds = timeout_seconds

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._with_server(lambda rpc: rpc.request("tools/list", {}))
        tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(tools, list):
            raise RuntimeError("MCP server returned an unsupported tools/list shape.")
        return [tool for tool in tools if isinstance(tool, dict)]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        AuditLogger(self.session_id).event(
            "research",
            "mcp_tool_call_started",
            tool_name=f"{self.server_name}:{tool_name}",
            inputs_hash=hash_payload({"tool_name": tool_name, "arguments": arguments}),
        )
        result = await self._with_server(lambda rpc: rpc.request("tools/call", {"name": tool_name, "arguments": arguments}))
        if not isinstance(result, dict):
            raise RuntimeError("MCP tool returned an unsupported result shape.")
        AuditLogger(self.session_id).event(
            "research",
            "mcp_tool_call_completed",
            tool_name=f"{self.server_name}:{tool_name}",
            output_hash=hash_payload(result),
        )
        return result

    async def call_tools(self, calls: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
        if not calls:
            return []
        for tool_name, arguments in calls:
            AuditLogger(self.session_id).event(
                "research",
                "mcp_tool_call_started",
                tool_name=f"{self.server_name}:{tool_name}",
                inputs_hash=hash_payload({"tool_name": tool_name, "arguments": arguments}),
            )

        async def _run_calls(rpc):
            results = []
            for tool_name, arguments in calls:
                result = await rpc.request("tools/call", {"name": tool_name, "arguments": arguments})
                if not isinstance(result, dict):
                    raise RuntimeError("MCP tool returned an unsupported result shape.")
                results.append(result)
            return results

        results = await self._with_server(_run_calls)
        for (tool_name, _arguments), result in zip(calls, results, strict=False):
            AuditLogger(self.session_id).event(
                "research",
                "mcp_tool_call_completed",
                tool_name=f"{self.server_name}:{tool_name}",
                output_hash=hash_payload(result),
            )
        return results

    async def _with_server(self, action):
        env = {**os.environ, **self.env}
        process = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        rpc = _StdioRPC(process, self.timeout_seconds)
        try:
            await rpc.initialize()
            return await action(rpc)
        finally:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()


class _StdioRPC:
    def __init__(self, process: asyncio.subprocess.Process, timeout_seconds: float):
        self.process = process
        self.timeout_seconds = timeout_seconds

    async def initialize(self) -> None:
        result = await self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "archway", "version": "0.1"},
            },
        )
        if not isinstance(result, dict):
            raise RuntimeError("MCP initialize returned an unsupported result shape.")
        await self.notify("notifications/initialized", {})

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = uuid4().hex
        await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            payload = await self._read()
            if payload.get("id") != request_id:
                continue
            if "error" in payload:
                error = payload["error"]
                message = error.get("message") if isinstance(error, dict) else str(error)
                raise RuntimeError(message or f"MCP request failed: {method}")
            result = payload.get("result")
            return result if isinstance(result, dict) else {"result": result}

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def _write(self, payload: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise RuntimeError("MCP process stdin is unavailable.")
        self.process.stdin.write((json.dumps(payload) + "\n").encode())
        await self.process.stdin.drain()

    async def _read(self) -> dict[str, Any]:
        if self.process.stdout is None:
            raise RuntimeError("MCP process stdout is unavailable.")
        line = await asyncio.wait_for(self.process.stdout.readline(), timeout=self.timeout_seconds)
        if not line:
            stderr = ""
            if self.process.stderr is not None:
                try:
                    chunk = await asyncio.wait_for(self.process.stderr.read(), timeout=1)
                    stderr = chunk.decode(errors="replace")[:1000]
                except Exception:
                    stderr = ""
            raise RuntimeError(f"MCP process ended before responding. {stderr}".strip())
        try:
            return json.loads(line.decode())
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"MCP server emitted non-JSON stdout: {line[:200]!r}") from exc
