"""Real Bolt dispatch with Slack's Web API faked at the HTTP layer: proves our listeners are wired to
the right events/actions and receive Bolt's say_stream / set_status."""

import json

import pytest
from slack_bolt.async_app import AsyncApp
from slack_bolt.request.async_request import AsyncBoltRequest
from slack_sdk.web.async_client import AsyncWebClient

from slack_bot.agent import TextDelta, ToolFinished, ToolStarted
from slack_bot.handlers import FEEDBACK_ACTION, register
from tests.conftest import FakeHub


class ScriptedAgent:
    async def stream(self, question, history=()):
        yield ToolStarted("tool-1", "ask_meetings", "Searching meetings")
        yield ToolFinished("tool-1", "ask_meetings", "Searching meetings", ok=True)
        yield TextDelta(f"Answer to: {question}")


@pytest.fixture
def calls(monkeypatch):
    """Every Slack Web API call made by the app: (method, params)."""
    recorded = []

    async def fake_api_call(
        self,
        api_method,
        *,
        http_verb="POST",
        files=None,
        data=None,
        params=None,
        json=None,
        headers=None,
        auth=None,
    ):  # noqa: A002
        if api_method != "auth.test":  # Bolt authorizes once; not interesting here
            recorded.append((api_method, json or data or params or {}))
        body = {"ok": True, "ts": "999.1", "channel": "C1"}
        if api_method == "conversations.replies":
            body["messages"] = []
        from slack_sdk.web.async_slack_response import AsyncSlackResponse

        return AsyncSlackResponse(
            client=self,
            http_verb=http_verb,
            api_url=api_method,
            req_args={},
            data=body,
            headers={},
            status_code=200,
        )

    monkeypatch.setattr(AsyncWebClient, "api_call", fake_api_call)
    return recorded


def app_with_listeners() -> AsyncApp:
    app = AsyncApp(
        token="xoxb-test",
        signing_secret="secret",
        request_verification_enabled=False,
        process_before_response=True,  # run listeners inside dispatch so the test can assert
    )
    register(app, FakeHub(), ScriptedAgent())
    return app


def event_request(event: dict) -> AsyncBoltRequest:
    body = {
        "type": "event_callback",
        "team_id": "T1",
        "api_app_id": "A1",
        "event": event,
        "authorizations": [{"team_id": "T1", "user_id": "UBOT", "is_bot": True}],
        "event_id": "Ev1",
        "event_time": 1,
    }
    return AsyncBoltRequest(body=json.dumps(body), headers={"content-type": ["application/json"]})


def methods(calls):
    return [m for m, _ in calls]


async def test_dm_is_answered_with_session_task_cards_and_stream(calls):
    app = app_with_listeners()
    event = {
        "type": "message",
        "channel_type": "im",
        "channel": "D1",
        "user": "U1",
        "text": "who owns it?",
        "ts": "5.0",
    }
    response = await app.async_dispatch(event_request(event))
    assert response.status == 200
    assert methods(calls)[:2] == ["agents.sessions.setStatus", "chat.startStream"]
    assert "chat.stopStream" in methods(calls)
    start = dict(calls)["chat.startStream"]
    assert start["thread_ts"] == "5.0"  # replies in the DM thread
    stop = dict(calls)["chat.stopStream"]
    assert stop["session_status"] == "active"


async def test_channel_messages_without_a_mention_are_ignored(calls):
    app = app_with_listeners()
    event = {
        "type": "message",
        "channel_type": "channel",
        "channel": "C1",
        "user": "U1",
        "text": "hello",
        "ts": "5.0",
    }
    await app.async_dispatch(event_request(event))
    assert calls == []


async def test_stop_event_is_routed(calls):
    app = app_with_listeners()
    event = {
        "type": "agent_session_stopped",
        "channel": "C1",
        "thread_ts": "7.0",
        "user": "U1",
        "streaming_message_ts": [],
        "event_ts": "8.0",
    }
    response = await app.async_dispatch(event_request(event))
    assert response.status == 200
    assert calls == [
        ("agents.sessions.setStatus", {"channel_id": "C1", "thread_ts": "7.0", "status": "active"})
    ]


async def test_feedback_click_is_routed(calls):
    app = app_with_listeners()
    payload = {
        "type": "block_actions",
        "team": {"id": "T1"},
        "user": {"id": "U1"},
        "api_app_id": "A1",
        "channel": {"id": "C1"},
        "message": {"ts": "9.0", "thread_ts": "7.0"},
        "actions": [
            {
                "action_id": FEEDBACK_ACTION,
                "type": "feedback_buttons",
                "value": "positive",
                "block_id": "b",
            }
        ],
        "trigger_id": "t",
    }
    request = AsyncBoltRequest(
        body="payload=" + json.dumps(payload).replace("&", "%26").replace("+", "%2B"),
        headers={"content-type": ["application/x-www-form-urlencoded"]},
    )
    response = await app.async_dispatch(request)
    assert response.status == 200
    assert methods(calls) == ["chat.postEphemeral"]
