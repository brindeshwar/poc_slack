# Architecture: Slack Bot

## Context

A thin Slack adapter over the meeting hub. All meeting data, AI extraction and Jira writes live in
other services. This bot turns Slack events into hub tool calls and the results into Block Kit
messages. Contract: [`poc_mcp/docs/INTEGRATION.md`](https://github.com/brindeshwar/poc_mcp/blob/main/docs/INTEGRATION.md).

## Components

```
Slack ─(Socket Mode | HTTP+OAuth)─► Bolt AsyncApp ──► handlers.register()
                                                       ├─ /lastmeeting* ─► meeting_command ─► HubClient.call("get_latest_meeting")
                                                       ├─ /meetingtojira ─► jira_command   ─► HubClient.call("create_jira_tasks", dry_run?)
                                                       └─ app_mention    ─► answer_mention ─► MeetingAgent.run()
                                                                                                 │
                                         Gemini (function calling) ◄── tools from hub list_tools ┘
```

| Module | Responsibility |
|---|---|
| `app.py` | Composition root. Builds Bolt in Socket or HTTP+OAuth mode, wires `HubClient` and `MeetingAgent`, starts the server |
| `handlers.py` | Slack behaviour as plain async functions plus `register()` |
| `agent.py` | Streamed tool-calling loop. MCP tools → Gemini `FunctionDeclaration`s → stream a step → call tools → feed results back → repeat (≤ 6 steps). Yields `Status` and `TextDelta` events |
| `hub.py` | MCP client. One session per command, or one per agent run (reused across tool calls) |
| `formatting.py` | Block Kit for slash commands, escaping, truncation |
| `config.py` | Settings with per-mode validation |

## Flows

**Slash command** (`/lastmeetingsummary` etc.): `ack()` immediately → `get_latest_meeting` →
format → `respond(response_type="in_channel")`. Hub errors are sent back *ephemeral* (only the
caller sees them). `respond` uses the response URL, so the bot doesn't need to be in the channel.

**`/meetingtojira [preview]`**: `preview` → `dry_run=true`. Results show status, a ticket link, and
any assignee warnings.

**Mention or DM** (`handlers.answer`, streamed):
1. Strip the bot's own mention. An empty question gets the help text. DMs (`message.im`) take the same path
   via `is_user_dm`, which skips edits, joins and our own messages.
2. **Thread follow-ups:** in a thread, read earlier messages with `conversations.replies`, at most 15
   messages, the cap for non-Marketplace distributed apps. The text is limited to 6,000 characters, most
   recent kept. Bot messages become `model` turns, people's become `user` turns. A rate limit or missing
   optional scope just means no history.
3. **Agent session:** `agents.sessions.setStatus(processing, title=question)` gives Slack's native
   *Working…* UI and stop button. If the app isn't declared as an agent, this falls back once to Bolt's
   `set_status`, the legacy `assistant.threads.setStatus` call, which Slack keeps through its compatibility bridge.
4. `MeetingAgent.stream(question, history)` streams each Gemini step into a `LimitedStream` (Bolt's
   `say_stream`):
   - **text parts** → appended as Markdown immediately (thought parts are never shown);
   - **tool calls** → a `task_update` chunk (*Searching meetings* · in_progress → complete/error) around the
     hub call. Every part of the step, including Gemini 3 **thought signatures**, goes back into the
     conversation unchanged, and tool errors reach the model as `{"error": …}`.
5. `finish()` in `finally`: `chat.stopStream(session_status="active", blocks=[feedback buttons])`. A
   `HubError` appends a "couldn't reach the hub" line; other exceptions append a generic message (details
   are logged, never posted).

**Stop button:** the running answer registers its task in `RunRegistry` under (channel, thread). An
`agent_session_stopped` event cancels it. The answer catches the cancellation, appends *Stopped.* and still
closes the stream. If nothing is running, the session is simply set to `active`.

**Streaming limits** (`streaming.LimitedStream`): Slack allows 12,000 Markdown characters and 10 minutes per
streamed message. At about 11,000 characters the stream is stopped with `session_status="processing"` and a
new one continues in the same thread. `msg_too_long` triggers the same rollover, and
`message_not_in_streaming_state` (timeout) switches to `chat.postMessage`.

**Feedback:** `feedback_buttons` (action `answer_feedback`) are logged and acknowledged with an ephemeral
"Thanks".

## Why the agent discovers tools dynamically

The bot hardcodes no tool list for the agent, so a new hub tool becomes usable from Slack without a
bot release. The tool's docstring is what Gemini reads. Slash commands do hardcode their tool,
because their output format depends on the result shape.

## Modes

| | Socket Mode (default) | HTTP mode |
|---|---|---|
| Workspaces | one (token in `.env`) | many ("Add to Slack") |
| Public URL | not needed | needed (`/slack/events`, `/slack/install`, `/slack/oauth_redirect`) |
| Auth | `SLACK_BOT_TOKEN` + `SLACK_APP_TOKEN` | signing secret + client ID/secret; installs in `INSTALLATION_DIR` |

Scopes (both modes): `app_mentions:read`, `chat:write` (messages, streaming, sessions, status), `commands`,
`assistant:write` (added by Slack when the app is declared an agent), and the **optional** (`bot_optional`)
`channels:history` / `groups:history` (thread follow-ups) and `im:history` (DMs). See `manifest.yml`.

Socket Mode suits development and internal use. Slack recommends HTTP for production, and Socket Mode apps
can't be listed on the Marketplace, which is the only allowed channel for commercial distribution.

## Models

`gemini-3.5-flash-lite` with `thinking_level=low`: enough reasoning to choose tools reliably at
Flash-Lite cost and latency. The 2.5 models are closed to new projects.

## Changes from v1

v1 mixed a hand-written OAuth flow (never wired to the running bot) with a hardcoded token, passed
the signing secret as a literal string, `await`ed a synchronous Gemini call (every mention failed),
and answered slash commands from hardcoded sample data. See `CHANGELOG.md` 0.2.0.
