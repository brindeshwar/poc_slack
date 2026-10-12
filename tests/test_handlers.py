from slack_bot.agent import AgentReply
from slack_bot.handlers import (
    HELP_TEXT,
    THINKING_TEXT,
    answer_mention,
    jira_command,
    meeting_command,
    strip_mention,
)
from slack_bot.hub import HubError
from tests.conftest import MEETING, FakeHub


async def test_summary_command_posts_latest_meeting(recorder):
    hub = FakeHub({"get_latest_meeting": MEETING})
    await meeting_command("/lastmeetingsummary", recorder, hub)

    [(_, kwargs)] = recorder.calls
    assert kwargs["response_type"] == "in_channel"
    texts = [b["text"]["text"] for b in kwargs["blocks"]]
    assert "Eng sync · 2025-07-02" in texts[0]
    assert "&lt;Atlas&gt; migration &amp; rollback" in texts[1]


async def test_todo_command_lists_owner_and_due_date(recorder):
    hub = FakeHub({"get_latest_meeting": MEETING})
    await meeting_command("/lastmeetingtodo", recorder, hub)
    body = recorder.calls[0][1]["blocks"][1]["text"]["text"]
    assert "• Write the rollback plan _(Eve, due 2025-07-08)_" in body
    assert "• Automate the pipeline _(unassigned)_" in body


async def test_command_errors_are_ephemeral(recorder):
    hub = FakeHub({"get_latest_meeting": HubError("No meetings have been stored yet.")})
    await meeting_command("/lastmeetinguserstory", recorder, hub)
    [(_, kwargs)] = recorder.calls
    assert kwargs["response_type"] == "ephemeral"
    assert "No meetings" in kwargs["text"]


async def test_jira_command_preview_uses_dry_run(recorder):
    result = {
        "message": "Dry run: 1 would create.",
        "results": [{"summary": "Write the rollback plan", "status": "would_create"}],
    }
    hub = FakeHub({"create_jira_tasks": result})
    await jira_command(" preview ", recorder, hub)

    assert hub.calls == [("create_jira_tasks", {"dry_run": True})]
    blocks = recorder.calls[0][1]["blocks"]
    assert "*Would create* Write the rollback plan" in blocks[1]["text"]["text"]


async def test_jira_command_shows_links_and_warnings(recorder):
    result = {
        "message": "1 created.",
        "results": [
            {
                "summary": "Budget proposal",
                "status": "created",
                "jira_key": "POC-7",
                "jira_url": "https://x.atlassian.net/browse/POC-7",
                "warnings": ["'Bob' matches several Jira users; left unassigned."],
            }
        ],
    }
    await jira_command("", recorder, FakeHub({"create_jira_tasks": result}))
    text = recorder.calls[0][1]["blocks"][1]["text"]["text"]
    assert "<https://x.atlassian.net/browse/POC-7|POC-7>" in text
    assert ":warning:" in text


def test_strip_mention_only_removes_the_bot():
    assert strip_mention("<@UBOT> ask <@UALICE> about it", "UBOT") == "ask <@UALICE> about it"
    assert strip_mention("<@UBOT>", "UBOT") == ""


class FakeAgent:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.questions = reply, error, []

    async def run(self, question):
        self.questions.append(question)
        if self.error:
            raise self.error
        return self.reply


EVENT = {"channel": "C1", "ts": "111.1", "text": "<@UBOT> who owns the **rollback plan**?"}


async def test_mention_replies_in_thread_by_updating_placeholder(recorder):
    agent = FakeAgent(AgentReply("**Eve** owns it.", ["ask_meetings"]))
    await answer_mention(EVENT, "UBOT", recorder, agent)

    assert agent.questions == ["who owns the **rollback plan**?"]
    (post, post_args), (update, update_args) = recorder.calls
    assert (post, post_args["text"], post_args["thread_ts"]) == (
        "chat_postMessage",
        THINKING_TEXT,
        "111.1",
    )
    assert update == "chat_update" and update_args["ts"] == "999.1"
    assert update_args["text"] == "*Eve* owns it."


async def test_empty_mention_gets_help(recorder):
    agent = FakeAgent()
    await answer_mention({**EVENT, "text": "<@UBOT>"}, "UBOT", recorder, agent)
    assert recorder.calls == [
        ("chat_postMessage", {"channel": "C1", "thread_ts": "111.1", "text": HELP_TEXT})
    ]
    assert agent.questions == []


async def test_unexpected_agent_errors_do_not_leak_details(recorder):
    agent = FakeAgent(error=KeyError("secret internal detail"))
    await answer_mention(EVENT, "UBOT", recorder, agent)
    text = recorder.calls[-1][1]["text"]
    assert "secret internal detail" not in text
    assert "went wrong" in text


async def test_hub_outage_is_explained(recorder):
    agent = FakeAgent(error=HubError("Meeting hub unavailable"))
    await answer_mention({**EVENT, "thread_ts": "100.0"}, "UBOT", recorder, agent)
    assert recorder.calls[0][1]["thread_ts"] == "100.0"
    assert "couldn't reach the meeting hub" in recorder.calls[-1][1]["text"]
