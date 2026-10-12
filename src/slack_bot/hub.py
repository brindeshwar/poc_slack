"""MCP client for the ListenLoom meeting hub."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolResult, Tool


class HubError(RuntimeError):
    """A hub tool returned an error, or the hub could not be reached."""


class HubSession(Protocol):
    async def list_tools(self) -> list[Tool]: ...

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any: ...


class _McpHubSession:
    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def list_tools(self) -> list[Tool]:
        return (await self._session.list_tools()).tools

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        result = await self._session.call_tool(name, arguments or {})
        if result.isError:
            raise HubError(_text(result) or f"Tool '{name}' failed")
        return unwrap(result)


class HubClient:
    def __init__(self, server_url: str) -> None:
        self.server_url = server_url

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[HubSession]:
        """One MCP session; reuse it for several calls (e.g. one agent run).

        Connection failures become HubError; exceptions raised by the caller's own code inside
        the `async with` block propagate unchanged."""
        in_body = False
        try:
            async with (
                streamablehttp_client(self.server_url) as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                in_body = True
                yield _McpHubSession(session)
        except Exception as exc:
            inner = _single(exc)
            if in_body or isinstance(inner, HubError):
                raise inner from None
            raise HubError(f"Meeting hub unavailable ({self.server_url}): {inner}") from exc

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        async with self.connect() as session:
            return await session.call(name, arguments)


def unwrap(result: CallToolResult) -> Any:
    """FastMCP returns structured content; non-object results are wrapped as {"result": ...}."""
    structured = result.structuredContent
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
