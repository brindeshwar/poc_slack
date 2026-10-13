from slack_bot.agent import Status, TextDelta
from slack_bot.handlers import (
    HELP_TEXT,
    THINKING_STATUS,
    answer_mention,
    jira_command,
    meeting_command,
    strip_mention,
    thread_history,
)
from slack_bot.hub import HubError
from tests.conftest import MEETING, FakeHub, Recorder


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
    def __init__(self, events=(), error=None):
        self.events, self.error, self.calls = list(events), error, []

    async def stream(self, question, history=()):
        self.calls.append((question, list(history)))
        for event in self.events:
            yield event
        if self.error:
            raise self.error


class FakeStream:
    def __init__(self):
        self.appended, self.stopped = [], False

    async def append(self, *, markdown_text):
        self.appended.append(markdown_text)

    async def stop(self):
        self.stopped = True


class FakeSayStream:
    def __init__(self):
        self.stream = FakeStream()

    async def __call__(self):
        return self.stream


class FakeStatus:
    def __init__(self, error=None):
        self.statuses, self.error = [], error

    async def __call__(self, status):
        if self.error:
            raise self.error
        self.statuses.append(status)


EVENT = {"channel": "C1", "ts": "111.1", "text": "<@UBOT> who owns the rollback plan?"}


async def mention(event, recorder, agent, status=None):
    say_stream, status = FakeSayStream(), status or FakeStatus()
    await answer_mention(event, "UBOT", recorder, agent, say_stream, status)
    return say_stream.stream, status


async def test_mention_streams_answer_with_status_updates(recorder):
    agent = FakeAgent(
        [
            Status("Searching meetings…", "ask_meetings"),
            TextDelta("**Eve** "),
            TextDelta("owns it."),
        ]
    )
    stream, status = await mention(EVENT, recorder, agent)

    assert agent.calls == [("who owns the rollback plan?", [])]
    assert status.statuses == [THINKING_STATUS, "Searching meetings…"]
    assert stream.appended == ["**Eve** ", "owns it."]  # Markdown streams as-is
    assert stream.stopped
    assert recorder.calls == []  # no placeholder posts or edits any more


async def test_empty_mention_gets_help(recorder):
    agent = FakeAgent()
    await mention({**EVENT, "text": "<@UBOT>"}, recorder, agent)
    assert recorder.calls == [
        ("chat_postMessage", {"channel": "C1", "thread_ts": "111.1", "text": HELP_TEXT})
    ]
    assert agent.calls == []


async def test_unexpected_errors_do_not_leak_details_and_close_the_stream(recorder):
    agent = FakeAgent([TextDelta("Partial ")], error=KeyError("secret internal detail"))
    stream, _ = await mention(EVENT, recorder, agent)
    assert stream.appended[0] == "Partial "
    assert "went wrong" in stream.appended[-1]
    assert "secret internal detail" not in "".join(stream.appended)
    assert stream.stopped


async def test_hub_outage_is_explained(recorder):
    stream, _ = await mention(EVENT, recorder, FakeAgent(error=HubError("Meeting hub unavailable")))
    assert "couldn't reach the meeting hub" in stream.appended[-1]
    assert stream.stopped


async def test_status_failures_never_break_the_answer(recorder):
    from slack_sdk.errors import SlackApiError

    broken = FakeStatus(error=SlackApiError("missing_scope", {"error": "missing_scope"}))
    stream, _ = await mention(EVENT, recorder, FakeAgent([TextDelta("Fine.")]), broken)
    assert stream.appended == ["Fine."] and stream.stopped


class ThreadClient(Recorder):
    def __init__(self, messages):
        super().__init__()
        self.messages = messages

    async def conversations_replies(self, **kwargs):
        self.calls.append(("conversations_replies", kwargs))
        return {"messages": self.messages}


async def test_follow_ups_in_a_thread_include_earlier_messages():
    client = ThreadClient(
        [
            {"ts": "100.0", "user": "UALICE", "text": "<@UBOT> what did we decide on rollback?"},
            {"ts": "100.5", "bot_id": "B1", "user": "UBOT", "text": "Eve writes a rollback plan."},
            {"ts": "111.1", "user": "UALICE", "text": "<@UBOT> and who reviews it?"},
        ]
    )
    agent = FakeAgent([TextDelta("David.")])
    event = {**EVENT, "thread_ts": "100.0", "text": "<@UBOT> and who reviews it?"}
    await mention(event, client, agent)

    question, history = agent.calls[0]
    assert question == "and who reviews it?"
    assert history == [
        ("user", "what did we decide on rollback?"),
        ("model", "Eve writes a rollback plan."),
    ]


async def test_thread_history_is_bounded(monkeypatch):
    from slack_bot import handlers

    monkeypatch.setattr(handlers, "HISTORY_CHARS", 25)
    client = ThreadClient(
        [{"ts": f"{n}.0", "user": "U1", "text": f"message number {n}"} for n in range(5)]
    )
    history = await thread_history(client, "C1", {"ts": "9.9", "thread_ts": "0.0"}, "UBOT")
    assert history == [("user", "message number 4")]  # most recent within the budget


async def test_missing_history_scope_degrades_gracefully():
    from slack_sdk.errors import SlackApiError

    class NoScope(Recorder):
        async def conversations_replies(self, **kwargs):
            raise SlackApiError("missing_scope", {"error": "missing_scope"})

    assert await thread_history(NoScope(), "C1", {"ts": "1", "thread_ts": "0"}, "UBOT") == []
