# Changelog

All notable changes to this project are documented here. Format:
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: [SemVer](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/brindeshwar/poc_slack/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/brindeshwar/poc_slack/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/brindeshwar/poc_slack/releases/tag/v0.1.0
