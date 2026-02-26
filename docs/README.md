# Telegram Repost Agent — Documentation

**Project layout:** Application code lives in the `telegram_agent/` package; `main.py` at the project root is the entry point. Specs and technical docs are in `docs/specs/`. Tests are in `tests/` (run from project root: `python tests/test_bundle_detector.py` or `python -m pytest tests/`).

| Document | Description |
|----------|-------------|
| **[Production Deployment](./production-deployment.md)** | How to run the script in production: server setup, environment, systemd service, **Docker (with `start.sh`)**, monitoring, and troubleshooting. |
| **[Telegram Admin Panel](./telegram-admin-panel.md)** | How to use your Telegram bot as an admin panel (no port to open), get your user ID, set `ADMIN_USER_IDS`, and use `/status`, `/pause`, `/resume`, `/retry_failed`, `/logs`. |
| **[Specs](./specs/)** | `telegram-user-script-spec.md`, `telegram-agent-technical-docs-v3.md` — functional and technical specifications. |

**Docker quick start:** Copy project → `cp .env.example.docker .env` and fill in credentials → put `credentials.json` in `data/` → `./start.sh login` (first-time Telegram login) → `./start.sh` to run. Control via private chat with your bot.
