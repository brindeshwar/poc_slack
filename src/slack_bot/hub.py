"""MCP client for the ListenLoom meeting hub."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.types import CallToolResult, Tool


class HubError(RuntimeError):
    """A hub tool returned an error, or the hub could not be reached."""


class HubSession(Protocol):
    async def list_tools(self) -> list[Tool]: ...

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any: ...


class _McpHubSession:
    def __init__(self, client: Client) -> None:
        self._client = client

    async def list_tools(self) -> list[Tool]:
        return (await self._client.list_tools()).tools

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        result = await self._client.call_tool(name, arguments or {})
        if result.is_error:
            raise HubError(_text(result) or f"Tool '{name}' failed")
        return unwrap(result)


class HubClient:
    def __init__(self, server_url: str, token: str | None = None) -> None:
        self.server_url = server_url
        self._token = token

    def _client(self) -> Client:
        """Sends `Authorization: Bearer <MCP_AUTH_TOKEN>` when the hub requires it."""
        if not self._token:
            return Client(self.server_url)
        http = create_mcp_http_client(headers={"Authorization": f"Bearer {self._token}"})
        return Client(streamable_http_client(self.server_url, http_client=http))

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[HubSession]:
        """One MCP session; reuse it for several calls (e.g. one agent run).

        Connection failures become HubError; exceptions raised by the caller's own code inside
        the `async with` block propagate unchanged."""
        in_body = False
        try:
            async with self._client() as client:
                in_body = True
                yield _McpHubSession(client)
        except Exception as exc:
            inner = _single(exc)
            if in_body or isinstance(inner, HubError):
                raise inner from None
            if "error response" in str(inner):  # e.g. 401: the SDK reports it generically
                raise HubError(
                    "The meeting hub refused the session (usually a wrong or missing MCP_AUTH_TOKEN)."
                ) from exc
            raise HubError(f"Meeting hub unavailable ({self.server_url}): {inner}") from exc

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        async with self.connect() as session:
            return await session.call(name, arguments)


def unwrap(result: CallToolResult) -> Any:
    """MCPServer returns structured content; non-object results are wrapped as {"result": ...}."""
    structured = result.structured_content
    if structured is None:
        text = _text(result)
        try:
            return json.loads(text)
        except ValueError:
            return text
    if set(structured) == {"result"}:
        return structured["result"]
    return structured


def _single(exc: Exception) -> Exception:
    """anyio task groups may wrap a lone exception in an ExceptionGroup; unwrap it."""
    while isinstance(exc, ExceptionGroup) and len(exc.exceptions) == 1:
        exc = exc.exceptions[0]
    return exc


def _text(result: CallToolResult) -> str:
    return " ".join(getattr(c, "text", "") for c in result.content).strip()
