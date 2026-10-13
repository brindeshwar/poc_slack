from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "socket": single workspace over Socket Mode (no public URL needed; best for development).
    # "http":   multi-workspace over HTTP with the "Add to Slack" OAuth flow.
    slack_mode: Literal["socket", "http"] = "socket"

    slack_bot_token: SecretStr | None = None  # socket mode
    slack_app_token: SecretStr | None = None  # socket mode (xapp-...)
    slack_signing_secret: SecretStr | None = None  # http mode
    slack_client_id: str | None = None  # http mode
    slack_client_secret: SecretStr | None = None  # http mode
    installation_dir: str = "./installations"

    mcp_server_url: str = "http://127.0.0.1:8001/mcp"

    google_api_key: SecretStr
    gemini_model: str = "gemini-3.5-flash-lite"
    # minimal | low | medium | high. "low" helps the agent pick tools reliably at Flash-Lite cost.
    gemini_thinking_level: Literal["minimal", "low", "medium", "high"] = "low"

    host: str = "127.0.0.1"
    port: int = 3000

    @model_validator(mode="after")
    def _mode_requirements(self) -> "Settings":
        required = (
            {"slack_bot_token": self.slack_bot_token, "slack_app_token": self.slack_app_token}
            if self.slack_mode == "socket"
            else {
                "slack_signing_secret": self.slack_signing_secret,
                "slack_client_id": self.slack_client_id,
                "slack_client_secret": self.slack_client_secret,
            }
        )
        missing = [name.upper() for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"SLACK_MODE={self.slack_mode} requires: {', '.join(missing)}")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
