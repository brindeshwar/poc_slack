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

**Mention** (streamed):
1. Strip the bot's own mention. An empty question gets the help text.
2. **Thread follow-ups:** if the mention is inside a thread, read earlier messages with
   `conversations.replies` (≤ 20 messages, ≤ 6,000 chars, most recent kept). Bot messages become `model`
   turns and people's messages become `user` turns. A missing `channels:history` scope just means no history.
3. `set_status("Thinking…")`, then open Bolt's `say_stream()` (`chat.startStream` in the thread,
   addressed to the asking user).
4. `MeetingAgent.stream(question, history)` opens one MCP session and streams each Gemini step:
   - **text parts** → `stream.append(markdown_text=…)` immediately (thought parts are never shown);
   - **function calls** → `set_status("Searching meetings…")` etc., then call the hub tool. Every part
     of the step, including Gemini 3 **thought signatures**, goes back into the conversation unchanged.
     Tool errors are passed to the model as `{"error": …}`.
5. `stream.stop()` in `finally`. A `HubError` appends a "couldn't reach the hub" line; any other exception
   appends a generic message (details are logged, never posted).

Status updates use `assistant.threads.setStatus` (`assistant:write`). If that fails, the answer still
streams.

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

Scopes (both modes): `app_mentions:read`, `chat:write` (incl. streaming), `commands`,
`channels:history` + `groups:history` (thread follow-ups), `assistant:write` (status line). See `manifest.yml`.

## Models

`gemini-3.5-flash-lite` with `thinking_level=low`: enough reasoning to choose tools reliably at
Flash-Lite cost and latency. The 2.5 models are closed to new projects.

## Changes from v1

v1 mixed a hand-written OAuth flow (never wired to the running bot) with a hardcoded token, passed
the signing secret as a literal string, `await`ed a synchronous Gemini call (every mention failed),
and answered slash commands from hardcoded sample data. See `CHANGELOG.md` 0.2.0.
