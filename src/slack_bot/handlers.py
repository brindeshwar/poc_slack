"""Slack listeners. The logic lives in plain async functions so it can be tested without Slack."""

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from slack_bolt.async_app import AsyncApp

from slack_bot.agent import MeetingAgent
from slack_bot.formatting import (
    jira_blocks,
    markdown_to_mrkdwn,
    section,
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
THINKING_TEXT = ":hourglass_flowing_sand: Looking through your meetings…"


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


async def answer_mention(
    event: dict[str, Any], bot_user_id: str | None, client: Any, agent: MeetingAgent
) -> None:
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    question = strip_mention(event.get("text", ""), bot_user_id)

    if not question:
        await client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=HELP_TEXT)
        return

    placeholder = await client.chat_postMessage(
        channel=channel, thread_ts=thread_ts, text=THINKING_TEXT
    )
    try:
        reply = await agent.run(question)
        text = markdown_to_mrkdwn(reply.text)
    except HubError as exc:
        logger.warning("Hub error while answering %r: %s", question, exc)
        text = f":warning: I couldn't reach the meeting hub right now. ({exc})"
    except Exception:
        logger.exception("Agent failed while answering %r", question)
        text = ":warning: Something went wrong while answering. The error has been logged."
    await client.chat_update(
        channel=channel, ts=placeholder["ts"], text=text, blocks=[section(text)]
    )


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
    async def on_mention(event, context, client):
        await answer_mention(event, context.bot_user_id, client, agent)
