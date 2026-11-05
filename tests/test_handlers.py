import asyncio

from slack_sdk.errors import SlackApiError

from slack_bot.agent import TextDelta, ToolFinished, ToolStarted
from slack_bot.handlers import (
    FEEDBACK_ACTION,
    HELP_TEXT,
    HISTORY_LIMIT,
    answer,
    is_user_dm,
    jira_command,
    meeting_command,
    record_feedback,
    stop_answer,
    strip_mention,
    thread_history,
)
from slack_bot.hub import HubError
from slack_bot.sessions import RunRegistry
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
    def __init__(self, events=(), error=None, hang=False):
        self.events, self.error, self.hang, self.calls = list(events), error, hang, []
        self.started = asyncio.Event()

    async def stream(self, question, history=()):
        self.calls.append((question, list(history)))
        for event in self.events:
            yield event
        self.started.set()
        if self.hang:
            await asyncio.sleep(3600)  # until cancelled by the stop button
        if self.error:
            raise self.error


class FakeStream:
    def __init__(self):
        self.appended, self.chunks, self.stopped_with = [], [], None

    async def append(self, *, markdown_text=None, chunks=None):
        if markdown_text is not None:
            self.appended.append(markdown_text)
        if chunks is not None:
            self.chunks.extend(chunks)

    async def stop(self, **kwargs):
        self.stopped_with = kwargs


class FakeSayStream:
    def __init__(self):
        self.streams = []

    async def __call__(self):
        self.streams.append(FakeStream())
        return self.streams[-1]

    @property
    def stream(self):
        return self.streams[0]


class FakeStatus:
    def __init__(self, error=None):
        self.statuses, self.error = [], error

    async def __call__(self, status):
        if self.error:
            raise self.error
        self.statuses.append(status)


class NotAnAgentClient(Recorder):
    """Workspace/app where agents.sessions.* isn't available (app not declared as an agent)."""

    async def agents_sessions_setStatus(self, **kwargs):
        raise SlackApiError("not_allowed", {"error": "not_allowed_token_type"})


EVENT = {"channel": "C1", "ts": "111.1", "text": "<@UBOT> who owns the rollback plan?"}


async def run_answer(event, client, agent, status=None, runs=None):
    say_stream, status = FakeSayStream(), status or FakeStatus()
    await answer(event, "UBOT", client, agent, say_stream, status, runs or RunRegistry())
    return say_stream, status


async def test_answer_uses_agent_session_task_cards_and_feedback(recorder):
    agent = FakeAgent(
        [
            ToolStarted("tool-1", "ask_meetings", "Searching meetings"),
            ToolFinished("tool-1", "ask_meetings", "Searching meetings", ok=True),
            TextDelta("**Eve** "),
            TextDelta("owns it."),
        ]
    )
    say_stream, status = await run_answer(EVENT, recorder, agent)
    stream = say_stream.stream

    assert agent.calls == [("who owns the rollback plan?", [])]
    name, kwargs = recorder.calls[0]
    assert name == "agents_sessions_setStatus"
    assert (kwargs["status"], kwargs["thread_ts"], kwargs["title"]) == (
        "processing",
        "111.1",
        "who owns the rollback plan?",
    )
    assert status.statuses == []  # sessions worked; no legacy status needed
    assert [(c["id"], c["status"]) for c in stream.chunks] == [
        ("tool-1", "in_progress"),
        ("tool-1", "complete"),
    ]
    assert stream.appended == ["**Eve** ", "owns it."]
    assert stream.stopped_with["session_status"] == "active"
    feedback = stream.stopped_with["blocks"][0]["elements"][0]
    assert (feedback["type"], feedback["action_id"]) == ("feedback_buttons", FEEDBACK_ACTION)


async def test_failed_tool_shows_an_error_task_card(recorder):
    agent = FakeAgent(
        [
            ToolStarted("tool-1", "create_jira_tasks", "Talking to Jira"),
            ToolFinished("tool-1", "create_jira_tasks", "Talking to Jira", ok=False),
            TextDelta("Jira is down."),
        ]
    )
    say_stream, _ = await run_answer(EVENT, recorder, agent)
    assert say_stream.stream.chunks[-1]["status"] == "error"


async def test_falls_back_to_legacy_status_when_not_declared_as_agent():
    client = NotAnAgentClient()
    say_stream, status = await run_answer(EVENT, client, FakeAgent([TextDelta("Fine.")]))
    assert status.statuses == ["is thinking…"]
    assert say_stream.stream.appended == ["Fine."]


async def test_empty_mention_gets_help(recorder):
    agent = FakeAgent()
    await run_answer({**EVENT, "text": "<@UBOT>"}, recorder, agent)
    assert recorder.calls == [
        ("chat_postMessage", {"channel": "C1", "thread_ts": "111.1", "text": HELP_TEXT})
    ]
    assert agent.calls == []


async def test_unexpected_errors_do_not_leak_details_and_close_the_stream(recorder):
    agent = FakeAgent([TextDelta("Partial ")], error=KeyError("secret internal detail"))
    say_stream, _ = await run_answer(EVENT, recorder, agent)
    stream = say_stream.stream
    assert stream.appended[0] == "Partial "
    assert "went wrong" in stream.appended[-1]
    assert "secret internal detail" not in "".join(stream.appended)
    assert stream.stopped_with is not None


async def test_hub_outage_is_explained(recorder):
    say_stream, _ = await run_answer(
        EVENT, recorder, FakeAgent(error=HubError("Meeting hub unavailable"))
    )
    assert "couldn't reach the meeting hub" in say_stream.stream.appended[-1]


async def test_stop_button_cancels_the_running_answer(recorder):
    runs = RunRegistry()
    agent = FakeAgent([TextDelta("Working on it ")], hang=True)
    say_stream = FakeSayStream()
    task = asyncio.create_task(
        answer(EVENT, "UBOT", recorder, agent, say_stream, FakeStatus(), runs)
    )
    await asyncio.wait_for(agent.started.wait(), 5)

    await stop_answer({"channel": "C1", "thread_ts": "111.1"}, recorder, runs)
    await asyncio.wait_for(task, 5)  # finishes cleanly instead of raising CancelledError

    stream = say_stream.stream
    assert stream.appended == ["Working on it ", "\n\n_Stopped._"]
    assert stream.stopped_with["session_status"] == "active"


async def test_stop_with_nothing_running_marks_the_session_active(recorder):
    await stop_answer({"channel": "C1", "thread_ts": "9.9"}, recorder, RunRegistry())
    assert recorder.calls == [
        ("agents_sessions_setStatus", {"channel_id": "C1", "thread_ts": "9.9", "status": "active"})
    ]


async def test_feedback_is_acknowledged_privately(recorder):
    body = {
        "actions": [{"action_id": FEEDBACK_ACTION, "value": "positive"}],
        "user": {"id": "UALICE"},
        "channel": {"id": "C1"},
        "message": {"ts": "222.2", "thread_ts": "111.1"},
    }
    await record_feedback(body, recorder)
    assert recorder.calls == [
        (
            "chat_postEphemeral",
            {
                "channel": "C1",
                "user": "UALICE",
                "thread_ts": "111.1",
                "text": "Thanks for the feedback!",
            },
        )
    ]


def test_only_human_dm_messages_are_answered():
    dm = {"channel_type": "im", "text": "hi", "user": "U1"}
    assert is_user_dm(dm)
    assert not is_user_dm({**dm, "bot_id": "B1"})  # our own replies
    assert not is_user_dm({**dm, "subtype": "message_changed"})
    assert not is_user_dm({**dm, "channel_type": "channel"})


class ThreadClient(Recorder):
    def __init__(self, messages=None, error=None):
        super().__init__()
        self.messages, self.error = messages or [], error

    async def conversations_replies(self, **kwargs):
        self.calls.append(("conversations_replies", kwargs))
        if self.error:
            raise SlackApiError(self.error, {"error": self.error})
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
    await run_answer(event, client, agent)

    question, history = agent.calls[0]
    assert question == "and who reviews it?"
    assert history == [
        ("user", "what did we decide on rollback?"),
        ("model", "Eve writes a rollback plan."),
    ]
    replies_call = next(kw for name, kw in client.calls if name == "conversations_replies")
    assert replies_call["limit"] == HISTORY_LIMIT == 15  # max for non-Marketplace distributed apps


async def test_thread_history_is_bounded(monkeypatch):
    from slack_bot import handlers

    monkeypatch.setattr(handlers, "HISTORY_CHARS", 25)
    client = ThreadClient(
        [{"ts": f"{n}.0", "user": "U1", "text": f"message number {n}"} for n in range(5)]
    )
    history = await thread_history(client, "C1", {"ts": "9.9", "thread_ts": "0.0"}, "UBOT")
    assert history == [("user", "message number 4")]  # most recent within the budget


async def test_rate_limited_or_missing_scope_history_degrades_gracefully():
    for error in ("ratelimited", "missing_scope"):
        client = ThreadClient(error=error)
        assert await thread_history(client, "C1", {"ts": "1", "thread_ts": "0"}, "UBOT") == []
