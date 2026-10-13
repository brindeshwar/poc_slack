"""Turn hub results into Slack Block Kit messages."""

from typing import Any

SECTION_LIMIT = 2900  # Slack rejects section text over 3000 characters


def section(text: str) -> dict[str, Any]:
    if len(text) > SECTION_LIMIT:
        text = text[: SECTION_LIMIT - 1] + "…"
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def context(text: str) -> dict[str, Any]:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def escape(text: str) -> str:
    """Slack treats &, < and > as control characters in mrkdwn."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def meeting_header(meeting: dict[str, Any]) -> str:
    return f"{escape(meeting['title'])} · {meeting['held_at'][:10]}"


def summary_blocks(meeting: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        section(f"*Summary: {meeting_header(meeting)}*"),
        section(escape(meeting["summary"])),
    ]


def todo_blocks(meeting: dict[str, Any]) -> list[dict[str, Any]]:
    items = meeting["action_items"]
    if not items:
        return [
            section(f"*Action items: {meeting_header(meeting)}*\nNo action items were recorded.")
        ]
    lines = []
    for item in items:
        details = [item.get("assignee") or "unassigned"]
        if item.get("due_date"):
            details.append(f"due {item['due_date']}")
        lines.append(f"• {escape(item['summary'])} _({escape(', '.join(details))})_")
    return [
        section(f"*Action items: {meeting_header(meeting)}*"),
        section("\n".join(lines)),
        context("Use `/meetingtojira` to turn these into Jira tasks."),
    ]


def user_story_blocks(meeting: dict[str, Any]) -> list[dict[str, Any]]:
    stories = meeting["user_stories"]
    body = "\n".join(f"• {escape(s)}" for s in stories) or "No user stories came up."
    return [section(f"*User stories: {meeting_header(meeting)}*"), section(body)]


STATUS_LABELS = {
    "created": "Created",
    "updated": "Updated",
    "would_create": "Would create",
    "would_update": "Would update",
    "failed": "Failed",
}


def jira_blocks(result: dict[str, Any]) -> list[dict[str, Any]]:
    lines = []
    for row in result["results"]:
        label = STATUS_LABELS.get(row["status"], row["status"])
        key = f" <{row['jira_url']}|{row['jira_key']}>" if row.get("jira_url") else ""
        line = f"• *{label}*{key} {escape(row['summary'])}"
        if row.get("message"):
            line += f"\n   _{escape(row['message'])}_"
        for warning in row.get("warnings", []):
            line += f"\n   :warning: {escape(warning)}"
        lines.append(line)
    blocks = [section(f"*Jira:* {escape(result['message'])}")]
    if lines:
        blocks.append(section("\n".join(lines)))
    return blocks
