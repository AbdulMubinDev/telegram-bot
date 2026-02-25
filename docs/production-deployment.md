# Production Deployment Guide — Telegram Repost Agent

This document describes how to run the Telegram repost agent in production. It is written for **deploying on an existing VPS that already serves a website**: the website stays publicly accessible; the agent runs alongside it and is **not** exposed to the public.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Security and network (UFW, no public access)](#2-security-and-network-ufw-no-public-access)
3. [Server requirements (shared VPS)](#3-server-requirements-shared-vps)
4. [Initial server setup](#4-initial-server-setup)
5. [Project setup on server](#5-project-setup-on-server)
6. [Environment configuration](#6-environment-configuration)
7. [Telegram & Google setup](#7-telegram--google-setup)
8. [Running as a system service](#8-running-as-a-system-service)
9. [Admin panel (optional)](#9-admin-panel-optional)
10. [Monitoring & logs](#10-monitoring--logs)
11. [Maintenance & recovery](#11-maintenance--recovery)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Overview

The agent runs as a long-lived process that:

- Uses a **user** Telegram session (MTProto) to read and download from a source channel
- Uses a **bot** Telegram session to post files to a destination channel
- Uses Google Drive as a staging area (upload → re-download → post to Telegram → verify → delete from Drive)
- Tracks state in `state.json` and avoids duplicates via a bundle-aware dedup index

**Deploying on an existing webserver VPS:**

- Your **website** stays the only **publicly accessible** service (HTTP/HTTPS on 80 and 443). Visitors see nothing new.
- The **Telegram agent** is **not** a website and **not** publicly accessible. It does not listen on any port and cannot be reached from the internet. Only you and the services the agent calls can “access” it:
  - **You**: SSH (your existing port) to manage the server; **Telegram admin bot** (private chat with the bot) for `/status`, `/pause`, `/logs` — no port or URL, works from anywhere including with a dynamic IP.
  - **External tools the agent needs**: Telegram (MTProto/API) and Google Drive (HTTPS). The agent only makes **outbound** connections; no inbound port or firewall rule is required for the agent.

**Summary:** Do **not** open any new UFW ports. Do **not** expose the agent via a subdomain, nginx, or any web URL. The program is only for you and for the external APIs it uses; the website remains the only public face of the server.

---

## 2. Security and network (UFW, no public access)

### 2.1 Keep your current UFW rules

You already allow only:

- **SSH** — port 22 (or 23 if you use that for SSH). Do not change this.
- **HTTP** (80) and **HTTPS** (443) for your website

**Do not open any additional ports for the Telegram agent.** The agent does not run a web server or listen on any port. Your existing rules (e.g. SSH + 80 + 443) are sufficient.

### 2.2 Why no new ports are needed

The agent only makes **outbound** connections:

- To **Telegram** (MTProto / API) — outbound
- To **Google Drive API** (HTTPS) — outbound

UFW’s default policy usually allows outbound traffic. So the agent can reach Telegram and Google without any new inbound or forward rules. No change to UFW is required.

### 2.3 Keeping the agent non‑public

- **Do not** create a website subdomain or nginx location that points to the agent. The agent has no HTTP server.
- **Do not** run any web UI or API for the agent that listens on 0.0.0.0 or a public interface.
- **Access to the agent** is only:
  - **You**: SSH (existing port) + Telegram admin bot in private chat (see [Admin panel](#9-admin-panel-optional)).
  - **Optional**: Cron or n8n on the **same** server (local, no extra ports) for keep-alive or status scripts.

This way the program is only accessible by you and by the external services it needs; the website stays the only publicly accessible service.

### 2.4 Dynamic IP (your local machine)

If your home or office IP is **dynamic**, you cannot rely on UFW source-IP whitelisting for SSH. Recommended:

- **SSH**: Use **key-based authentication** (disable password login if possible) and keep your private key secure. Optionally use **fail2ban** to limit brute force. No new port or IP allowlist is required for the agent.
- **Controlling the agent**: Use the **Telegram admin panel** (private chat with your bot: `/status`, `/pause`, `/logs`, etc.). It works from anywhere and does not depend on your IP. The only other way to control the agent is SSH to the VPS.

---

## 3. Server requirements (shared VPS)

Assumed setup:

- **OS**: Ubuntu 24.04 LTS  
- **Storage**: 75 GB NVMe (shared with OS and website)  
- **RAM**: e.g. 8 GB — enough for a website and this agent (agent is mostly I/O bound)  
- **Network**: Outbound HTTPS and Telegram (no new ports)

### 3.1 Disk budget (75 GB NVMe)

Rough split so the website and system are safe:


| Use                                  | Size (guideline)                 |
| ------------------------------------ | -------------------------------- |
| OS + system                          | ~5–10 GB                         |
| Website (code, assets, data)         | Keep your current usage + growth |
| **Agent (Python, venv, temp, logs)** | **~25–35 GB** reserved           |


Agent usage in practice:

- Python + venv: ~0.5–1 GB  
- **Temp directory**: up to **~8 GB** at peak (one large file from Telegram + one re-download from Drive)  
- Logs (with rotation): ~0.5–1 GB  
- State and session files: negligible

So reserve **at least 25–35 GB** free for the agent (e.g. don’t let the website or other apps use the whole disk). Monitor free space (e.g. `df -h` and `du -sh /opt/telegram-agent/temp`) so temp never fills during large uploads.

---

## 4. Initial server setup

### 4.1 Python on Ubuntu 24.04

Ubuntu 24.04 LTS usually includes Python 3.12. The project works with Python 3.11 or 3.12. Install a venv-capable stack if needed:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip
```

To use Python 3.11 explicitly (e.g. for consistency with other docs):

```bash
sudo apt install -y python3.11 python3.11-venv python3-pip
```

Then use `python3.11` in the venv steps below; otherwise use `python3`.

### 4.2 Create app user (recommended)

```bash
sudo useradd -m -s /bin/bash telegram-agent
```

Do **not** add this user to the web server's group or give it access to `/var/www`. The agent lives under `/opt/telegram-agent` only.

### 4.3 Project directory (outside web root)

Use a path **outside** the website document root (e.g. not under `/var/www`):

```bash
sudo mkdir -p /opt/telegram-agent
sudo chown telegram-agent:telegram-agent /opt/telegram-agent
```

Your website stays in its current directory; the agent is isolated under `/opt/telegram-agent`.

---

## 5. Project setup on server

### 5.1 Copy project files

Copy the entire `telegram` project (all `.py` files, `requirements.txt`, `.env.example`) to the server, e.g.:

```bash
# From your machine (replace with your server and path)
scp -r telegram/* user@your-vps:/opt/telegram-agent/
# Then on the server, fix ownership:
sudo chown -R telegram-agent:telegram-agent /opt/telegram-agent
```

### 5.2 Virtual environment and dependencies

Run as the agent user (or with `sudo -u telegram-agent`):

```bash
cd /opt/telegram-agent
sudo -u telegram-agent bash -c 'python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt'
```

If you installed Python 3.11 and want to use it:

```bash
sudo -u telegram-agent bash -c 'python3.11 -m venv venv && source venv/bin/activate && pip install -r requirements.txt'
```

### 5.3 Directories and credentials

```bash
sudo -u telegram-agent mkdir -p /opt/telegram-agent/temp /opt/telegram-agent/logs
```

- Place the Google service account JSON on the server (e.g. `/opt/telegram-agent/credentials.json`).
- Restrict permissions:  
`sudo chown telegram-agent:telegram-agent /opt/telegram-agent/credentials.json`  
`sudo chmod 600 /opt/telegram-agent/credentials.json`

---

## 6. Environment configuration

### 6.1 Create `.env`

```bash
sudo -u telegram-agent cp /opt/telegram-agent/.env.example /opt/telegram-agent/.env
sudo -u telegram-agent nano /opt/telegram-agent/.env
```

### 6.2 Set every variable

Use **absolute paths** under `/opt/telegram-agent`:


| Variable               | Example                                | Description                                     |
| ---------------------- | -------------------------------------- | ----------------------------------------------- |
| `TG_API_ID`            | `12345678`                             | From [my.telegram.org](https://my.telegram.org) |
| `TG_API_HASH`          | `your_api_hash`                        | From my.telegram.org                            |
| `BOT_TOKEN`            | `123456:ABC...`                        | From @BotFather                                 |
| `SOURCE_CHANNEL`       | `sourcechannel`                        | Source channel username (no @)                  |
| `DEST_CHANNEL_ID`      | `-1001234567890`                       | Destination channel ID (numeric)                |
| `DRIVE_ROOT_FOLDER_ID` | `1abc...`                              | Google Drive folder ID (from URL)               |
| `CREDENTIALS_PATH`     | `/opt/telegram-agent/credentials.json` | Service account JSON path                       |
| `TEMP_DIR`             | `/opt/telegram-agent/temp`             | Temp directory for downloads                    |
| `STATE_FILE`           | `/opt/telegram-agent/state.json`       | State file path                                 |
| `LOG_FILE`             | `/opt/telegram-agent/logs/agent.log`   | Log file path                                   |


Optional (for admin panel):


| Variable         | Example               | Description                                                    |
| ---------------- | --------------------- | -------------------------------------------------------------- |
| `ADMIN_USER_IDS` | `123456789,987654321` | Comma-separated Telegram user IDs allowed to send bot commands |


### 6.3 Secure `.env`

```bash
sudo chmod 600 /opt/telegram-agent/.env
```

---

## 7. Telegram & Google Setup

### 7.1 Telegram

1. **API credentials**: [my.telegram.org](https://my.telegram.org) → API Development Tools → get `api_id` and `api_hash`.
2. **Bot**: Message @BotFather → `/newbot` → save token. Add bot to **destination channel** as admin with “Post messages” and “Send files”.
3. **Destination channel ID**: Forward a message from the channel to @userinfobot to get the numeric ID (e.g. `-1001234567890`).
4. **First run**: Run the script once **interactively over SSH** so the **user** account can log in (phone + code). This creates `user_session.session` and `bot_session.session` under `/opt/telegram-agent`. Then you can run it under systemd.

### 7.2 Google Drive

1. Create a Google Cloud project and enable **Google Drive API**.
2. Create a **Service Account**, download JSON, save as `credentials.json` at `CREDENTIALS_PATH`.
3. In Google Drive, create a folder (e.g. `TelegramArchive`), share it with the service account email (e.g. `xxx@yyy.iam.gserviceaccount.com`) as **Editor**.
4. Open the folder in the browser; the folder ID is in the URL:
  `https://drive.google.com/drive/folders/FOLDER_ID`.

---

## 8. Running as a system service

### 8.1 Create systemd unit

```bash
sudo nano /etc/systemd/system/telegram-agent.service
```

Paste (paths assume `/opt/telegram-agent` and user `telegram-agent`):

```ini
[Unit]
Description=Telegram Repost Agent v3
After=network-online.target
WantedBy=multi-user.target

[Service]
Type=simple
User=telegram-agent
WorkingDirectory=/opt/telegram-agent
ExecStart=/opt/telegram-agent/venv/bin/python main.py
Restart=always
RestartSec=30
StandardOutput=append:/opt/telegram-agent/logs/agent.log
StandardError=append:/opt/telegram-agent/logs/agent-error.log
EnvironmentFile=/opt/telegram-agent/.env

[Install]
WantedBy=multi-user.target
```

### 8.2 Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable telegram-agent
sudo systemctl start telegram-agent
```

### 8.3 Useful commands

```bash
sudo systemctl status telegram-agent   # status
sudo systemctl stop telegram-agent   # stop
sudo systemctl start telegram-agent  # start
tail -f /opt/telegram-agent/logs/agent.log
```

### 8.4 Running with Docker (recommended on a Docker VPS)

If your VPS already runs Docker/containerd, you can run the agent in a container. **No port is opened**; the container only makes outbound connections (Telegram, Google). You control and monitor the agent via the **Telegram admin bot** (private chat) — see [Why You Don't Need to Open Any Port](./telegram-admin-panel.md#2-why-you-dont-need-to-open-any-port) in the admin panel doc.

**Steps:**

1. **Copy the project** to the server (e.g. `/opt/telegram-agent` or your home). Ensure it contains `Dockerfile`, `docker-compose.yml`, `start.sh`, and all `.py` files.
2. **Create `.env`** for Docker (paths must be the ones used inside the container):
  ```bash
   cp .env.example.docker .env
   nano .env   # set TG_API_ID, TG_API_HASH, BOT_TOKEN, SOURCE_CHANNEL, DEST_CHANNEL_ID, DRIVE_ROOT_FOLDER_ID, ADMIN_USER_IDS
  ```
   Do **not** change `CREDENTIALS_PATH`, `TEMP_DIR`, `STATE_FILE`, or `LOG_FILE` in `.env` — they must stay as in `.env.example.docker` (`/app/data/...`) so the container finds them.
3. **Put the Google service account JSON** in the `data/` folder:
  ```bash
   mkdir -p data
   # Copy your credentials file to data/credentials.json
  ```
4. **First-time Telegram login** (once per machine): the agent needs your Telegram user account (phone + code) to read the source channel. **Do not** start in background until this is done.
  - If the container is already running in background: `docker compose down`
  - Run **interactively** (so you can type phone and code): `./start.sh login`
  - When prompted, enter your phone number (with country code) and the code Telegram sends you. When you see "Both Telegram clients connected", press Ctrl+C. Session files are saved in `data/` and persist.
5. **Start the agent in the background:**
  ```bash
   ./start.sh
  ```
   The script creates `data/temp` and `data/logs`, checks for `.env` and `data/credentials.json`, then runs `docker compose up -d --build`.
6. **Control and monitor from Telegram:** Open a **private chat** with your bot and send `/status`, `/pause`, `/resume`, `/logs`, `/help`. No port or URL on the server is needed; the bot connects outbound to Telegram and receives your messages over that connection.

**Useful Docker commands:**

```bash
docker compose logs -f      # follow log
docker compose ps           # status
docker compose down         # stop
./start.sh                  # start again
```

**Permissions (if you cloned or copied with sudo):** If the project is owned by root, your user may get "permission denied" when running `./start.sh` or `docker compose logs`. Fix ownership so your user can run Docker without sudo:

```bash
sudo chown -R $(whoami):$(whoami) /opt/telegram-bot
```

Then run `./start.sh` and `docker compose logs -f` as your user (no sudo).

**Docker .env paths:** When running in Docker, `.env` must use the **container** paths from `.env.example.docker`: `CREDENTIALS_PATH=/app/data/credentials.json`, `TEMP_DIR=/app/data/temp`, `STATE_FILE=/app/data/state.json`, `LOG_FILE=/app/data/logs/agent.log`. If you used a non-Docker `.env` (e.g. `/opt/telegram-agent/...`), the container will try to write to paths that don’t exist and you’ll see errors like "Could not create lock file". Copy `.env.example.docker` to `.env`, fill in your secrets, and leave those four path variables unchanged.

---

## 9. Admin panel (optional)

You can use the **same bot** as an admin panel so **only you** (and other listed Telegram user IDs) can control the agent — no public website or port involved.

- **Setup**: Add `ADMIN_USER_IDS=YOUR_TELEGRAM_USER_ID` to `.env`. Get your user ID by messaging @userinfobot.
- **Usage**: In Telegram, open a **private chat** with your bot and send commands there (`/status`, `/pause`, `/resume`, `/retry_failed`, `/logs`). See [Telegram Admin Panel](./telegram-admin-panel.md).
- If `ADMIN_USER_IDS` is not set, the bot does not listen for admin commands and is used only for posting to the destination channel.

Access to the agent remains: **you** (SSH + Telegram private chat) and **external services** the agent calls (Telegram, Google) over outbound connections.

---

## 10. Monitoring & logs

### 10.1 Log rotation

So agent logs don’t fill your 75 GB disk:

```bash
sudo nano /etc/logrotate.d/telegram-agent
```

Contents:

```
/opt/telegram-agent/logs/*.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    copytruncate
}
```

### 10.2 Optional: cron keep-alive

systemd already restarts the agent on failure. If you want an extra safeguard, run a cron job as root (or your user) — **no new port**, just a local check:

```bash
sudo crontab -e
```

Add:

```
*/5 * * * * systemctl is-active --quiet telegram-agent || systemctl start telegram-agent
```

### 10.3 Optional: daily status (local or Telegram)

You can run a status script locally (e.g. cron) or rely on the Telegram admin `/status` command. Example local script (no network listener):

```bash
#!/bin/bash
STATE=/opt/telegram-agent/state.json
if [ -f "$STATE" ]; then
  python3 -c "
import json
with open('$STATE') as f:
  s = json.load(f)
b = s.get('bundles', {})
incomplete = [k for k,v in b.items() if v.get('parts_failed')]
print('Processed:', s['total_processed'])
print('Dupes skipped:', s.get('skipped_duplicates', 0))
print('Failed:', len(s['failed_ids']))
print('Bundles:', len(b), '| With failures:', len(incomplete))
"
fi
```

---

## 11. Maintenance & recovery

### 11.1 Retry failed posts

From the server (or via admin `/retry_failed` in Telegram):

```bash
cd /opt/telegram-agent
sudo -u telegram-agent /opt/telegram-agent/venv/bin/python retry_failed.py
sudo systemctl restart telegram-agent
```

### 11.2 Clear state and start over (use with care)

Only if you want to reprocess everything (will re-upload duplicates unless you clear the destination channel or accept them):

```bash
sudo -u telegram-agent cp /opt/telegram-agent/state.json /opt/telegram-agent/state.json.bak
# Then edit state.json (e.g. last_processed_id=0, processed_ids=[], etc.)
```

### 11.3 Session re-auth

If you get `AuthKeyError` or session invalid:

1. Stop the agent: `sudo systemctl stop telegram-agent`
2. Remove session files:
  `sudo rm /opt/telegram-agent/user_session.session /opt/telegram-agent/bot_session.session`
3. Run once **interactively over SSH**:
  `cd /opt/telegram-agent && sudo -u telegram-agent /opt/telegram-agent/venv/bin/python main.py`  
   Complete phone + code login.
4. Ctrl+C, then: `sudo systemctl start telegram-agent`

---

## 12. Troubleshooting


| Symptom                                 | What to check                                                                                                                  |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Agent exits immediately                 | `.env` missing or wrong; run without systemd to see traceback; check `agent-error.log`.                                        |
| “Another instance may be running”       | Another process is using the same lock file; kill the other process or remove `agent.lock` if the process is gone.             |
| ChannelPrivateError / can’t read source | Source channel username correct; user account in the channel if it’s private.                                                  |
| ChatWriteForbiddenError                 | Bot not admin in destination channel or missing “Post messages” / “Send files”.                                                |
| Drive 403 / upload fails                | Drive folder shared with service account email; Drive API enabled.                                                             |
| Disk full                               | Free space in `TEMP_DIR`; clear `temp/`; ensure enough of the 75 GB is reserved for the agent; reduce log retention.           |
| FloodWaitError                          | Handled by script (wait + retry); if frequent, reduce posting rate or wait.                                                    |
| Website affected                        | Agent runs as `telegram-agent` under `/opt/telegram-agent`; ensure no nginx/web root points there and no new ports are opened. |


For more errors and fixes, see the main technical docs (`telegram-agent-technical-docs-v3.md`) “Common Errors & Fixes” section.

---

*Production deployment guide for Telegram Repost Agent v3 — shared VPS (Ubuntu 24.04, 75 GB NVMe, UFW 22/80/443)*