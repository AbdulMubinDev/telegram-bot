# Telegram Repost Agent v3 — production image
FROM python:3.11-slim

WORKDIR /app

# Install dependencies (no build deps needed for these packages)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code (entry point + package)
COPY main.py ./
COPY telegram_agent/ telegram_agent/

# Persistent data (state, sessions, temp, logs, credentials) live in /app/data (mounted)
RUN mkdir -p /app/data/temp /app/data/logs

# Run as non-root when possible (optional; session files must be writable)
# USER 1000:1000

ENTRYPOINT ["python", "-u", "main.py"]
