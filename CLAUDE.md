# CLAUDE.md

@AGENTS.md

## Claude Code specifics

- `AGENTS.md` (imported above) holds the shared rules. Add anything that applies to every agent
  there; this file is only for Claude-specific workflow.
- The hub repo is at `../poc_mcp`. Read `../poc_mcp/docs/INTEGRATION.md` before changing how
  results are formatted or which tools are called. Use plan mode for changes that span repos.
- Never post to a real Slack workspace or call `create_jira_tasks` without `dry_run` while testing.
  The unit tests use fakes for both.
- Before finishing: `uv run ruff format . && uv run ruff check . && uv run pytest`, report the real
  result, then add a Handoff entry to `docs/STATUS.md`.
