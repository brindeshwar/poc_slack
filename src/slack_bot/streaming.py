"""A chat stream that respects Slack's streaming limits.

Slack caps one streamed message at 12,000 characters of markdown in total and closes it 10 minutes after
it started. This wrapper:

- shows tool calls as task cards (`task_update` chunks, timeline mode);
- rolls over to a new streamed message in the same thread before the character limit, keeping the
  agent session `processing` in between;
- falls back to `chat.postMessage` if Slack has already closed the stream (timeout).
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)

MAX_STREAM_CHARS = 12_000
ROLLOVER_AT = 11_000  # leave headroom for the closing note / feedback


class LimitedStream:
    def __init__(
        self,
        open_stream: Callable[[], Awaitable[Any]],
        client: Any,
        channel: str,
        thread_ts: str,
        *,
        rollover_at: int = ROLLOVER_AT,
    ) -> None:
        self._open = open_stream
        self._client = client
        self._channel = channel
        self._thread_ts = thread_ts
        self._rollover_at = rollover_at
        self._stream: Any = None
        self._chars = 0
        self._closed_by_slack = False
        self.messages = 0  # streamed messages used (for tests / logs)

    async def _current(self) -> Any:
        if self._stream is None:
            self._stream = await self._open()
            self._chars = 0
            self.messages += 1
        return self._stream

    async def text(self, text: str) -> None:
        if not text:
            return
        if self._closed_by_slack:
            await self._post(text)
            return
        if self._chars and self._chars + len(text) > self._rollover_at:
            await self._rollover()
        for piece in _split(text, self._rollover_at):
            stream = await self._current()
            try:
                await stream.append(markdown_text=piece)
                self._chars += len(piece)
            except SlackApiError as exc:
                await self._handle(exc, piece)
            if self._chars >= self._rollover_at:
                await self._rollover()

    async def task(self, task_id: str, title: str, status: str) -> None:
        """Show or update a task card (`pending`, `in_progress`, `complete`, `error`)."""
        if self._closed_by_slack:
            return
        stream = await self._current()
        chunk = {"type": "task_update", "id": task_id, "title": title, "status": status}
        try:
            await stream.append(chunks=[chunk])
        except SlackApiError as exc:
            await self._handle(exc, None)

    async def finish(self, blocks: list[dict[str, Any]] | None = None) -> None:
        if self._closed_by_slack:
            return
        stream = await self._current()
        try:
            await stream.stop(blocks=blocks, session_status="active")
        except SlackApiError as exc:
            if _error(exc) != "message_not_in_streaming_state":
                raise
            logger.info("Stream already finalized by Slack; nothing to stop")
        self._stream = None

    async def _rollover(self) -> None:
        if self._stream is None:
            return
        try:
            await self._stream.stop(session_status="processing")
        except SlackApiError as exc:
            logger.info("Could not stop full stream: %s", _error(exc))
        self._stream = None

    async def _handle(self, exc: SlackApiError, pending_text: str | None) -> None:
        error = _error(exc)
        if error == "msg_too_long":
            await self._rollover()
            if pending_text:
                await self.text(pending_text)
        elif error == "message_not_in_streaming_state":
            logger.info("Slack closed the stream (10-minute limit); continuing with plain messages")
            self._closed_by_slack = True
            self._stream = None
            if pending_text:
                await self._post(pending_text)
        else:
            raise exc

    async def _post(self, text: str) -> None:
        await self._client.chat_postMessage(
            channel=self._channel, thread_ts=self._thread_ts, markdown_text=text
        )


def _split(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def _error(exc: SlackApiError) -> str | None:
    try:
        return exc.response.get("error")
    except AttributeError:
        return None
