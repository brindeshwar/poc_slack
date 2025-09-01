import os
from typing import Optional
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.oauth.installation_store import InstallationStore
from slack_sdk.errors import SlackApiError
import google.generativeai as genai


from data_store import get_latest_meeting_data


async def handle_slash_command_logic(
    command: str,
    team_id: str,
    channel_id: str,
    installation_store: InstallationStore,
    slack_client: AsyncWebClient # Pass the client configured with bot_token
):
    """
    Handles the logic for /lastmeetingsummary, /lastmeetingtodo, /lastmeetinguserstory.
    Sends the response directly to Slack.
    """
    response_blocks = []
    response_text = "" # Initialize here

    data_map = {
        "/lastmeetingsummary": {"field": "summary", "title": "Latest Meeting Summary"},
        "/lastmeetingtodo": {"field": "todo", "title": "Latest Meeting To-Do Items"},
        "/lastmeetinguserstory": {"field": "userstories", "title": "Latest Meeting User Stories"},
    }

    command_info = data_map.get(command)

    if command_info:
        data_content = get_latest_meeting_data(command_info["field"])
        if data_content:
            response_text = f"*{command_info['title']}:*\n{data_content}"
        else:
            response_text = "No meeting data found yet. Add some meeting data first!"
    else:
        response_text = "Unknown slash command."

    response_blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": response_text # Using the constructed response_text for the block
            }
        }
    )

    try:
        await slack_client.chat_postMessage(
            channel=channel_id,
            text=response_text, # <-- ADDED THIS: Provides the top-level text fallback
            blocks=response_blocks
        )
    except SlackApiError as e:
        print(f"Error sending slash command response to Slack: {e.response['error']}")
    except Exception as e:
        print(f"Unexpected error in slash command logic: {e}")

async def handle_app_mention_logic(
    clean_text: str, # Text after bot mention
    user_id: str,
    channel_id: str,
    team_id: str,
    installation_store: InstallationStore,
    slack_client: AsyncWebClient # Pass the client configured with bot_token
):
    """
    Handles the logic for @poc_slack mentions, integrating with Google Gemini AI.
    Sends the response directly to Slack.
    """
    gemini_response_text: str = ""

    if clean_text:
        try:
            print(f"Sending to Gemini: '{clean_text}'")
            model = genai.GenerativeModel('gemini-pro') # Or 'gemini-1.5-flash', etc.
            response = await model.generate_content(clean_text) # Use await here
            gemini_response_text = response.text
            print(f"Received from Gemini: '{gemini_response_text}'")

        except Exception as gemini_e:
            gemini_response_text = f"Sorry, I couldn't get a response from Gemini AI at the moment. Error: {gemini_e}"
            print(f"Gemini AI error: {gemini_e}")
    else:
        gemini_response_text = f"Hello <@{user_id}>! What can I help you with today? Please provide some text after mentioning me."

    try:
        await slack_client.chat_postMessage(
            channel=channel_id,
            text=gemini_response_text # This already had the text argument, so it's good.
        )
    except SlackApiError as e:
        print(f"Error posting message to Slack: {e.response['error']}")
    except Exception as e:
        print(f"Unexpected error in app_mention logic: {e}")