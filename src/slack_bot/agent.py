"""Gemini agent that answers Slack questions by calling the meeting hub's MCP tools."""

import json
import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from google import genai
from google.genai import types

from slack_bot.hub import HubClient, HubError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are ListenLoom, a Slack assistant for a team's meetings. Today is {today}.
Use the tools to look things up; never invent meeting content. Prefer `ask_meetings` for questions
and `get_latest_meeting` for "last meeting" requests. Earlier messages in the conversation are the
Slack thread so far; use them to resolve follow-ups like "who owns that?".
Only call `create_jira_tasks` when the user explicitly asks to create Jira tickets or tasks. If they
just ask what the tickets would be, call it with dry_run=true.
Reply in concise Markdown (bold, bullet lists, links)."""

STEP_LIMIT_REPLY = "Sorry, that took too many steps. Could you ask a more specific question?"
NO_ANSWER_REPLY = "I don't have an answer for that."

# What the user sees in Slack's status line while a tool runs.
TOOL_STATUS = {
    "ask_meetings": "Searching meetings…",
    "search_meetings": "Searching meetings…",
    "get_latest_meeting": "Reading the latest meeting…",
    "list_meetings": "Looking through meetings…",
    "get_meeting": "Reading the meeting…",
    "create_jira_tasks": "Talking to Jira…",
    "ingest_meeting": "Saving the meeting…",
}

ThinkingLevel = Literal["minimal", "low", "medium", "high"]
Turn = tuple[Literal["user", "model"], str]


@dataclass(frozen=True)
class Status:
    """A tool is about to run."""

    text: str
    tool: str


@dataclass(frozen=True)
class TextDelta:
    """A piece of the answer, in order."""

    text: str


AgentEvent = Status | TextDelta


@dataclass
class AgentReply:
    text: str
    tools_used: list[str] = field(default_factory=list)


class MeetingAgent:
    def __init__(
        self,
        hub: HubClient,
        *,
        api_key: str | None = None,
        model: str = "gemini-3.5-flash-lite",
        thinking_level: ThinkingLevel = "low",
        max_steps: int = 6,
        client: Any = None,
    ) -> None:
        self._hub = hub
        self._client = client or genai.Client(api_key=api_key)
        self._model = model
        self._thinking = types.ThinkingConfig(
            thinking_level=types.ThinkingLevel(thinking_level.upper())
        )
        self._max_steps = max_steps

    async def stream(
        self, question: str, history: Sequence[Turn] = ()
    ) -> AsyncIterator[AgentEvent]:
        """Answer `question`, yielding Status events before tool calls and the answer as TextDeltas.

        Each model step is streamed. Every part the model returns is kept and sent back verbatim,
        which preserves Gemini 3 thought signatures across function-calling turns."""
        async with self._hub.connect() as session:
            config = self._config(await session.list_tools())
            contents = [
                types.Content(role=role, parts=[types.Part.from_text(text=text)])
                for role, text in history
            ]
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=question)]))

            for _ in range(self._max_steps):
                parts: list[types.Part] = []
                calls: list[types.FunctionCall] = []
                answered = False
                stream = await self._client.aio.models.generate_content_stream(
                    model=self._model, contents=contents, config=config
                )
                async for chunk in stream:
                    content = chunk.candidates[0].content if chunk.candidates else None
                    for part in content.parts if content and content.parts else []:
                        parts.append(part)
                        if part.function_call:
                            calls.append(part.function_call)
                        elif part.text and not part.thought:
                            answered = True
                            yield TextDelta(part.text)

                if not calls:
                    if not answered:
                        yield TextDelta(NO_ANSWER_REPLY)
                    return

                contents.append(types.Content(role="model", parts=parts))
                replies = []
                for call in calls:
                    name = call.name or ""
                    yield Status(TOOL_STATUS.get(name, "Working…"), name)
                    replies.append(
                        types.Part.from_function_response(
                            name=name, response=await self._call_tool(session, name, call.args)
                        )
                    )
                contents.append(types.Content(role="user", parts=replies))

        yield TextDelta(STEP_LIMIT_REPLY)

    async def run(self, question: str, history: Sequence[Turn] = ()) -> AgentReply:
        """Non-streaming convenience wrapper around `stream`."""
        text, tools = [], []
        async for event in self.stream(question, history):
            if isinstance(event, TextDelta):
                text.append(event.text)
            else:
                tools.append(event.tool)
        return AgentReply("".join(text).strip(), tools)

    def _config(self, mcp_tools: list[Any]) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT.format(today=date.today().isoformat()),
            temperature=0.2,
            thinking_config=self._thinking,
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t.name,
                            description=t.description or "",
                            parameters_json_schema=t.input_schema,
                        )
                        for t in mcp_tools
                    ]
                )
            ],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    @staticmethod
    async def _call_tool(session: Any, name: str, args: dict[str, Any] | None) -> dict[str, Any]:
        logger.info("Agent calling %s(%s)", name, json.dumps(args or {})[:200])
        try:
            return {"result": await session.call(name, dict(args or {}))}
        except HubError as exc:
            # Let the model see the error so it can explain it or try something else.
            return {"error": str(exc)}
