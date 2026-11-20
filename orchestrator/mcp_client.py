"""Minimal MCP client for local stdio servers (plan section 9, step 5).

Only servers allowlisted in `config/mcp.yaml` start. Every tool they expose
registers at tier 3 (approval every time) unless the config reclassifies it
by hand. Each server is third-party code running with the user's file
permissions, so the allowlist is the control, not this client.

Implements the subset of the Model Context Protocol this build needs:
`initialize`, `tools/list` and `tools/call` over newline-delimited JSON-RPC.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from orchestrator.errors import ToolExecutionError
from orchestrator.settings import McpServerSettings
from orchestrator.toolkit.context import ToolContext
from orchestrator.toolkit.registry import (
    ToolDefinition,
    ToolOutput,
    ToolRegistry,
    ToolTier,
)

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "local-cowork", "version": "0.1.0"}
EMPTY_OBJECT_SCHEMA = {"type": "object", "properties": {}}


class McpServerConnection:
    """One running MCP server process."""

    def __init__(self, server_settings: McpServerSettings) -> None:
        self._settings = server_settings
        self._process: asyncio.subprocess.Process | None = None
        self._next_request_id = 0
        # stdio carries one conversation; concurrent calls would interleave.
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        """The server's configured name."""
        return self._settings.name

    async def start(self) -> list[dict[str, Any]]:
        """Start the server, initialise it and return its tool descriptions.

        Raises:
            ToolExecutionError: If the process cannot start or does not
                answer within the configured start-up timeout.
        """
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self._settings.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as exc:
            raise ToolExecutionError(
                "MCP server could not be started", server_name=self.name
            ) from exc
        timeout_seconds = self._settings.startup_timeout_seconds
        await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
            timeout_seconds,
        )
        await self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        listing = await self._request("tools/list", {}, timeout_seconds)
        return list(listing.get("tools", []))

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Call a tool and return its text content."""
        result = await self._request(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
            self._settings.call_timeout_seconds,
        )
        text_parts = [
            str(part.get("text", ""))
            for part in result.get("content", [])
            if part.get("type") == "text"
        ]
        text = "\n".join(text_parts)
        if result.get("isError"):
            raise ToolExecutionError(f"the connector reported an error: {text[:300]}")
        return text

    async def stop(self) -> None:
        """Terminate the server process."""
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            await self._process.wait()

    async def _send(self, message: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise ToolExecutionError("MCP server is not running", server_name=self.name)
        self._process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        await self._process.stdin.drain()

    async def _request(
        self, method: str, params: dict[str, Any], timeout_seconds: float
    ) -> dict[str, Any]:
        async with self._lock:
            self._next_request_id += 1
            request_id = self._next_request_id
            await self._send(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            )
            try:
                return await asyncio.wait_for(
                    self._read_response(request_id), timeout_seconds
                )
            except TimeoutError as exc:
                raise ToolExecutionError(
                    "the connector did not answer in time",
                    server_name=self.name,
                    method=method,
                ) from exc

    async def _read_response(self, request_id: int) -> dict[str, Any]:
        if self._process is None or self._process.stdout is None:
            raise ToolExecutionError("MCP server is not running", server_name=self.name)
        while True:
            line = await self._process.stdout.readline()
            if not line:
                raise ToolExecutionError(
                    "the connector closed unexpectedly", server_name=self.name
                )
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                # Servers sometimes write log lines to stdout; skip them.
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise ToolExecutionError(
                    f"the connector rejected the call: "
                    f"{str(message['error'].get('message', ''))[:300]}"
                )
            return dict(message.get("result") or {})


def _make_handler(connection: McpServerConnection, remote_tool_name: str) -> Any:
    async def call_mcp_tool(
        context: ToolContext, arguments: dict[str, Any]
    ) -> ToolOutput:
        return ToolOutput(await connection.call_tool(remote_tool_name, arguments))

    return call_mcp_tool


async def start_mcp_servers(
    server_settings_list: tuple[McpServerSettings, ...], registry: ToolRegistry
) -> list[McpServerConnection]:
    """Start every allowlisted server and register its tools.

    A server that fails to start is logged and skipped so one broken
    connector does not stop the orchestrator.
    """
    connections: list[McpServerConnection] = []
    for server_settings in server_settings_list:
        connection = McpServerConnection(server_settings)
        try:
            remote_tools = await connection.start()
        except ToolExecutionError:
            logger.exception(
                "MCP server failed to start; skipped",
                extra={"server_name": server_settings.name},
            )
            await connection.stop()
            continue
        for remote_tool in remote_tools:
            remote_name = str(remote_tool["name"])
            tier = ToolTier(
                server_settings.tier_overrides.get(remote_name, ToolTier.EXTERNAL)
            )
            registry.register(
                ToolDefinition(
                    name=f"{server_settings.name}__{remote_name}".replace("-", "_"),
                    description=str(remote_tool.get("description", ""))[:300],
                    parameters=remote_tool.get("inputSchema") or EMPTY_OBJECT_SCHEMA,
                    tier=tier,
                    handler=_make_handler(connection, remote_name),
                    keywords=(server_settings.name, "connector"),
                )
            )
        logger.info(
            "MCP server started",
            extra={
                "server_name": server_settings.name,
                "tool_count": len(remote_tools),
            },
        )
        connections.append(connection)
    return connections
