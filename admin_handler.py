"""
Telegram bot admin panel: handle private commands from allowed users.
Commands: /status, /pause, /resume, /retry_failed, /logs
"""
import os
from telethon import events
from telethon.errors import MessageTooLongError
from dotenv import load_dotenv
from state_manager import load_state
from retry_failed import run_retry_failed

load_dotenv()
LOG_FILE = os.getenv('LOG_FILE', 'logs/agent.log')
MAX_LOG_LINES = 50
MAX_MESSAGE_LEN = 4000


def get_admin_ids():
    """Parse ADMIN_USER_IDS from env (comma-separated integers)."""
    raw = os.getenv('ADMIN_USER_IDS', '').strip()
    if not raw:
        return set()
    ids = set()
    for part in raw.split(','):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


def format_status(state: dict) -> str:
    bundles = state.get('bundles', {})
    incomplete = [(k, v) for k, v in bundles.items() if v.get('parts_failed')]
    lines = [
        "📊 **Status**",
        f"Mode: `{state.get('mode', '?')}`",
        f"Processed: {state.get('total_processed', 0)}",
        f"Dupes skipped: {state.get('skipped_duplicates', 0)}",
        f"Failed: {len(state.get('failed_ids', []))}",
        f"Bundles tracked: {len(bundles)}",
        f"Bundles with failures: {len(incomplete)}",
    ]
    if incomplete:
        lines.append("\n⚠️ Incomplete bundles:")
        for bid, b in incomplete[:5]:
            lines.append(f"  • {b.get('display_name', bid)} — failed parts: {b.get('parts_failed', [])}")
    return "\n".join(lines)


async def register_admin_handlers(bot_client, paused_ref: list):
    """
    Register handlers for admin commands in private chat.
    paused_ref: single-element list [False]; set paused_ref[0]=True/False for /pause, /resume.
    """
    admin_ids = get_admin_ids()
    if not admin_ids:
        return

    @bot_client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def admin_command(event):
        if event.sender_id not in admin_ids:
            return
        text = (event.message.text or "").strip().lower()
        if not text.startswith('/'):
            return
        cmd = text.split()[0] if text else ""
        try:
            if cmd == '/status':
                state = load_state()
                msg = format_status(state)
                await event.reply(msg, parse_mode='md')
            elif cmd == '/pause':
                paused_ref[0] = True
                await event.reply("⏸ Paused. New posts will be queued but not processed until /resume.")
            elif cmd == '/resume':
                paused_ref[0] = False
                await event.reply("▶️ Resumed. Processing continues.")
            elif cmd == '/retry_failed':
                n = run_retry_failed()
                await event.reply(f"🔄 Reset {n} failed post(s) for retry. Restart the agent to reprocess them.")
            elif cmd == '/logs':
                if not os.path.exists(LOG_FILE):
                    await event.reply("No log file found.")
                    return
                with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
                    lines = f.readlines()
                tail = lines[-MAX_LOG_LINES:] if len(lines) > MAX_LOG_LINES else lines
                log_text = "".join(tail).strip()
                if len(log_text) > MAX_MESSAGE_LEN:
                    log_text = "...\n" + log_text[-MAX_MESSAGE_LEN:]
                if not log_text:
                    log_text = "(empty)"
                try:
                    await event.reply(f"```\n{log_text}\n```", parse_mode='md')
                except MessageTooLongError:
                    await event.reply("Logs too long; try reducing MAX_LOG_LINES or check server.")
            elif cmd == '/help':
                help_text = (
                    "**Admin commands**\n"
                    "/status — agent state summary\n"
                    "/pause — pause processing\n"
                    "/resume — resume processing\n"
                    "/retry_failed — reset failed posts for retry\n"
                    "/logs — last lines of log file\n"
                    "/help — this message"
                )
                await event.reply(help_text, parse_mode='md')
        except Exception as e:
            await event.reply(f"Error: {str(e)}")
