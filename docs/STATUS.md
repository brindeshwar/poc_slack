# Project Status: Slack Bot

> Living document. Update it at the end of every work session (`AGENTS.md` §6). Newest handoff on top.

## Health

| Check | State | As of |
|---|---|---|
| Tests (agent sessions, task cards, stop button, stream limits, DMs, feedback, Bolt wiring, history limits) | ✅ 40 passing | 2026-11-05 |
| Lint / format | ✅ clean | 2026-10-13 |
| MCP client ↔ live hub (list tools, tool errors, outage) | ✅ verified | 2026-10-13 |
| Bolt app builds in HTTP mode; config validation | ✅ verified | 2026-10-13 |
| Real Slack workspace (Socket Mode, streaming) | ⛔ not verified: tokens need rotating; apply the v0.3 manifest scopes | 2026-10-13 |
| Gemini agent live | ⛔ not verified: Gemini key invalid | 2026-10-13 |
| Docker image | ✅ builds in CI (`Docker build` job, required check) | 2026-10-13 |

## Current version

`0.2.0`, released 2026-10-13 (tag `v0.2.0`, GitHub release).

## Known issues / blockers

1. **Leaked tokens in git history.** v1 commits contain `installations/` (bot tokens) and a
   `.env`. Rotate the bot token, app token, client secret and signing secret in the Slack app settings.
   Optionally purge the history with `git filter-repo`.
2. **Slack app config must be updated.** Apply the new `manifest.yml`, which declares the app as an agent
   (`agent_view`), subscribes to `message.im` and `agent_session_stopped`, enables interactivity, and marks the
   history scopes optional. Then reinstall the app.
3. Gemini key invalid (shared with the other repos).

## Backlog (prioritized)

| # | Item | Notes |
|---|---|---|
| 1 | Live test in a dev workspace | slash commands, mention, `/meetingtojira preview` |
| 2 | Upload a transcript file to ingest a meeting | `files:read` scope + `ingest_meeting` |
| 3 | Persistent installation store for HTTP mode (DB instead of files) | needed for multi-instance deploys |

## Decision log

| Date | Decision | Why |
|---|---|---|
| 2026-10-13 | Bot is a pure MCP client of the hub | single data owner; no duplicated logic |
| 2026-10-13 | Agent discovers tools at runtime | new hub tools reach Slack without a bot release |
| 2026-10-13 | Bolt's built-in OAuth instead of a custom flow | v1's custom flow was never wired; less code, maintained upstream |
| 2026-10-13 | Placeholder message + `chat_update` for mentions (superseded below) | instant feedback; agent runs can take seconds |
| 2026-10-13 | Slash command results `in_channel`, errors `ephemeral` | share useful output; don't spam errors |
| 2026-10-13 | Protect `main`: PR + required checks (5, then 6 with Python 3.14), linear history, rebase-only merges, 0 approvals | keeps `main` always green; linear history keeps the Conventional Commits readable; solo maintainer can't self-approve |
| 2026-10-13 | v0.3: native chat streaming + `set_status` instead of placeholder/edit | tokens appear as generated; Slack-native AI UX; no Markdown→mrkdwn conversion needed |
| 2026-10-13 | v0.3: thread history (≤ 20 msgs / 6k chars) passed as turns | follow-ups work; bounded cost |
| 2026-10-13 | v0.3: `gemini-3.5-flash-lite`, thinking `low` | 2.5 closed to new projects; tool choice needs a little reasoning |
| 2026-11-05 | Agent Sessions API (`agents.sessions.setStatus`) with legacy fallback | `assistant.threads.*` is being replaced and assistant_view is deprecated in February 2027; sessions give a native stop button; the fallback keeps it working before the app is declared an agent |
| 2026-11-05 | Declare the app as an agent (`agent_view`) and answer DMs | required for sessions; new apps can only use agent_view; DMs come for free with the same answer path |
| 2026-11-05 | Task cards for tool calls instead of a status-line string | Slack's native way to show agent steps; `agents.sessions.setStatus` has no custom loading text |
| 2026-11-05 | Roll streams over before 12,000 chars; fall back to postMessage after the 10-minute timeout | documented hard limits; long answers must not fail |
| 2026-11-05 | History capped at 15 messages, `ratelimited` → no history | non-Marketplace distributed apps: 1 call per minute, 15 messages (May 2025) |

## Handoff log

### 2026-11-05: Claude (Opus 5.5) · Slack platform update (Nov 2026 docs)
**Changed:** after reviewing Slack's changelog since May 2025 and the current reference docs:
- `agents.sessions.setStatus` with a fallback to legacy `set_status`;
- a stop button (`agent_session_stopped` → `RunRegistry` cancels the answer);
- task cards for tool calls;
- `LimitedStream` (12k/10-minute limits);
- feedback buttons;
- DM answers (`message.im`);
- thread history capped at 15 with `ratelimited` handling;
- hub bearer token (`MCP_AUTH_TOKEN`);
- manifest: `agent_view`, `bot_optional` history scopes, new events, interactivity, and a commented
  `mcp_servers` block for the Slackbot MCP client;
- slack-sdk 3.46.

**Verified:** 40 tests, including real Bolt dispatch with the Web API faked at HTTP level (DM → session →
startStream → stopStream; stop event; feedback action); the manifest checked field by field against Slack's
manifest reference; live: HubClient with token against an auth-enabled hub (7 tools with titles; a wrong or
missing token gives a clear error).

**Not verified:** a real Slack workspace (agent declaration, sessions, stop button and streaming in channels
need the updated app and a paid or Developer Program sandbox workspace).

**Next agent:** apply the manifest, reinstall, and test: a mention in a channel, a DM, the stop button
mid-answer, a thread follow-up, and feedback.

### 2026-10-13: Claude (Opus 5.5) · v0.3.0 streaming + thread follow-ups
**Changed:** `MeetingAgent.stream()` streams Gemini steps (`generate_content_stream`), yielding `Status`
before tool calls and `TextDelta`s, and preserving every part (Gemini 3 thought signatures). Mentions now
use Bolt's `say_stream` + `set_status` (the placeholder/`chat_update` flow and the Markdown→mrkdwn
converter are removed). Thread follow-ups read up to 20 earlier messages. Model → `gemini-3.5-flash-lite`
(thinking `low`). New scopes in the manifest/OAuth. Python 3.14 in CI/Docker.

**Verified:** 25 tests (stream order, status before tools, thought-signature round trip, history
turns and budget, stream always stopped, status failures harmless, missing scope); ruff; HTTP-mode
app builds.

**Not verified:** against real Slack (streaming in channels, `assistant.threads.setStatus` outside the
assistant panel) and real Gemini.

**Next agent:** after rotating tokens and applying the manifest, test a mention in a channel and a
follow-up in its thread. If `set_status` returns an error outside assistant threads, it is already
ignored; consider removing it.

### 2026-10-13: Claude (Opus 5.5) · dependency upgrades (Dependabot triage)
**Changed:** migrated `HubClient`/agent to `mcp` 2.3 (`mcp.Client`, snake_case fields) and `google-genai` 2.x. CI actions moved to their Node 24 majors.

**Verified:** release notes reviewed for every major bump; pytest (19); live: HubClient against the hub running mcp 2.3 (tool listing, Gemini declarations from `input_schema`, tool errors, outage).

**Next agent:** Dependabot's superseded PRs close automatically after merge. Future major bumps need the
same review (CI alone isn't enough where tests use fakes, e.g. Gemini).

### 2026-10-13: Claude (Opus 5.5) · v0.2.0 released, branch protection
**Changed:** merged the v2 PR (rebase), tagged `v0.1.0` (original POC) and `v0.2.0`, and published the
GitHub release. Protected `main`: PR required, 5 required checks (lint, tests 3.12/3.13, secret scan,
Docker build) that must be up to date, linear history, conversation resolution, no force-push or
deletion, enforced for admins. 0 approvals required (solo maintainer; GitHub forbids self-approval).
Rebase merge is the only merge method; merged branches are auto-deleted.

**Verified:** CI green on the PR and on `main` after merge; protection settings read back from the
GitHub API.

**Next agent:** unchanged. Live verification is blocked on a valid Gemini key (and Jira site / Slack
token rotation; see Known issues). All changes now go through a PR.

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
