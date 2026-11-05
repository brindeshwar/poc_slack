# ListenLoom Slack Bot

[![CI](https://github.com/brindeshwar/poc_slack/actions/workflows/ci.yml/badge.svg)](https://github.com/brindeshwar/poc_slack/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A Slack front end for the ListenLoom meeting hub. It has no data or business logic of its own:
everything goes through the hub's MCP tools, so Slack, the Streamlit UI and any MCP client (Claude
Desktop, an IDE, …) all see the same meetings.

```
Slack ──► this bot ──MCP (HTTP)──► Meeting hub ──► MongoDB Atlas
                                        └──HTTP──► Jira Task Service ──► Jira Cloud
```

## What it does

| In Slack | What happens |
|---|---|
| `@ListenLoom who owns the rollback plan?` | A Gemini agent picks hub tools (`ask_meetings`, `get_latest_meeting`, …), calls them, and answers in the thread |
| A direct message to ListenLoom | Same agent, in the app's Messages tab (Slack's Agent messaging experience), replying in a thread |
| `@ListenLoom create Jira tasks for the last meeting` | The agent calls `create_jira_tasks` (it only does this when explicitly asked) |
| `/lastmeetingsummary` | Summary of the most recent meeting |
| `/lastmeetingtodo` | Action items with owner and due date |
| `/lastmeetinguserstory` | User stories that came up |
| `/meetingtojira [preview]` | Create (or preview) Jira tasks for the latest meeting's action items |

Answers use Slack's current agent features (November 2026 platform):

- **Agent session status:** Slack's native *Working…* indicator, with a **stop button** that really
  cancels the answer.
- **Streamed answers** that appear as they're generated. Each tool call shows as a **task card**
  ("Searching meetings" → complete / error).
- **Feedback buttons** (👍 / 👎) under every answer.
- **Thread follow-ups:** in a thread, the bot reads the earlier messages, so "and who owns that?" works.

Errors are shown as friendly messages, and details go to the log, not the channel. Model:
`gemini-3.5-flash-lite`.

> **Slackbot can also use the meeting hub directly**, through Slack's Slackbot MCP client. See the hub
> README, *Use it from Slackbot*. The commented `mcp_servers` block in `manifest.yml` is ready for it.

## Setup

1. **Create the Slack app** from [`manifest.yml`](manifest.yml): <https://api.slack.com/apps> → *Create
   New App* → *From a manifest*. It declares the app as an **agent** (`agent_view`), and sets:
   - scopes: `app_mentions:read`, `chat:write`, `commands`; `assistant:write`, which Slack adds for agents;
     and the optional `channels:history`, `groups:history`, `im:history`;
   - the slash commands;
   - the events `app_mention`, `message.im` and `agent_session_stopped`;
   - interactivity, for the feedback buttons.

   Some Slack AI features need a paid plan. The free [Slack Developer Program](https://api.slack.com/developer-program)
   sandbox has them.
2. **Pick a mode:**
   - **Socket mode** (default, no public URL): install the app to your workspace, then copy the Bot
     token (`xoxb-…`) and create an App-level token with `connections:write` (`xapp-…`).
   - **HTTP mode** ("Add to Slack"): set `socket_mode_enabled: false` in the manifest,
     point the URLs at your public host (e.g. ngrok), and use the client ID, client secret and signing
     secret. Users install via `https://<host>/slack/install`. Installations are stored under
     `./installations/` (gitignored).
   - **Distribution rules:** Slack's API terms (2025) make the **Slack Marketplace the only channel for
     commercial distribution**, and Socket Mode apps can't be listed there. Apps installed on other
     workspaces without a Marketplace listing get a strict `conversations.replies` limit: 1 call per minute,
     15 messages. The bot already requests at most 15 and skips history when rate-limited. Internal apps,
     installed only in your own workspace, aren't affected.
3. **Configure and run** (requires [uv](https://docs.astral.sh/uv/), Python 3.12+, and the meeting hub
   running):

```bash
cp .env.example .env
uv sync
uv run slack-bot
```

## Tests

```bash
uv run pytest      # fakes for Slack, the hub and Gemini; no network or credentials
uv run ruff check .
```

## Layout

```
src/slack_bot/
  app.py         builds the Bolt app (socket or HTTP+OAuth) and starts it
  handlers.py    slash commands + @mention logic (plain functions, unit-tested)
  sessions.py    agent session status + stop-button cancellation
  streaming.py   streamed answers with task cards, respecting Slack's limits
  agent.py       streamed Gemini function calling over the hub's MCP tools
  hub.py         MCP client for the meeting hub
  formatting.py  Block Kit builders for slash commands
  config.py      settings from environment / .env
manifest.yml     Slack app definition
```

## Docker

```bash
docker build -t listenloom-slack .
docker run --env-file .env -e MCP_SERVER_URL=http://host.docker.internal:8001/mcp listenloom-slack
```

For the whole stack, use `poc_mcp/deploy/docker-compose.yml --profile slack`.

## Documentation

| Doc | For |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Rules and commands for coding agents and contributors (`CLAUDE.md` imports it) |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Components, flows, modes |
| [`docs/STATUS.md`](docs/STATUS.md) | Health, known issues, backlog, decisions, handoff log |
| [Integration contract](https://github.com/brindeshwar/poc_mcp/blob/main/docs/INTEGRATION.md) | Tools and result shapes this bot relies on (lives in the hub repo) |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) · [`SECURITY.md`](SECURITY.md) · [`CHANGELOG.md`](CHANGELOG.md) | Process |

## License

[MIT](LICENSE) © Brindeshwar Sharma
