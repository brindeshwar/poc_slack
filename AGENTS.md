# AGENTS.md: ListenLoom Slack Bot

Instructions for **any** coding agent (Claude Code, Codex, Cursor, Copilot, Gemini CLI, Aider, …) and
for humans. This file is the source of truth for working in this repo. `CLAUDE.md` only adds to it.

## 1. What this repo is

The Slack front end of a three-repo system. It has **no data of its own**: every answer comes from the
meeting hub's MCP tools.

```
Slack ──► poc_slack (THIS REPO) ──MCP──► poc_mcp (meeting hub) ──► MongoDB Atlas
                                                 └──HTTP──► poc_jira (Jira Task Service) ──► Jira Cloud
```

| Repo | Local path | Role |
|---|---|---|
| `poc_slack` | `../poc_slack` | Slack bot (this repo); MCP client |
| `poc_mcp` | `../poc_mcp` | MCP hub. **Owns the integration contract:** `../poc_mcp/docs/INTEGRATION.md` |
| `poc_jira` | `../poc_jira/jira_task_creator` | Jira Task Service (the bot never calls it directly) |

Read next: `docs/ARCHITECTURE.md` (how the bot works), `docs/STATUS.md` (state, backlog,
**handoff log**), and the hub's `docs/INTEGRATION.md` (tool names, arguments and result shapes this
bot relies on).

## 2. Commands

| Task | Command |
|---|---|
| Install | `uv sync` |
| Run | `uv run slack-bot` (needs the hub running and `.env` filled in) |
| Tests | `uv run pytest` |
| Lint / format | `uv run ruff check .` / `uv run ruff format .` |
| Pre-commit | `uv run pre-commit run --all-files` |
| Docker | `docker build -t listenloom-slack .` (full stack: `poc_mcp/deploy/docker-compose.yml --profile slack`) |

**Definition of done:** `uv run ruff format . && uv run ruff check . && uv run pytest` passes.

## 3. Repo map

```
src/slack_bot/
  app.py         build_bolt_app(settings): Socket Mode (single token) or HTTP + Bolt OAuth; main()
  handlers.py    meeting_command / jira_command / answer_mention: plain async functions; register() wires Bolt
  agent.py       MeetingAgent.stream(): streamed Gemini function calling over the hub's MCP tools (max 6 steps)
  hub.py         HubClient: MCP Streamable HTTP client; HubError for tool errors and outages
  formatting.py  Block Kit builders for slash commands, mrkdwn escaping, truncation
  config.py      Settings: the ONLY place env vars are read; validates per-mode requirements
tests/           conftest.py (FakeHub, Recorder); tests for handlers, agent, formatting
manifest.yml     Slack app definition (scopes, slash commands, events). Keep it in sync with handlers.py
```

## 4. Rules

- **Keep handlers thin and testable.** Logic goes in plain functions (`meeting_command`, …) that take
  `respond`/`client`/`hub`/`agent` as arguments. `register()` only adapts Bolt's signature.
- **No business logic here.** If you need data the hub doesn't expose, add a tool to the hub (see
  its `docs/ARCHITECTURE.md` → Extending) rather than reaching into MongoDB or Jira from the bot.
- **Contract:** this bot relies on the tool names and result fields listed in the hub's
  `INTEGRATION.md` (`get_latest_meeting` → `title`, `held_at`, `summary`, `action_items`,
  `user_stories`; `create_jira_tasks` → `message`, `results[]`). If they change, update
  `formatting.py`/`handlers.py` and the tests together.
- **Agent safety:** the system prompt only allows `create_jira_tasks` on an explicit request and
  prefers `dry_run` for "what would…" questions. Keep that guarantee if you edit `SYSTEM_PROMPT`.
- **User-facing errors:** friendly text in Slack, details in logs. Never post stack traces or raw
  exception text from unexpected errors into a channel.
- **Streaming:** mentions answer via Bolt's `say_stream` (chat streaming, Markdown) with `set_status`
  updates between tool calls. Always `stop()` the stream (the handler does it in `finally`). Status
  failures must never break an answer.
- **Gemini 3 thought signatures:** `MeetingAgent.stream` appends every streamed part back to the
  conversation unchanged. Don't filter or rebuild model parts, or multi-step tool calls break.
- **Model:** `GEMINI_MODEL` (default `gemini-3.5-flash-lite`) with `GEMINI_THINKING_LEVEL` (default
  `low`). Never hardcode model IDs elsewhere.
- **Slack limits:** section text ≤ 3000 chars (use `formatting.section`); escape `& < >` in
  user or LLM content with `formatting.escape`; ack slash commands immediately (Bolt requires
  < 3s).
- **New slash command:** add it in `handlers.py`, `manifest.yml`, the README table and the tests.
- **Tests:** no network. Use `FakeHub`, `Recorder`, and the scripted `FakeGemini` in
  `tests/test_agent.py`. Bug fixes include a regression test.
- **Secrets:** never commit `.env` or `installations/` (OAuth installs contain bot tokens).
  `gitleaks` runs in pre-commit and CI. Read config only via `config.Settings`.
- **Style:** Python 3.12+, type hints, ruff (line length 100), `logging` not `print`.

## 5. Workflow

**`main` is protected:** every change goes through a PR with green, up-to-date CI (lint, tests 3.12/3.13,
secret scan, Docker build) and is rebase-merged. Never push to `main` directly or force-push.

Branches `feat/…`, `fix/…`, `docs/…`, `chore/…`, `refactor/…`, `ci/…`. Conventional Commits. PRs use the
template and need green CI. User-visible changes go under `[Unreleased]` in `CHANGELOG.md`.

## 6. Handoff protocol (multi-agent)

1. **Start:** read `docs/STATUS.md` (known issues, backlog, latest handoff).
2. **Decisions:** add questionable or important choices to the Decision log.
3. **End:** add a dated Handoff entry at the top: what changed, how it was verified (fakes vs. real
   Slack), what's unfinished, what to do next. Update Health and Backlog.

## 7. Gotchas

- Socket Mode sets `request_verification_enabled=False` on purpose: the app-level token
  authenticates the connection, and there are no signed HTTP requests to verify.
- In HTTP mode, Bolt's built-in OAuth serves `/slack/install` and `/slack/oauth_redirect`.
  Installations and state go to `INSTALLATION_DIR` (default `./installations`, gitignored).
- `context.bot_user_id` is used to strip the bot mention. Other user mentions in the question are
  kept.
- `HubClient.connect()` turns connection failures into `HubError`, but exceptions raised by *your*
  code inside the `async with` block propagate unchanged. Don't break that (there's a test for it).
- This repo's **git history contains old Slack tokens** (v1 committed `installations/` and a `.env`).
  They must be rotated; see `SECURITY.md`.
