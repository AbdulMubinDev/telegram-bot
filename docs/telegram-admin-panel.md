# Telegram Bot as Admin Panel

The same bot that posts to your destination channel can act as an **admin panel**: you send commands to the bot in a **private chat**, and the bot replies with status, logs, or confirms actions (pause, resume, retry failed). Only Telegram user IDs listed in `ADMIN_USER_IDS` can use these commands.

---

## Table of Contents

1. [How It Works](#1-how-it-works)
2. [Why You Don’t Need to Open Any Port](#2-why-you-dont-need-to-open-any-port)
3. [Setup](#3-setup)
3. [Getting Your Telegram User ID](#3-getting-your-telegram-user-id)
4. [Configuration](#4-configuration)
5. [Admin Commands](#5-admin-commands)
6. [Connecting the Script to the Bot](#6-connecting-the-script-to-the-bot)
7. [Security](#7-security)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. How It Works

- The **repost agent** runs on your server and uses two Telegram connections:
  - **User client**: reads and downloads from the source channel (MTProto).
  - **Bot client**: posts files to the destination channel **and** listens for private messages.
- When you send a **private message** to the bot (e.g. `/status`), the script checks whether your Telegram user ID is in the allowed list (`ADMIN_USER_IDS`). If yes, it runs the command and replies in the same chat.
- No separate “admin bot” is needed: the same `BOT_TOKEN` is used for both posting to the channel and handling admin commands. The script is already “connected” to the bot because it starts the bot client with that token.

```
┌─────────────────┐     private chat      ┌──────────────────┐
│  You (Telegram)  │ ───────────────────► │  Your bot        │
│  /status        │                       │  (BOT_TOKEN)      │
└─────────────────┘ ◄─────────────────── └────────┬─────────┘
                     reply with status              │
                                                    │ same connection
                                                    ▼
                                            ┌───────────────┐
                                            │ Repost agent  │
                                            │ (main.py)     │
                                            └───────────────┘
```

---

## 2. Why You Don’t Need to Open Any Port

The agent runs on your server (or in Docker) and **only makes outbound connections**. You never open an inbound port for the bot. So how does the bot receive your commands?

- The **bot client** inside the agent opens a connection **from your server to Telegram’s servers** (outbound). That connection stays open (long polling or similar).
- When you send a message to the bot in the Telegram app, your message goes to **Telegram’s servers**, not to your VPS.
- Telegram then **delivers your message to the bot** over the connection that the agent already has open. So the flow is: **You → Telegram → (over existing outbound connection) → Agent**. Your VPS never accepts an incoming connection; it only talks to Telegram outbound.
- The bot’s reply goes back: **Agent → Telegram → You**. Again, no inbound port on your side.

So you can control and monitor the agent from anywhere (phone, laptop, dynamic IP) by simply opening Telegram and chatting with your bot. No firewall change, no port opening, and no need to expose the agent as a website.

---

## 3. Setup

1. **Bot already set up**  
   You already have a bot from @BotFather and use `BOT_TOKEN` in the script. The bot is added as admin to the destination channel. No new bot is required.

2. **Get your Telegram user ID**  
   You need your numeric user ID so the script can treat you as an admin. See [Getting Your Telegram User ID](#3-getting-your-telegram-user-id).

3. **Add admin IDs to environment**  
   Set `ADMIN_USER_IDS` in your `.env` to a comma-separated list of allowed user IDs. Example:
   ```env
   ADMIN_USER_IDS=123456789,987654321
   ```
   If `ADMIN_USER_IDS` is empty or not set, the bot **does not** handle any admin commands (it only posts to the destination channel).

4. **Start the agent**  
   When the agent runs, it starts the bot client and registers the admin command handler. After that, open a **private chat** with your bot and send `/help` or `/status`.

---

## 4. Getting Your Telegram User ID

**Option A — @userinfobot**

1. Open Telegram and search for **@userinfobot**.
2. Start the bot (e.g. Send any message).
3. The bot replies with your **Id** (a number like `123456789`). That is your user ID.

**Option B — @getidsbot**

1. Search for **@getidsbot** and start it.
2. It will show your user ID in the reply.

Use this number in `ADMIN_USER_IDS` (no spaces, no @). To add more admins, add their user IDs separated by commas.

---

## 5. Configuration

In your `.env` (or environment):

| Variable          | Required | Example              | Description                                      |
|-------------------|----------|----------------------|--------------------------------------------------|
| `ADMIN_USER_IDS`  | No       | `123456789,987654321` | Comma-separated Telegram user IDs for admins.   |

- **If set**: the bot responds to admin commands only from these user IDs in private chat.
- **If not set or empty**: no admin commands are handled; the bot is used only for posting to the destination channel.

No code change is needed: the script reads `ADMIN_USER_IDS` at startup and, if present, registers the admin handler on the same bot client.

---

## 6. Admin Commands

Send these in a **private chat** with your bot (not in the channel).

| Command         | Description |
|-----------------|-------------|
| **/status**     | Replies with a short summary: mode, processed count, duplicates skipped, failed count, bundles tracked, and any bundles with failed parts. |
| **/pause**      | Pauses processing. New posts are still queued (in live mode) but not processed until you send `/resume`. Useful for maintenance or to avoid processing during peak times. |
| **/resume**     | Resumes processing after a pause. |
| **/retry_failed** | Resets failed posts in `state.json` so they can be retried. The agent does **not** restart automatically; restart the service (or run `retry_failed.py` and restart) to reprocess those messages. |
| **/logs**       | Sends the last part of the log file (path from `LOG_FILE`). Useful for quick checks from your phone. |
| **/help**       | Lists these commands. |

- Commands are **case-insensitive** (e.g. `/Status` works).
- Only users whose ID is in `ADMIN_USER_IDS` get a reply; others are ignored.

---

## 7. Connecting the Script to the Bot

The script is **already** connected to the bot:

1. **BOT_TOKEN** in `.env` is the token of the bot you use for the destination channel.
2. **main.py** starts the bot client with that token:
   ```python
   await bot_client.start(bot_token=BOT_TOKEN)
   ```
3. **admin_handler.py** registers a handler on that same `bot_client` for private messages and replies in the same chat.

So:

- **Posting to channel**: script uses `bot_client.send_file(DEST_CHANNEL_ID, ...)`.
- **Admin panel**: script uses `bot_client.on(events.NewMessage(incoming=True, func=...))` and `event.reply(...)` in private chat.

No extra “connection” step is required. Once `ADMIN_USER_IDS` is set and the agent is running, open a private chat with the bot and send `/help` or `/status` to use the admin panel.

---

## 8. Security

- **Who can run commands**  
  Only Telegram user IDs in `ADMIN_USER_IDS` can trigger admin commands. Everyone else is ignored (no reply, no error).

- **Where commands work**  
  Commands are handled only in **private** chats with the bot. Messages in groups or in the destination channel do **not** run admin logic.

- **Secrets**  
  Keep `.env` (and `BOT_TOKEN`, `ADMIN_USER_IDS`) only on the server and out of version control. Restrict file permissions, e.g. `chmod 600 .env`.

- **Logs**  
  `/logs` sends a portion of the log file. Avoid logging secrets; if you do, restrict who is in `ADMIN_USER_IDS`.

---

## 9. Troubleshooting

| Problem | What to check |
|--------|----------------|
| Bot doesn’t reply to /status or /help | 1) `ADMIN_USER_IDS` is set in `.env`. 2) Your user ID is correct and in that list. 3) You’re in a **private** chat with the bot. 4) Agent is running (e.g. `systemctl status telegram-agent`). |
| “Error: ...” in reply | Check server logs (`agent.log` or `agent-error.log`). Common causes: missing `STATE_FILE`/`LOG_FILE`, permission errors, or exception in command logic. |
| /pause or /resume doesn’t seem to work | In live mode, processing pauses after the current file; in historical mode, it pauses before the next message. Wait a few seconds and send /status to confirm mode and state. |
| /retry_failed says “Reset N” but nothing reprocesses | The script only resets state; it does not restart. Restart the agent (e.g. `sudo systemctl restart telegram-agent`) so it fetches and reprocesses the reset messages. |
| Bot replies in channel instead of private | Commands are only handled in private chat. Always open the bot’s profile and “Start” or use the private chat; do not send commands in the destination channel. |

---

*Telegram Admin Panel — use your bot as admin panel for the repost agent*
