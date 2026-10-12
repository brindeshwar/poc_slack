"""Gemini agent that answers Slack questions by calling the meeting hub's MCP tools."""

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from google import genai
from google.genai import types

from slack_bot.hub import HubClient, HubError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are ListenLoom, a Slack assistant for a team's meetings. Today is {today}.
Use the tools to look things up; never invent meeting content. Prefer `ask_meetings` for questions
and `get_latest_meeting` for "last meeting" requests.
Only call `create_jira_tasks` when the user explicitly asks to create Jira tickets or tasks. If they
just ask what the tickets would be, call it with dry_run=true.
Reply in Slack format: *bold*, _italic_, bullet lists with "•", links as <url|text>. Keep replies short."""

STEP_LIMIT_REPLY = "Sorry, that took too many steps. Could you ask a more specific question?"


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
        model: str = "gemini-2.5-flash",
        max_steps: int = 6,
        client: Any = None,
    ) -> None:
        self._hub = hub
        self._client = client or genai.Client(api_key=api_key)
        self._model = model
        self._max_steps = max_steps

    async def run(self, question: str) -> AgentReply:
        tools_used: list[str] = []
        async with self._hub.connect() as session:
            mcp_tools = await session.list_tools()
            config = types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT.format(today=date.today().isoformat()),
                temperature=0.2,
                tools=[
                    types.Tool(
                        function_declarations=[
                            types.FunctionDeclaration(
                                name=t.name,
                                description=t.description or "",
                                parameters_json_schema=t.inputSchema,
                            )
                            for t in mcp_tools
                        ]
                    )
                ],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )
            contents: list[types.Content] = [
                types.Content(role="user", parts=[types.Part.from_text(text=question)])
            ]

            for _ in range(self._max_steps):
                response = await self._client.aio.models.generate_content(
                    model=self._model, contents=contents, config=config
                )
                calls = response.function_calls or []
                if not calls:
                    return AgentReply(
                        (response.text or "").strip() or "I don't have an answer for that.",
                        tools_used,
                    )

                contents.append(response.candidates[0].content)
                replies = []
                for call in calls:
                    name = call.name or ""
                    tools_used.append(name)
                    replies.append(
                        types.Part.from_function_response(
                            name=name, response=await self._call_tool(session, name, call.args)
                        )
                    )
                contents.append(types.Content(role="user", parts=replies))

        return AgentReply(STEP_LIMIT_REPLY, tools_used)

    @staticmethod
    async def _call_tool(session: Any, name: str, args: dict[str, Any] | None) -> dict[str, Any]:
        logger.info("Agent calling %s(%s)", name, json.dumps(args or {})[:200])
        try:
            return {"result": await session.call(name, dict(args or {}))}
        except HubError as exc:
            # Let the model see the error so it can explain it or try something else.
            return {"error": str(exc)}
