# Changelog

All notable changes to this project are documented here. Format:
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: [SemVer](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-10-13

### Added
- **Streaming answers:** mentions stream the agent's answer into the thread with Slack's native chat
  streaming, with a status line ("Searching meetings…", "Talking to Jira…") while tools run.
- **Thread follow-ups:** mentions inside a thread include up to 20 earlier messages as context.

### Changed
- Default model is `gemini-3.5-flash-lite` with `GEMINI_THINKING_LEVEL` (default `low`). The 2.5
  models are closed to new projects.
- **BREAKING (Slack app config):** new bot scopes `channels:history`, `groups:history` and
  `assistant:write`. Apply `manifest.yml` and reinstall.
- The placeholder-then-edit flow and the Markdown→mrkdwn converter are removed; streaming renders
  Markdown natively.
- Python 3.14 added to CI; the Docker image uses Python 3.14.
- Upgraded to `mcp` 2.x: `HubClient` uses the high-level `mcp.Client`; result and tool fields are
  snake_case (`is_error`, `structured_content`, `input_schema`). No behaviour change.
- Upgraded `google-genai` to 2.x (its breaking changes only affect the Interactions API, which isn't used).
- CI actions moved to their Node 24 versions (`checkout@v7`, `setup-uv@v7`, `setup-buildx-action@v4`,
  `build-push-action@v7`, `gitleaks-action@v3`). Node 20 was removed from GitHub-hosted runners.

## [0.2.0] - 2026-10-13

Full rewrite as a client of the ListenLoom meeting hub (MCP).

### Added
- `@mention` answers from a Gemini agent that calls the hub's MCP tools (discovered at runtime),
  shown as a placeholder that is updated in the thread.
- `/meetingtojira [preview]` creates or previews Jira tasks for the latest meeting.
- HTTP mode with Bolt's built-in "Add to Slack" OAuth (multi-workspace); Socket Mode remains the
  default.
- `manifest.yml` for creating the Slack app, plus tests, CI, pre-commit with gitleaks, Dependabot,
  Dockerfile, and contributor and agent documentation.

### Changed
- **BREAKING:** slash commands now read real meetings from the hub. Requires a running hub
  (`MCP_SERVER_URL`).
- **BREAKING:** required bot scopes are `app_mentions:read`, `chat:write`, `commands`. Update the
  app from `manifest.yml` and reinstall.
- Slash command responses use `respond()` (response URL), so the bot doesn't need to be in the channel.
- Dependencies managed with uv (`pyproject.toml` + `uv.lock`).

### Fixed
- Every mention failed: a synchronous Gemini call was `await`ed (and used the retired `gemini-pro`).
- The signing secret was the literal string `"SLACK_SIGNING_SECRET"`.
- The custom OAuth flow was never connected to the running bot.
- Raw exception text was posted into channels.

### Security
- Gitleaks in pre-commit and CI. See `SECURITY.md` about tokens in early git history (rotate them).

## [0.1.0] - 2025-07-06

- Initial internship proof of concept.

[Unreleased]: https://github.com/brindeshwar/poc_slack/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/brindeshwar/poc_slack/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/brindeshwar/poc_slack/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/brindeshwar/poc_slack/releases/tag/v0.1.0
