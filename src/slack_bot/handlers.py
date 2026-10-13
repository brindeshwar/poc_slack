"""Slack listeners. The logic lives in plain async functions so it can be tested without Slack."""

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from slack_bolt.async_app import AsyncApp
from slack_sdk.errors import SlackApiError

from slack_bot.agent import MeetingAgent, Status, Turn
from slack_bot.formatting import (
    jira_blocks,
    summary_blocks,
    todo_blocks,
    user_story_blocks,
)
from slack_bot.hub import HubClient, HubError

logger = logging.getLogger(__name__)

Respond = Callable[..., Awaitable[Any]]

MEETING_COMMANDS: dict[str, Callable[[dict[str, Any]], list[dict[str, Any]]]] = {
    "/lastmeetingsummary": summary_blocks,
    "/lastmeetingtodo": todo_blocks,
    "/lastmeetinguserstory": user_story_blocks,
}
JIRA_COMMAND = "/meetingtojira"

HELP_TEXT = (
    "Hi! Ask me anything about your meetings, for example:\n"
    "• _What did we decide about the influencer budget?_\n"
    "• _Who owns the rollback plan?_\n"
    "• _Create Jira tasks for the last meeting_\n"
    "Slash commands: `/lastmeetingsummary`, `/lastmeetingtodo`, `/lastmeetinguserstory`, "
    "`/meetingtojira [preview]`"
)
THINKING_STATUS = "Thinking…"
HISTORY_MESSAGES = 20
HISTORY_CHARS = 6000


async def meeting_command(command: str, respond: Respond, hub: HubClient) -> None:
    try:
        meeting = await hub.call("get_latest_meeting")
    except HubError as exc:
        await respond(response_type="ephemeral", text=f":warning: {exc}")
        return
    blocks = MEETING_COMMANDS[command](meeting)
    await respond(
        response_type="in_channel", text=f"Latest meeting: {meeting['title']}", blocks=blocks
    )


async def jira_command(text: str, respond: Respond, hub: HubClient) -> None:
    dry_run = text.strip().lower() in {"preview", "dry-run", "dryrun"}
    try:
        result = await hub.call("create_jira_tasks", {"dry_run": dry_run})
    except HubError as exc:
        await respond(response_type="ephemeral", text=f":warning: {exc}")
        return
    await respond(response_type="in_channel", text=result["message"], blocks=jira_blocks(result))


def strip_mention(text: str, bot_user_id: str | None) -> str:
    pattern = rf"<@{re.escape(bot_user_id)}>" if bot_user_id else r"<@[A-Z0-9]+>"
    return re.sub(pattern, "", text or "").strip()


async def thread_history(
    client: Any, channel: str, event: dict[str, Any], bot_user_id: str | None
) -> list[Turn]:
    """Earlier messages of the thread as conversation turns (oldest first), so follow-ups like
    "who owns that?" have context. Bounded to the last HISTORY_MESSAGES / HISTORY_CHARS."""
    thread_ts = event.get("thread_ts")
    if not thread_ts:
        return []
    try:
        response = await client.conversations_replies(
            channel=channel, ts=thread_ts, limit=HISTORY_MESSAGES + 1
        )
    except SlackApiError as exc:  # e.g. missing channels:history scope
        logger.warning("Could not read thread history: %s", exc.response.get("error"))
        return []

    turns: list[Turn] = []
    for message in response.get("messages", []):
        if message.get("ts") == event.get("ts"):
            continue  # the current question is passed separately
        text = strip_mention(message.get("text", ""), bot_user_id)
        if not text or text == HELP_TEXT:
            continue
        is_bot = bool(message.get("bot_id")) or message.get("user") == bot_user_id
        turns.append(("model" if is_bot else "user", text))

    kept, size = [], 0
    for turn in reversed(turns[-HISTORY_MESSAGES:]):  # keep the most recent within the budget
        size += len(turn[1])
        if size > HISTORY_CHARS:
            break
        kept.append(turn)
    return list(reversed(kept))


async def answer_mention(
    event: dict[str, Any],
    bot_user_id: str | None,
    client: Any,
    agent: MeetingAgent,
    say_stream: Any,
    set_status: Any,
) -> None:
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    question = strip_mention(event.get("text", ""), bot_user_id)

    if not question:
        await client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=HELP_TEXT)
        return

    history = await thread_history(client, channel, event, bot_user_id)
    await _status(set_status, THINKING_STATUS)
    stream = await say_stream()
    try:
        async for update in agent.stream(question, history):
            if isinstance(update, Status):
                await _status(set_status, update.text)
            else:
                await stream.append(markdown_text=update.text)
    except HubError as exc:
        logger.warning("Hub error while answering %r: %s", question, exc)
        await stream.append(
            markdown_text=f"\n\n:warning: I couldn't reach the meeting hub right now. ({exc})"
        )
    except Exception:
        logger.exception("Agent failed while answering %r", question)
        await stream.append(
            markdown_text="\n\n:warning: Something went wrong while answering. The error has been logged."
        )
    finally:
        await stream.stop()


async def _status(set_status: Any, text: str) -> None:
    """The status line is a nicety; never let it break an answer (e.g. missing assistant:write)."""
    if set_status is None:
        return
    try:
        await set_status(text)
    except SlackApiError as exc:
        logger.debug("set_status failed: %s", exc.response.get("error"))


def register(app: AsyncApp, hub: HubClient, agent: MeetingAgent) -> None:
    async def on_meeting_command(ack, command, respond):
        await ack()
        await meeting_command(command["command"], respond, hub)

    for name in MEETING_COMMANDS:
        app.command(name)(on_meeting_command)

    @app.command(JIRA_COMMAND)
    async def on_jira_command(ack, command, respond):
        await ack()
        await jira_command(command.get("text", ""), respond, hub)

    @app.event("app_mention")
    async def on_mention(event, context, client, say_stream, set_status):
        await answer_mention(event, context.bot_user_id, client, agent, say_stream, set_status)
