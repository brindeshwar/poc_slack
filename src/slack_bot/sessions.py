"""Slack agent sessions (status + stop button) and cancellation of in-flight answers.

Slack's Agent Sessions API (`agents.sessions.setStatus`) replaces `assistant.threads.setStatus`: while a
session is `processing`, Slack shows its native "Working..." indicator and, because we subscribe to
`agent_session_stopped`, a stop button. Only apps declared as agents can create sessions, so if the
call fails (app not declared yet, older workspace) we fall back once to Bolt's `set_status`, which
uses the legacy method through Slack's compatibility bridge.
"""

import asyncio
import logging
from typing import Any

from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)

FALLBACK_STATUS = "is thinking…"
TITLE_LIMIT = 200


class AgentSession:
    def __init__(
        self, client: Any, channel: str, thread_ts: str, fallback_set_status: Any = None
    ) -> None:
        self._client = client
        self._channel = channel
        self._thread_ts = thread_ts
        self._fallback = fallback_set_status
        self.uses_sessions = True

    async def processing(self, title: str | None = None) -> None:
        try:
            await self._client.agents_sessions_setStatus(
                channel_id=self._channel,
                thread_ts=self._thread_ts,
                status="processing",
                **({"title": title[:TITLE_LIMIT]} if title else {}),
            )
            return
        except SlackApiError as exc:
            self.uses_sessions = False
            logger.info(
                "agents.sessions.setStatus unavailable (%s); using the legacy status",
                exc.response.get("error"),
            )
        if self._fallback is not None:
            try:
                await self._fallback(FALLBACK_STATUS)
            except SlackApiError as exc:  # the status line is a nicety, never fatal
                logger.debug("set_status failed: %s", exc.response.get("error"))

    async def active(self) -> None:
        """Mark the session ready for the next prompt. Not needed after a stream is stopped
        (chat.stopStream sets the status itself); used when no stream was opened."""
        if not self.uses_sessions:
            return
        try:
            await self._client.agents_sessions_setStatus(
                channel_id=self._channel, thread_ts=self._thread_ts, status="active"
            )
        except SlackApiError as exc:
            logger.debug("Could not set session active: %s", exc.response.get("error"))


class RunRegistry:
    """Tracks the task answering each thread so the native stop button can cancel it."""

    def __init__(self) -> None:
        self._runs: dict[tuple[str, str], asyncio.Task[Any]] = {}

    def register(self, channel: str, thread_ts: str) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._runs[(channel, thread_ts)] = task

    def unregister(self, channel: str, thread_ts: str) -> None:
        self._runs.pop((channel, thread_ts), None)

    def stop(self, channel: str, thread_ts: str) -> bool:
        """Cancel the answer running in this thread. Returns False if nothing was running."""
        task = self._runs.pop((channel, thread_ts), None)
        if task is None or task.done():
            return False
        task.cancel()
        return True
