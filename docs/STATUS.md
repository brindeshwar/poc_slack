# Project Status: Slack Bot

> Living document. Update it at the end of every work session (`AGENTS.md` §6). Newest handoff on top.

## Health

| Check | State | As of |
|---|---|---|
| Tests (handlers, agent loop, formatting) | ✅ 19 passing | 2026-10-13 |
| Lint / format | ✅ clean | 2026-10-13 |
| MCP client ↔ live hub (list tools, tool errors, outage) | ✅ verified | 2026-10-13 |
| Bolt app builds in HTTP mode; config validation | ✅ verified | 2026-10-13 |
| Real Slack workspace (Socket Mode) | ⛔ not verified: tokens need rotating; app needs `chat:write` + `commands` | 2026-10-13 |
| Gemini agent live | ⛔ not verified: Gemini key invalid | 2026-10-13 |
| Docker image | ⚠️ not built locally (Docker daemon not running); CI `docker` job builds it | 2026-10-13 |

## Current version

`0.2.0` (unreleased; branch `refactor/v2-connected-system`).

## Known issues / blockers

1. **Leaked tokens in git history.** v1 commits contain `installations/` (bot tokens) and a
   `.env`. Rotate the bot token, app token, client secret and signing secret in the Slack app settings.
   Optionally purge the history with `git filter-repo`.
2. **Slack app config must be updated.** Apply `manifest.yml` (v1 requested `assistant:write` and
   `incoming-webhook` but lacked `chat:write`/`commands`), then reinstall the app to the workspace.
3. Gemini key invalid (shared with the other repos).

## Backlog (prioritized)

| # | Item | Notes |
|---|---|---|
| 1 | Live test in a dev workspace | slash commands, mention, `/meetingtojira preview` |
| 2 | Thread context for mentions | pass earlier thread messages to the agent for follow-ups |
| 3 | Confirmation button before creating Jira tickets from a mention | Block Kit interactivity; needs `interactivity` in the manifest |
| 4 | Upload a transcript file to ingest a meeting | `files:read` scope + `ingest_meeting` |
| 5 | Persistent installation store for HTTP mode (DB instead of files) | needed for multi-instance deploys |

## Decision log

| Date | Decision | Why |
|---|---|---|
| 2026-10-13 | Bot is a pure MCP client of the hub | single data owner; no duplicated logic |
| 2026-10-13 | Agent discovers tools at runtime | new hub tools reach Slack without a bot release |
| 2026-10-13 | Bolt's built-in OAuth instead of a custom flow | v1's custom flow was never wired; less code, maintained upstream |
| 2026-10-13 | Placeholder message + `chat_update` for mentions | instant feedback; agent runs can take seconds |
| 2026-10-13 | Slash command results `in_channel`, errors `ephemeral` | share useful output; don't spam errors |

## Handoff log

### 2026-10-13: Claude (Opus 5.5) · v2 rebuild + project infrastructure
**Changed:** removed the v1 code (`slack_logic.py`, `data_store.py`, `requirements.txt`); rewrote the bot into `src/slack_bot` (MCP client, Gemini agent, Bolt OAuth, Block Kit).
Added `/meetingtojira`, `manifest.yml`, tests, and project infrastructure (AGENTS/CLAUDE/docs, CI,
pre-commit + gitleaks, Dependabot, templates, Dockerfile, MIT license, CHANGELOG).

**Verified:** 19 tests; ruff; HubClient against the live hub (tool list, Gemini declarations build
from real MCP schemas, tool errors, body exceptions propagate, outage → HubError); HTTP-mode app
construction.

**Not verified:** real Slack, real Gemini.

**Next agent:** once tokens are rotated and the manifest is applied, do Backlog #1 and record the
results here.
