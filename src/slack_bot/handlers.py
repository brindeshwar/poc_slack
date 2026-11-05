"""Slack listeners. The logic lives in plain async functions so it can be tested without Slack."""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from slack_bolt.async_app import AsyncApp
from slack_sdk.errors import SlackApiError

from slack_bot.agent import MeetingAgent, TextDelta, ToolFinished, ToolStarted, Turn
from slack_bot.formatting import (
    jira_blocks,
    summary_blocks,
    todo_blocks,
    user_story_blocks,
)
from slack_bot.hub import HubClient, HubError
from slack_bot.sessions import AgentSession, RunRegistry
from slack_bot.streaming import LimitedStream

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
# conversations.replies: distributed apps outside the Slack Marketplace get at most 15 messages per
# call and 1 call per minute (since May 2025); internal apps get more, but 15 is plenty of context.
HISTORY_LIMIT = 15
HISTORY_CHARS = 6000
STOPPED_NOTE = "\n\n_Stopped._"
FEEDBACK_ACTION = "answer_feedback"


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
    "who owns that?" have context. Bounded to HISTORY_LIMIT messages and HISTORY_CHARS."""
    thread_ts = event.get("thread_ts")
    if not thread_ts:
        return []
    try:
        response = await client.conversations_replies(
            channel=channel, ts=thread_ts, limit=HISTORY_LIMIT
        )
    except SlackApiError as exc:
        error = exc.response.get("error")
        if error == "ratelimited":
            logger.info(
                "Thread history skipped: rate-limited (non-Marketplace distributed apps may call "
                "conversations.replies once per minute)"
            )
        else:  # e.g. missing_scope when the optional history scopes weren't granted
            logger.warning("Could not read thread history: %s", error)
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
    for turn in reversed(turns):  # keep the most recent within the budget
        size += len(turn[1])
        if size > HISTORY_CHARS:
            break
        kept.append(turn)
    return list(reversed(kept))


def feedback_blocks() -> list[dict[str, Any]]:
    """Thumbs up/down under every answer (Slack's feedback_buttons element)."""
    return [
        {
            "type": "context_actions",
            "elements": [
                {
                    "type": "feedback_buttons",
                    "action_id": FEEDBACK_ACTION,
                    "positive_button": {
                        "text": {"type": "plain_text", "text": "👍"},
                        "accessibility_label": "This answer was helpful",
                        "value": "positive",
                    },
                    "negative_button": {
                        "text": {"type": "plain_text", "text": "👎"},
                        "accessibility_label": "This answer was not helpful",
                        "value": "negative",
                    },
                }
            ],
        }
    ]


async def answer(
    event: dict[str, Any],
    bot_user_id: str | None,
    client: Any,
    agent: MeetingAgent,
    say_stream: Any,
    set_status: Any,
    runs: RunRegistry,
) -> None:
    """Answer a mention or DM in its thread: agent session status, streamed text with task cards
    for tool calls, a stop button (via agent_session_stopped), and feedback buttons."""
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    question = strip_mention(event.get("text", ""), bot_user_id)

    if not question:
        await client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=HELP_TEXT)
        return

    history = await thread_history(client, channel, event, bot_user_id)
    session = AgentSession(client, channel, thread_ts, set_status)
    await session.processing(title=question)
    stream = LimitedStream(say_stream, client, channel, thread_ts)
    runs.register(channel, thread_ts)
    try:
        async for update in agent.stream(question, history):
            if isinstance(update, ToolStarted):
                await stream.task(update.id, update.title, "in_progress")
            elif isinstance(update, ToolFinished):
                await stream.task(update.id, update.title, "complete" if update.ok else "error")
            elif isinstance(update, TextDelta):
                await stream.text(update.text)
    except asyncio.CancelledError:
        # The user clicked Slack's stop button (agent_session_stopped). Finish cleanly instead of
        # propagating, so the stream is closed and the session returns to "active".
        logger.info("Answer stopped by the user in %s/%s", channel, thread_ts)
        await stream.text(STOPPED_NOTE)
    except HubError as exc:
        logger.warning("Hub error while answering %r: %s", question, exc)
        await stream.text(f"\n\n:warning: I couldn't reach the meeting hub right now. ({exc})")
    except Exception:
        logger.exception("Agent failed while answering %r", question)
        await stream.text(
            "\n\n:warning: Something went wrong while answering. The error has been logged."
        )
    finally:
        runs.unregister(channel, thread_ts)
        await stream.finish(blocks=feedback_blocks())


async def stop_answer(event: dict[str, Any], client: Any, runs: RunRegistry) -> None:
    """Slack's native stop button was clicked (agent_session_stopped)."""
    channel, thread_ts = event["channel"], event["thread_ts"]
    if not runs.stop(channel, thread_ts):
        # Nothing running (already finished, or another instance): just leave "processing".
        await AgentSession(client, channel, thread_ts).active()


async def record_feedback(body: dict[str, Any], client: Any) -> None:
    action = body["actions"][0]
    user = body["user"]["id"]
    channel = body.get("channel", {}).get("id")
    message = body.get("message", {})
    logger.info("Answer feedback: %s from %s on %s", action.get("value"), user, message.get("ts"))
    if channel:
        await client.chat_postEphemeral(
            channel=channel,
            user=user,
            thread_ts=message.get("thread_ts") or message.get("ts"),
            text="Thanks for the feedback!",
        )


def is_user_dm(event: dict[str, Any]) -> bool:
    """A human's message in a DM with the bot (not edits, joins, or our own messages)."""
    return (
        event.get("channel_type") == "im"
        and not event.get("subtype")
        and not event.get("bot_id")
        and bool(event.get("text"))
    )


def register(app: AsyncApp, hub: HubClient, agent: MeetingAgent) -> None:
    runs = RunRegistry()

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
        await answer(event, context.bot_user_id, client, agent, say_stream, set_status, runs)

    @app.event("message")
    async def on_message(event, context, client, say_stream, set_status):
        # Direct messages to the agent (Agent messaging experience). Channel messages are ignored;
        # in channels the bot answers @mentions only.
        if is_user_dm(event):
            await answer(event, context.bot_user_id, client, agent, say_stream, set_status, runs)

    @app.event("agent_session_stopped")
    async def on_stopped(event, client):
        await stop_answer(event, client, runs)

    @app.action(FEEDBACK_ACTION)
    async def on_feedback(ack, body, client):
        await ack()
        await record_feedback(body, client)
