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
| `agent.py` | Tool-calling loop. MCP tools → Gemini `FunctionDeclaration`s → call → feed results back → repeat (≤ 6 steps) |
| `hub.py` | MCP client. One session per command, or one per agent run (reused across tool calls) |
| `formatting.py` | Block Kit, escaping, truncation, Markdown → mrkdwn |
| `config.py` | Settings with per-mode validation |

## Flows

**Slash command** (`/lastmeetingsummary` etc.): `ack()` immediately → `get_latest_meeting` →
format → `respond(response_type="in_channel")`. Hub errors are sent back *ephemeral* (only the
caller sees them). `respond` uses the response URL, so the bot doesn't need to be in the channel.

**`/meetingtojira [preview]`**: `preview` → `dry_run=true`. Results show status, a ticket link, and
any assignee warnings.

**Mention:**
1. Strip the bot's own mention. An empty question gets the help text.
2. Post a "Looking through your meetings…" placeholder in the thread (`thread_ts` = existing thread
   or the message itself).
3. `MeetingAgent.run(question)` opens one MCP session, lists the tools, and loops with Gemini.
   Tool errors are passed to the model as `{"error": …}` so it can explain or retry.
4. Convert Markdown to mrkdwn and `chat_update` the placeholder with the answer. A `HubError` gives
   a "couldn't reach the hub" message; any other exception gives a generic message (details are
   logged).

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

Scopes (both modes): `app_mentions:read`, `chat:write`, `commands`. See `manifest.yml`.

## Changes from v1

v1 mixed a hand-written OAuth flow (never wired to the running bot) with a hardcoded token, passed
the signing secret as a literal string, `await`ed a synchronous Gemini call (every mention failed),
and answered slash commands from hardcoded sample data. See `CHANGELOG.md` 0.2.0.
