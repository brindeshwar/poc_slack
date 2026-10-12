"""Kept so `python app.py` still starts the bot. Prefer `uv run slack-bot`."""

from slack_bot.app import main

if __name__ == "__main__":
    main()
