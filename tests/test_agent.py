from google.genai import types

from slack_bot.agent import STEP_LIMIT_REPLY, MeetingAgent
from slack_bot.hub import HubError
from tests.conftest import FakeHub


def text_response(text: str) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part.from_text(text=text)])
            )
        ]
    )


def call_response(name: str, args: dict) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model", parts=[types.Part.from_function_call(name=name, args=args)]
                )
            )
        ]
    )


class FakeGemini:
    """Mimics `client.aio.models.generate_content` with scripted responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.aio = self
        self.models = self

    async def generate_content(self, *, model, contents, config):
        self.requests.append((list(contents), config))
        return self.responses.pop(0)


async def test_answers_directly_without_tools():
    gemini = FakeGemini([text_response("Hello!")])
    reply = await MeetingAgent(FakeHub(), client=gemini).run("hi")
    assert reply.text == "Hello!"
    assert reply.tools_used == []


async def test_exposes_mcp_tools_to_gemini():
    gemini = FakeGemini([text_response("ok")])
    await MeetingAgent(FakeHub(), client=gemini).run("hi")
    _, config = gemini.requests[0]
    names = [d.name for d in config.tools[0].function_declarations]
    assert names == ["ask_meetings", "get_latest_meeting", "create_jira_tasks"]
    assert config.automatic_function_calling.disable is True


async def test_calls_tool_and_feeds_result_back():
    hub = FakeHub({"ask_meetings": {"answer": "Eve owns it", "sources": []}})
    gemini = FakeGemini(
        [call_response("ask_meetings", {"question": "rollback owner"}), text_response("Eve.")]
    )
    reply = await MeetingAgent(hub, client=gemini).run("who owns rollback?")

    assert reply.text == "Eve."
    assert reply.tools_used == ["ask_meetings"]
    assert hub.calls == [("ask_meetings", {"question": "rollback owner"})]
    contents, _ = gemini.requests[1]
    function_response = contents[-1].parts[0].function_response
    assert function_response.response == {"result": {"answer": "Eve owns it", "sources": []}}


async def test_tool_errors_are_given_to_the_model():
    hub = FakeHub({"get_latest_meeting": HubError("No meetings have been stored yet.")})
    gemini = FakeGemini(
        [call_response("get_latest_meeting", {}), text_response("There are no meetings yet.")]
    )
    reply = await MeetingAgent(hub, client=gemini).run("last meeting?")
    contents, _ = gemini.requests[1]
    assert contents[-1].parts[0].function_response.response == {
        "error": "No meetings have been stored yet."
    }
    assert reply.text == "There are no meetings yet."


async def test_stops_after_step_limit():
    hub = FakeHub({"get_latest_meeting": {"title": "x"}})
    gemini = FakeGemini([call_response("get_latest_meeting", {}) for _ in range(3)])
    reply = await MeetingAgent(hub, client=gemini, max_steps=3).run("loop forever")
    assert reply.text == STEP_LIMIT_REPLY
    assert len(hub.calls) == 3
