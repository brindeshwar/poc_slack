import json
import os
import html
import time
import secrets
from typing import Dict, Optional, Any
from slack_logic import handle_slash_command_logic, handle_app_mention_logic

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.oauth.installation_store import FileInstallationStore

import google.generativeai as genai

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from slack_sdk.oauth import AuthorizeUrlGenerator
from slack_sdk.oauth.installation_store import Installation, InstallationStore
from slack_sdk.oauth.state_store import OAuthStateStore
from slack_sdk.web.async_client import AsyncWebClient
from dotenv import load_dotenv

load_dotenv()


# --- Configuration and Initialization ---

SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"] 
GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]


genai.configure(api_key=GOOGLE_API_KEY)

# --- Custom In-Memory Stores for POC ---
class InMemoryOAuthStateStore(OAuthStateStore):
    def __init__(self, expiration_seconds: int = 300):
        self.states: Dict[str, float] = {}
        self.expiration_seconds = expiration_seconds

    def issue(self) -> str:
        state = secrets.token_hex(16)
        expiration_time = time.time() + self.expiration_seconds
        self.states[state] = expiration_time
        return state

    def consume(self, state: str) -> bool:
        if state in self.states:
            expiration_time = self.states[state]
            del self.states[state]
            return time.time() < expiration_time
        return False

# class InMemoryInstallationStore(InstallationStore):
#     def __init__(self):
#         self.installations: Dict[str, Installation] = {}

#     def _get_key(self, enterprise_id: Optional[str], team_id: Optional[str]) -> str:
#         return f"{enterprise_id or 'none'}-{team_id or 'none'}"

#     def save(self, installation: Installation):
#         key = self._get_key(installation.enterprise_id, installation.team_id)
#         self.installations[key] = installation
#         print(f"Stored installation for team {installation.team_id} (in-memory)")

#     def find_installation(
#         self,
#         *,
#         enterprise_id: Optional[str],
#         team_id: Optional[str],
#         user_id: Optional[str] = None,
#         is_enterprise_install: Optional[bool] = False
#     ) -> Optional[Installation]:
#         key = self._get_key(enterprise_id, team_id)
#         installation = self.installations.get(key)
#         if installation:
#             print(f"Found installation for team {team_id} (in-memory)")
#         else:
#             print(f"No installation found for team {team_id} (in-memory)")
#         return installation

#     def find_bot(
#         self,
#         *,
#         enterprise_id: Optional[str],
#         team_id: Optional[str],
#         is_enterprise_install: Optional[bool] = False,
#     ) -> Optional[Installation]:
#         return self.find_installation(
#             enterprise_id=enterprise_id,
#             team_id=team_id,
#             is_enterprise_install=is_enterprise_install
#         )

# --- Initialize In-Memory Stores ---
state_store = InMemoryOAuthStateStore(expiration_seconds=300)
installation_store = FileInstallationStore(base_dir="./installations")

# --- FastAPI App Initialization ---
app_fastapi = FastAPI()

# --- Initialize Bolt App ---
app_bolt = AsyncApp(
    token=os.environ.get("SLACK_BOT_TOKEN"), # Your xoxb- token for bot calls
    signing_secret="SLACK_SIGNING_SECRET", # Still needed for HTTP callbacks (like OAuth)
    installation_store=installation_store, # Your custom store
)

# --- OAuth Configuration ---
# Your ngrok public URL for the callback
NGROK_REDIRECT_URI = "https://trusting-topical-shark.ngrok-free.app/slack/oauth/callback"

authorize_url_generator = AuthorizeUrlGenerator(
    client_id=os.environ["SLACK_CLIENT_ID"],
    scopes=["app_mentions:read", "assistant:write", "incoming-webhook"],
    user_scopes=["im:read"],
    redirect_uri=NGROK_REDIRECT_URI,
)

# --- Routes ---

@app_fastapi.get("/slack/install", response_class=HTMLResponse)
async def oauth_start():
    state = state_store.issue()

    # Generate the Slack OAuth URL using the configured client_id and scopes,
    # specifically setting the redirect_uri to your ngrok URL.
    auth_url = authorize_url_generator.generate(
        state=state,
    )

    # Embed the provided HTML button, updating its href with the generated auth_url
    html_content = f"""
    <a href="{html.escape(auth_url)}" style="align-items:center;color:#000;background-color:#fff;border:1px solid #ddd;border-radius:4px;display:inline-flex;font-family:Lato, sans-serif;font-size:16px;font-weight:600;height:48px;justify-content:center;text-decoration:none;width:236px">
        <svg xmlns="http://www.w3.org/2000/svg" style="height:20px;width:20px;margin-right:12px" viewBox="0 0 122.8 122.8">
            <path d="M25.8 77.6c0 7.1-5.8 12.9-12.9 12.9S0 84.7 0 77.6s5.8-12.9 12.9-12.9h12.9v12.9zm6.5 0c0-7.1 5.8-12.9 12.9-12.9s12.9 5.8 12.9 12.9v32.3c0 7.1-5.8 12.9-12.9 12.9s-12.9-5.8-12.9-12.9V77.6z" fill="#e01e5a"></path>
            <path d="M45.2 25.8c-7.1 0-12.9-5.8-12.9-12.9S38.1 0 45.2 0s12.9 5.8 12.9 12.9v12.9H45.2zm0 6.5c7.1 0 12.9 5.8 12.9 12.9s-5.8 12.9-12.9 12.9H12.9C5.8 58.1 0 52.3 0 45.2s5.8-12.9 12.9-12.9h32.3z" fill="#36c5f0"></path>
            <path d="M97 45.2c0-7.1 5.8-12.9 12.9-12.9s12.9 5.8 12.9 12.9-5.8 12.9-12.9 12.9H97V45.2zm-6.5 0c0 7.1-5.8 12.9-12.9 12.9s-12.9-5.8-12.9-12.9V12.9C64.7 5.8 70.5 0 77.6 0s12.9 5.8 12.9 12.9v32.3z" fill="#2eb67d"></path>
            <path d="M77.6 97c7.1 0 12.9 5.8 12.9 12.9s-5.8 12.9-12.9 12.9-12.9-5.8-12.9-12.9V97h12.9zm0-6.5c-7.1 0-12.9-5.8-12.9-12.9s5.8-12.9 12.9-12.9h32.3c7.1 0 12.9 5.8 12.9 12.9s-5.8 12.9-12.9 12.9H77.6z" fill="#ecb22e"></path>
        </svg>
        Add to Slack
    </a>
    """
    return HTMLResponse(content=html_content)


@app_fastapi.get("/slack/oauth/callback")
async def oauth_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None
):
    if error:
        print(f"OAuth error: {error}")
        return HTMLResponse(f"Something is wrong with the installation (error: {html.escape(error)})", status_code=400)

    if code and state:
        if not state_store.consume(state):
            print(f"State verification failed: {state}")
            return HTMLResponse(f"Try the installation again (the state value is already expired or invalid)", status_code=400)

    
        client_id = os.environ["SLACK_CLIENT_ID"]
        client_secret = os.environ["SLACK_CLIENT_SECRET"]
        # The redirect_uri here must match the one sent in the authorization request
        # (which is NGROK_REDIRECT_URI)
        redirect_uri_for_access = NGROK_REDIRECT_URI

        client = AsyncWebClient()
        oauth_response = await client.oauth_v2_access(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri_for_access,
            code=code
        )

        installed_enterprise = oauth_response.get("enterprise") or {}
        is_enterprise_install = oauth_response.get("is_enterprise_install")
        installed_team = oauth_response.get("team") or {}
        installer = oauth_response.get("authed_user") or {}
        incoming_webhook = oauth_response.get("incoming_webhook") or {}
        bot_token = oauth_response.get("access_token")
        bot_id = None

        if bot_token is not None:
            async_client = AsyncWebClient(token=bot_token)
            auth_test = await async_client.auth_test()
            bot_id = auth_test["bot_id"]

        installation = Installation(
            app_id=oauth_response.get("app_id"),
            enterprise_id=installed_enterprise.get("id"),
            enterprise_name=installed_enterprise.get("name"),
            enterprise_url=None,
            team_id=installed_team.get("id"),
            team_name=installed_team.get("name"),
            bot_token=bot_token,
            bot_id=bot_id,
            bot_user_id=oauth_response.get("bot_user_id"),
            bot_scopes=oauth_response.get("scope"),
            user_id=installer.get("id"),
            user_token=installer.get("access_token"),
            user_scopes=installer.get("scope"),
            incoming_webhook_url=incoming_webhook.get("url"),
            incoming_webhook_channel=incoming_webhook.get("channel"),
            incoming_webhook_channel_id=incoming_webhook.get("channel_id"),
            incoming_webhook_configuration_url=incoming_webhook.get("configuration_url"),
            is_enterprise_install=is_enterprise_install,
            token_type=oauth_response.get("token_type"),
            installed_at=float(time.time()),
        )

        installation_store.save(installation)

        # You can redirect the user to a "success" page or your dashboard here
        # return RedirectResponse(url="YOUR_DASHBOARD_URL_HERE", status_code=302)
        return HTMLResponse("Thanks for installing this app!", status_code=200)

        
    
    return HTMLResponse("Invalid OAuth callback parameters.", status_code=400)

# --- Bolt Event and Command Listeners ---

# Listen for Slash Commands
@app_bolt.command("/lastmeetingsummary")
@app_bolt.command("/lastmeetingtodo")
@app_bolt.command("/lastmeetinguserstory")
async def handle_any_slash_command(ack, body, respond, client):
    await ack() # Acknowledge the command immediately
    command = body["command"]
    team_id = body["team_id"]
    channel_id = body["channel_id"]

    await handle_slash_command_logic(
        command=command,
        team_id=team_id,
        channel_id=channel_id,
        installation_store=installation_store, # Pass your custom store
        slack_client=client # Bolt's client is already configured with the correct token
    )

# Listen for App Mentions (@poc_slack)
@app_bolt.event("app_mention")
async def handle_app_mention(body, say, client, event):
    # Bolt automatically handles the acknowledgment for events when using say() or client.chat_postMessage()
    # No explicit ack() needed here as say() implicitly handles it.

    text = event.get("text")
    user_id = event.get("user")
    channel_id = event.get("channel")
    team_id = body.get("team_id")

    # Retrieve bot's user_id from auth_test response
    bot_auth_test = await client.auth_test()
    bot_user_id = bot_auth_test["user_id"] # This is the bot's user ID for the workspace

    # Clean the text (remove the bot mention)
    clean_text = text.replace(f"<@{bot_user_id}>", "").strip()

    await handle_app_mention_logic(
        clean_text=clean_text,
        user_id=user_id,
        channel_id=channel_id,
        team_id=team_id,
        installation_store=installation_store, # Pass your custom store
        slack_client=client # Bolt's client is already configured with the correct token
    )

# --- Main entry point for running the Socket Mode app ---
if __name__ == "__main__":
    import asyncio

    async def start_app():
        # This is where the event loop is already running.
        # Initialize the handler here.
        # Make sure SLACK_APP_TOKEN here is the VARIABLE, NOT A STRING LITERAL.
        handler = AsyncSocketModeHandler(app_bolt, SLACK_APP_TOKEN)
        
        print("Starting Socket Mode Handler...")
        await handler.start_async()

    # This starts the asyncio event loop and runs the start_app() coroutine
    asyncio.run(start_app())

# --- Root Path (Optional, for basic health check) ---
@app_fastapi.get("/")
async def root():
    return {"message": "Slack FastAPI App is running!"}
