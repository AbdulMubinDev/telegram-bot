#!/usr/bin/env bash
# Start the Telegram Repost Agent in Docker.
# Prerequisites: Docker and Docker Compose installed; .env and data/credentials.json configured.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Ensure .env exists
if [ ! -f .env ]; then
  echo "No .env file found."
  if [ -f .env.example.docker ]; then
    echo "Copying .env.example.docker to .env — please edit .env and add your credentials, then run this script again."
    cp .env.example.docker .env
    exit 1
  else
    echo "Create a .env file (see .env.example.docker for Docker path values) and run again."
    exit 1
  fi
fi

# Ensure data directory and credentials exist
mkdir -p data/temp data/logs
if [ ! -f data/credentials.json ]; then
  echo "Please add your Google service account JSON to: data/credentials.json"
  exit 1
fi

# First-time Telegram login: run interactively once, then use start.sh for background
if [ "${1:-}" = "login" ]; then
  echo "Running agent once for Telegram login (phone + code). After success, Ctrl+C and run ./start.sh without 'login'."
  docker compose run --rm telegram-agent python main.py
  exit 0
fi

echo "Starting Telegram Repost Agent (Docker)..."
docker compose up -d --build

echo ""
echo "First time? If you still need to log in with Telegram (phone + code), run: ./start.sh login"
echo ""
echo "Agent is running. You can control and monitor it via Telegram:"
echo "  — Open a private chat with your bot and send /status, /pause, /resume, /logs, /help"
echo "  — No port is opened; the bot connects outbound to Telegram."
echo ""
echo "Useful commands:"
echo "  docker compose logs -f          # follow logs"
echo "  docker compose ps                # status"
echo "  docker compose down              # stop"
exit 0
