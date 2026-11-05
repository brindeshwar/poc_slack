# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue. Use GitHub's private
[security advisory form](../../security/advisories/new) or email the maintainer.

## Supported versions

Only the latest release on `main` receives fixes.

## Known historical exposure

Early v1 commits in this repository contained Slack OAuth installation files (bot tokens) and a
`.env` file. **Every credential from that period must be considered compromised and rotated:** bot
token, app-level token, client secret and signing secret (Slack app settings → *Basic Information* /
*OAuth & Permissions*). Rewriting history (`git filter-repo --path installations --path first-bolt-app/.env --invert-paths`
plus a force push) removes the files, but it does **not** replace rotation, because forks and clones
may already have them.

## Handling secrets

- Secrets live only in `.env` (gitignored) or a deployment secret store. `.env.example` lists
  names only.
- `installations/` holds OAuth installs with bot tokens and is gitignored. Never commit it.
- `gitleaks` runs in pre-commit and CI.
- The bot never posts raw exception text from unexpected errors to Slack, since it could include
  internal details. Details go to logs only.
- If a secret is committed, rotate it first, then clean the history.

## Slack data and third parties

Slack's API Terms (May and October 2025) restrict how apps store, use and share data from Slack APIs:

- **The bot stores nothing from Slack.** It reads up to 15 earlier messages of a thread only to answer the
  current question, and sends them to the configured LLM (Google Gemini) as part of that request.
- **Use a paid Gemini tier**, or keep the bot internal to your own workspace. On the Gemini API's free tier,
  Google may use prompts to improve its products, which isn't appropriate for other organisations' Slack
  data.
- **Commercial distribution** of a Slack app is only allowed through the Slack Marketplace.
