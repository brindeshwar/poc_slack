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
| Docker image | ✅ builds in CI (`Docker build` job, required check) | 2026-10-13 |

## Current version

`0.2.0`, released 2026-10-13 (tag `v0.2.0`, GitHub release).

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
| 2026-10-13 | Protect `main`: PR + 5 required checks, linear history, rebase-only merges, 0 approvals | keeps `main` always green; linear history keeps the Conventional Commits readable; solo maintainer can't self-approve |

## Handoff log

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
