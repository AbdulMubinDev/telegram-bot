# Telegram Repost Agent — Documentation

| Document | Description |
|----------|-------------|
| **[Production Deployment](./production-deployment.md)** | How to run the script in production: server setup, environment, systemd service, **Docker (with `start.sh`)**, monitoring, and troubleshooting. |
| **[Telegram Admin Panel](./telegram-admin-panel.md)** | How to use your Telegram bot as an admin panel (no port to open), get your user ID, set `ADMIN_USER_IDS`, and use `/status`, `/pause`, `/resume`, `/retry_failed`, `/logs`. |

**Docker quick start:** Copy project → `cp .env.example.docker .env` and fill in credentials → put `credentials.json` in `data/` → `./start.sh login` (first-time Telegram login) → `./start.sh` to run. Control via private chat with your bot.
