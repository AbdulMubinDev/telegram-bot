"""
Entry point for Telegram Repost Agent. Loads config (BASE_DIR + path resolution) then runs the agent.
"""
from dotenv import load_dotenv

load_dotenv()
from telegram_agent import config  # noqa: E402, F401 — resolve paths before run
from telegram_agent.run import main

if __name__ == '__main__':
    main()
