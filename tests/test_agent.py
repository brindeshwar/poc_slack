from google.genai import types

from slack_bot.agent import (
    NO_ANSWER_REPLY,
    STEP_LIMIT_REPLY,
    MeetingAgent,
    Status,
    TextDelta,
)
from slack_bot.hub import HubError
from tests.conftest import FakeHub


def chunk(*parts: types.Part) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))]
    )


def text(value: str) -> types.Part:
    return types.Part.from_text(text=value)


def call(name: str, args: dict, signature: bytes | None = None) -> types.Part:
    part = types.Part.from_function_call(name=name, args=args)
    if signature:
        part.thought_signature = signature  # Gemini 3 attaches these to function calls
    return part


class FakeGemini:
    """Mimics `client.aio.models.generate_content_stream`: each scripted step is a list of chunks."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.requests = []
        self.aio = self
        self.models = self

    async def generate_content_stream(self, *, model, contents, config):
        self.requests.append((list(contents), config))
        chunks = self.steps.pop(0)

        async def iterate():
            for c in chunks:
                yield c

        return iterate()


async def collect(agent, question, history=()):
    return [event async for event in agent.stream(question, history)]


async def test_streams_text_deltas_in_order():
    gemini = FakeGemini([[chunk(text("Eve ")), chunk(text("owns it."))]])
    events = await collect(MeetingAgent(FakeHub(), client=gemini), "who?")
    assert events == [TextDelta("Eve "), TextDelta("owns it.")]


async def test_run_joins_the_stream():
    gemini = FakeGemini([[chunk(text("Hello")), chunk(text("!"))]])
    reply = await MeetingAgent(FakeHub(), client=gemini).run("hi")
    assert (reply.text, reply.tools_used) == ("Hello!", [])


async def test_exposes_mcp_tools_and_thinking_level_to_gemini():
    gemini = FakeGemini([[chunk(text("ok"))]])
    await collect(MeetingAgent(FakeHub(), client=gemini, thinking_level="minimal"), "hi")
    _, config = gemini.requests[0]
    names = [d.name for d in config.tools[0].function_declarations]
    assert names == ["ask_meetings", "get_latest_meeting", "create_jira_tasks"]
    assert config.automatic_function_calling.disable is True
    assert config.thinking_config.thinking_level == types.ThinkingLevel.MINIMAL


async def test_status_before_tool_call_then_result_fed_back():
    hub = FakeHub({"ask_meetings": {"answer": "Eve owns it", "sources": []}})
    gemini = FakeGemini(
        [
            [chunk(call("ask_meetings", {"question": "rollback owner"}))],
            [chunk(text("Eve."))],
        ]
    )
    events = await collect(MeetingAgent(hub, client=gemini), "who owns rollback?")

    assert events == [Status("Searching meetings…", "ask_meetings"), TextDelta("Eve.")]
    assert hub.calls == [("ask_meetings", {"question": "rollback owner"})]
    contents, _ = gemini.requests[1]
    assert contents[-1].parts[0].function_response.response == {
        "result": {"answer": "Eve owns it", "sources": []}
    }


async def test_thought_signatures_are_sent_back_unchanged():
    hub = FakeHub({"get_latest_meeting": {"title": "Eng sync"}})
    gemini = FakeGemini(
        [
            [
                chunk(types.Part(text="planning…", thought=True)),
                chunk(call("get_latest_meeting", {}, b"sig-1")),
            ],
            [chunk(text("Done."))],
        ]
    )
    events = await collect(MeetingAgent(hub, client=gemini), "last meeting?")

    assert TextDelta("planning…") not in events  # thoughts are never shown to users
    model_turn = gemini.requests[1][0][-2]
    assert model_turn.role == "model"
    assert [p.thought for p in model_turn.parts] == [True, None]
    assert model_turn.parts[1].thought_signature == b"sig-1"


async def test_thread_history_is_sent_before_the_question():
    gemini = FakeGemini([[chunk(text("It's Eve."))]])
    history = [("user", "what was decided about rollback?"), ("model", "Eve writes a plan.")]
    await collect(MeetingAgent(FakeHub(), client=gemini), "and who owns that?", history)
    contents, _ = gemini.requests[0]
    assert [(c.role, c.parts[0].text) for c in contents] == [
        *history,
        ("user", "and who owns that?"),
    ]


async def test_tool_errors_are_given_to_the_model():
    hub = FakeHub({"get_latest_meeting": HubError("No meetings have been stored yet.")})
    gemini = FakeGemini(
        [[chunk(call("get_latest_meeting", {}))], [chunk(text("There are no meetings yet."))]]
    )
    reply = await MeetingAgent(hub, client=gemini).run("last meeting?")
    contents, _ = gemini.requests[1]
    assert contents[-1].parts[0].function_response.response == {
        "error": "No meetings have been stored yet."
    }
    assert reply.text == "There are no meetings yet."


async def test_empty_answer_gets_a_fallback():
    gemini = FakeGemini([[chunk(types.Part(text="hmm", thought=True))]])
    assert await collect(MeetingAgent(FakeHub(), client=gemini), "?") == [
        TextDelta(NO_ANSWER_REPLY)
    ]


async def test_stops_after_step_limit():
    hub = FakeHub({"get_latest_meeting": {"title": "x"}})
    gemini = FakeGemini([[chunk(call("get_latest_meeting", {}))] for _ in range(3)])
    reply = await MeetingAgent(hub, client=gemini, max_steps=3).run("loop forever")
    assert reply.text == STEP_LIMIT_REPLY
    assert len(hub.calls) == 3
