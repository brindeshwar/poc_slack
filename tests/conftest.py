from contextlib import asynccontextmanager
from typing import Any

import pytest
from mcp.types import Tool

from slack_bot.hub import HubError

MEETING = {
    "meeting_id": "m1",
    "title": "Eng sync",
    "held_at": "2025-07-02T10:00:00+00:00",
    "summary": "We planned the <Atlas> migration & rollback.",
    "action_items": [
        {"summary": "Write the rollback plan", "assignee": "Eve", "due_date": "2025-07-08"},
        {"summary": "Automate the pipeline", "assignee": None, "due_date": None},
    ],
    "user_stories": ["As an admin, I want an audit log so that I can trace changes."],
}


class FakeHub:
    """Stands in for HubClient (and its sessions) with canned tool results."""

    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self.results = results or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.tools = [
            Tool(name=name, description=f"{name} tool", inputSchema={"type": "object"})
            for name in ("ask_meetings", "get_latest_meeting", "create_jira_tasks")
        ]

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.calls.append((name, arguments or {}))
        result = self.results.get(name)
        if isinstance(result, Exception):
            raise result
        if result is None:
            raise HubError(f"no fake result for {name}")
        return result

    async def list_tools(self) -> list[Tool]:
        return self.tools

    @asynccontextmanager
    async def connect(self):
        yield self


class Recorder:
    """Collects calls to Slack's respond() / client methods."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __getattr__(self, name: str):
        async def method(**kwargs):
            self.calls.append((name, kwargs))
            return {"ok": True, "ts": "999.1"}

        return method

    async def __call__(self, **kwargs):
        self.calls.append(("respond", kwargs))


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()
