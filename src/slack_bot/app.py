import asyncio
import logging

from fastapi import FastAPI, Request
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp
from slack_bolt.oauth.async_oauth_settings import AsyncOAuthSettings
from slack_sdk.oauth.installation_store import FileInstallationStore
from slack_sdk.oauth.state_store import FileOAuthStateStore

from slack_bot.agent import MeetingAgent
from slack_bot.config import Settings, get_settings
from slack_bot.handlers import register
from slack_bot.hub import HubClient

logger = logging.getLogger(__name__)

BOT_SCOPES = ["app_mentions:read", "chat:write", "commands"]


def build_bolt_app(settings: Settings) -> AsyncApp:
    if settings.slack_mode == "socket":
        assert settings.slack_bot_token is not None  # enforced by Settings
        app = AsyncApp(
            token=settings.slack_bot_token.get_secret_value(),
            signing_secret=(
                settings.slack_signing_secret.get_secret_value()
                if settings.slack_signing_secret
                else None
            ),
            # Socket Mode traffic is authenticated by the app-level token, not request signatures.
            request_verification_enabled=False,
        )
    else:
        assert settings.slack_signing_secret and settings.slack_client_secret
        app = AsyncApp(
            signing_secret=settings.slack_signing_secret.get_secret_value(),
            oauth_settings=AsyncOAuthSettings(
                client_id=settings.slack_client_id,
                client_secret=settings.slack_client_secret.get_secret_value(),
                scopes=BOT_SCOPES,
                installation_store=FileInstallationStore(base_dir=settings.installation_dir),
                state_store=FileOAuthStateStore(
                    expiration_seconds=600, base_dir=f"{settings.installation_dir}/.states"
                ),
            ),
        )

    hub = HubClient(settings.mcp_server_url)
    agent = MeetingAgent(
        hub, api_key=settings.google_api_key.get_secret_value(), model=settings.gemini_model
    )
    register(app, hub, agent)
    return app


def build_http_app(bolt_app: AsyncApp) -> FastAPI:
    """HTTP mode: Slack events + the built-in 'Add to Slack' OAuth flow."""
    handler = AsyncSlackRequestHandler(bolt_app)
    api = FastAPI(title="ListenLoom Slack bot")

    @api.post("/slack/events")
    async def events(request: Request):
        return await handler.handle(request)

    @api.get("/slack/install")
    async def install(request: Request):
        return await handler.handle(request)

    @api.get("/slack/oauth_redirect")
    async def oauth_redirect(request: Request):
        return await handler.handle(request)

    @api.get("/health")
    async def health():
        return {"status": "ok"}

    return api


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = get_settings()
    bolt_app = build_bolt_app(settings)
    logger.info("Using meeting hub at %s", settings.mcp_server_url)

    if settings.slack_mode == "socket":
        assert settings.slack_app_token is not None
        handler = AsyncSocketModeHandler(bolt_app, settings.slack_app_token.get_secret_value())
        logger.info("Starting in Socket Mode")
        asyncio.run(handler.start_async())
    else:
        import uvicorn

        logger.info("Starting HTTP mode on %s:%d", settings.host, settings.port)
        uvicorn.run(build_http_app(bolt_app), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
