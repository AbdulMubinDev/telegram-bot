"""
Telegram Repost Agent v3.0 — Core orchestrator.
User-script: MTProto user client reads source channel; bot client posts to destination.
Bundle-aware dedup, Drive staging, upload verification.
"""
import asyncio
import os
import sys
import logging
import time
from logging.handlers import TimedRotatingFileHandler
from telethon import events
from telethon.errors import FloodWaitError

from . import config  # noqa: F401 — resolve paths before other imports
from .telegram_handler import (
    get_user_client, get_bot_client, get_all_posts,
    download_file, upload_file, get_last_dest_post,
    get_filename, get_size, USER_SESSION_PATH
)
from .drive_handler import (
    upload_to_drive, download_from_drive,
    get_last_drive_file_in_folder, delete_from_drive
)
from .bundle_detector import detect_bundle
from .dedup_engine import BundleDeduplicationEngine
from .state_manager import (
    load_state, save_state,
    mark_processed, mark_duplicate, mark_failed
)
from .admin_handler import register_admin_handlers

USE_DRIVE_STAGING = os.getenv('USE_DRIVE_STAGING', 'false').lower() in ('true', '1', 'yes')
CONCURRENT_FILES = max(1, int(os.getenv('CONCURRENT_FILES', '2')))  # parallel downloads for large files (2–4)

REQUIRED_ENV = [
    'TG_API_ID', 'TG_API_HASH', 'BOT_TOKEN', 'SOURCE_CHANNEL',
    'DEST_CHANNEL_ID', 'TEMP_DIR', 'STATE_FILE', 'LOG_FILE'
]
REQUIRED_ENV_DRIVE = ['DRIVE_ROOT_FOLDER_ID', 'CREDENTIALS_PATH']


def validate_env():
    required = REQUIRED_ENV + (REQUIRED_ENV_DRIVE if USE_DRIVE_STAGING else [])
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print(f"ERROR: Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        print("Set them in .env or the environment. See .env.example.", file=sys.stderr)
        sys.exit(1)


def setup_lockfile():
    """Create lockfile to prevent two instances (spec Part 10 rule 8)."""
    state_file = os.getenv('STATE_FILE', 'state.json')
    lock_dir = os.path.dirname(os.path.abspath(state_file))
    if lock_dir and not os.path.isdir(lock_dir):
        lock_dir = os.getenv('TEMP_DIR', os.getcwd())
    lock_path = os.path.join(lock_dir, 'agent.lock')
    try:
        os.makedirs(lock_dir, exist_ok=True)
    except OSError:
        pass
    if os.path.exists(lock_path):
        try:
            with open(lock_path, 'r') as f:
                old_pid = int(f.read().strip())
        except (ValueError, OSError):
            old_pid = None
        if old_pid is not None:
            try:
                os.kill(old_pid, 0)
            except (ProcessLookupError, PermissionError):
                pass
            else:
                print(f"ERROR: Another instance may be running (PID {old_pid}). Lock file: {lock_path}", file=sys.stderr)
                sys.exit(1)
        try:
            os.remove(lock_path)
        except OSError:
            pass
    try:
        with open(lock_path, 'w') as f:
            f.write(str(os.getpid()))
        return lock_path
    except OSError as e:
        print(f"ERROR: Could not create lock file: {e}", file=sys.stderr)
        sys.exit(1)


def remove_lockfile(lock_path: str):
    try:
        if lock_path and os.path.exists(lock_path):
            os.remove(lock_path)
    except OSError:
        pass


def setup_logging():
    """Log to console and rotating file (daily, 14 days — spec Part 9)."""
    log_file = os.getenv('LOG_FILE', 'logs/agent.log')
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    fmt = '%(asctime)s [%(levelname)s] %(message)s'
    file_handler = TimedRotatingFileHandler(
        log_file, when='midnight', backupCount=14, encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter(fmt))
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(fmt))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    return logging.getLogger(__name__)


RETRY_DELAYS = [5, 15, 45]
MAX_RETRIES = 3

TEMP_DIR = os.getenv('TEMP_DIR')
LOG_FILE = os.getenv('LOG_FILE')
BOT_TOKEN = os.getenv('BOT_TOKEN')
SOURCE_CHANNEL = os.getenv('SOURCE_CHANNEL')

log = None  # set in main()


async def download_file_with_retry(user_client, message, filename: str) -> str:
    """Download from Telegram with up to 3 retries and exponential backoff."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return await download_file(user_client, message, filename)
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt]
                log.warning(f"Download attempt {attempt + 1} failed: {e}. Retrying in {delay}s.")
                await asyncio.sleep(delay)
    raise last_error


def upload_to_drive_with_retry(file_path: str, filename: str, bundle_id: str) -> str:
    """Upload to Drive with up to 3 retries."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return upload_to_drive(file_path, filename, bundle_id)
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt]
                log.warning(f"Drive upload attempt {attempt + 1} failed: {e}. Retrying in {delay}s.")
                time.sleep(delay)
    raise last_error


async def process_message(user_client, bot_client, message, state, dedup, state_lock=None):
    msg_id = message.id
    start_time = time.monotonic()

    if state_lock:
        async with state_lock:
            state = load_state()
            if msg_id in state['processed_ids']:
                return state
            if not message.document:
                log.info(f"[{msg_id}] No file — skipping")
                return mark_processed(state, msg_id)
            filename = get_filename(message)
            file_size = get_size(message)
            if not filename:
                log.info(f"[{msg_id}] Document with no filename — skipping")
                return mark_processed(state, msg_id)
            bundle_info = detect_bundle(filename)
            if dedup.is_duplicate(filename, file_size):
                log.info(f"[{msg_id}] DUPLICATE — skipping.")
                state = mark_duplicate(state, msg_id)
                log.info(f"[{msg_id}] Total time: {time.monotonic() - start_time:.1f}s")
                return state
            # committed to process; release lock for download/upload
    else:
        if msg_id in state['processed_ids']:
            return state
        if not message.document:
            log.info(f"[{msg_id}] No file — skipping")
            return mark_processed(state, msg_id)
        filename = get_filename(message)
        file_size = get_size(message)
        if not filename:
            log.info(f"[{msg_id}] Document with no filename — skipping")
            return mark_processed(state, msg_id)
        bundle_info = detect_bundle(filename)
        size_mb = file_size / (1024 * 1024)
        log.info(
            f"[{msg_id}] File: '{filename}' ({size_mb:.1f} MB) | "
            f"Bundle: '{bundle_info['bundle_id']}' | "
            f"Part: {bundle_info['part_number'] if bundle_info['is_part'] else 'standalone'}"
        )
        if dedup.is_duplicate(filename, file_size):
            log.info(f"[{msg_id}] DUPLICATE — skipping.")
            state = mark_duplicate(state, msg_id)
            log.info(f"[{msg_id}] Total time: {time.monotonic() - start_time:.1f}s")
            return state

    size_mb = file_size / (1024 * 1024)
    log.info(
        f"[{msg_id}] File: '{filename}' ({size_mb:.1f} MB) | "
        f"Bundle: '{bundle_info['bundle_id']}' | "
        f"Part: {bundle_info['part_number'] if bundle_info['is_part'] else 'standalone'}"
    )

    local_dl = None
    local_ul = None
    drive_file_id = None
    caption = filename  # consistent caption for matching by filename later

    try:
        step_total = 5 if USE_DRIVE_STAGING else 2
        log.info(f"[{msg_id}] 1/{step_total} Downloading from Telegram...")
        safe_filename = filename.replace('/', '_').replace('\\', '_')
        local_dl = await download_file_with_retry(
            user_client, message, f"dl_{msg_id}_{safe_filename}"
        )
        expected_size = get_size(message)
        if os.path.getsize(local_dl) != expected_size:
            raise RuntimeError(
                f"Size mismatch: disk={os.path.getsize(local_dl)}, expected={expected_size}"
            )

        if USE_DRIVE_STAGING:
            log.info(f"[{msg_id}] 2/5 Uploading to Drive folder '{bundle_info['bundle_id']}'...")
            drive_file_id = upload_to_drive_with_retry(local_dl, filename, bundle_info['bundle_id'])
            os.remove(local_dl)
            local_dl = None

            log.info(f"[{msg_id}] 3/5 Re-downloading from Drive...")
            local_ul = os.path.join(TEMP_DIR, f"up_{msg_id}_{safe_filename}")
            download_from_drive(drive_file_id, local_ul)

            log.info(f"[{msg_id}] 4/5 Uploading to destination channel...")
            try:
                await upload_file(bot_client, local_ul, caption=caption, user_client=user_client, file_name=filename)
            except FloodWaitError as e:
                log.warning(f"[{msg_id}] FloodWait {e.seconds}s — waiting then retrying...")
                await asyncio.sleep(e.seconds + 5)
                await upload_file(bot_client, local_ul, caption=caption, user_client=user_client, file_name=filename)
            os.remove(local_ul)
            local_ul = None

            log.info(f"[{msg_id}] 5/5 Verifying upload...")
            drive_meta = get_last_drive_file_in_folder(bundle_info['bundle_id'])
            tg_last = await get_last_dest_post(user_client)
            drive_name = drive_meta.get('name', '').lower().strip()
            tg_name = tg_last.get('filename', '').lower().strip()
            drive_size = int(drive_meta.get('size', -1))
            tg_size = tg_last.get('size', -2)
            if drive_name == tg_name and drive_size == tg_size:
                log.info(f"[{msg_id}] Verification PASSED — deleting from Drive.")
                delete_from_drive(drive_file_id)
            else:
                log.warning(
                    f"[{msg_id}] Verification MISMATCH — Drive file kept as backup. "
                    f"Drive='{drive_name}'({drive_size}B) | TG='{tg_name}'({tg_size}B)"
                )
        else:
            log.info(f"[{msg_id}] 2/{step_total} Uploading to destination channel...")
            try:
                await upload_file(bot_client, local_dl, caption=caption, user_client=user_client, file_name=filename)
            except FloodWaitError as e:
                log.warning(f"[{msg_id}] FloodWait {e.seconds}s — waiting then retrying...")
                await asyncio.sleep(e.seconds + 5)
                await upload_file(bot_client, local_dl, caption=caption, user_client=user_client, file_name=filename)
            os.remove(local_dl)
            local_dl = None

        if state_lock:
            async with state_lock:
                state = load_state()
                dedup.mark_uploaded(filename, file_size)
                state = mark_processed(state, msg_id, bundle_info)
                save_state(state)
        else:
            dedup.mark_uploaded(filename, file_size)
            state = mark_processed(state, msg_id, bundle_info)
        elapsed = time.monotonic() - start_time
        log.info(f"[{msg_id}] Done. Total time: {elapsed:.1f}s")

    except OSError as e:
        if e.errno == 28 or 'No space left' in str(e):
            log.error(f"[{msg_id}] DISK FULL — halting agent. Free disk space and restart.")
            for path in [local_dl, local_ul]:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            sys.exit(1)
        raise
    except Exception as e:
        log.exception(f"[{msg_id}] Failed: {e}")
        if state_lock:
            async with state_lock:
                state = load_state()
                state = mark_failed(state, msg_id, str(e), bundle_info)
                save_state(state)
        else:
            state = mark_failed(state, msg_id, str(e), bundle_info)
        for path in [local_dl, local_ul]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        log.info(f"[{msg_id}] Total time: {time.monotonic() - start_time:.1f}s")

    return state


async def run_historical(user_client, bot_client, state, dedup, paused_ref: list):
    log.info("=== HISTORICAL MODE ===")
    messages = await get_all_posts(user_client, last_processed_id=state['last_processed_id'])

    if not messages:
        log.info("No new posts. Switching to LIVE MODE.")
        state['mode'] = 'live'
        save_state(state)
        return state

    total = len(messages)
    state_lock = asyncio.Lock() if CONCURRENT_FILES > 1 else None
    sem = asyncio.Semaphore(CONCURRENT_FILES) if CONCURRENT_FILES > 1 else None

    async def process_one(i: int, msg):
        while paused_ref[0]:
            await asyncio.sleep(10)
        if sem:
            async with sem:
                log.info(f"─── {i}/{total} ───")
                return await process_message(user_client, bot_client, msg, state, dedup, state_lock=state_lock)
        else:
            log.info(f"─── {i}/{total} ───")
            new_state = await process_message(user_client, bot_client, msg, state, dedup)
            await asyncio.sleep(2)
            return new_state

    if CONCURRENT_FILES > 1:
        log.info(f"Parallel download: up to {CONCURRENT_FILES} files at a time.")
        tasks = [process_one(i, msg) for i, msg in enumerate(messages, 1)]
        await asyncio.gather(*tasks)
        state = load_state()
    else:
        for i, msg in enumerate(messages, 1):
            state = await process_one(i, msg)

    log.info("=== Historical complete. Switching to LIVE MODE. ===")
    state['mode'] = 'live'
    save_state(state)
    return state


async def run_live(user_client, bot_client, state, dedup, paused_ref: list):
    """Live mode: process one message at a time (queue new posts)."""
    log.info("=== LIVE MODE: Watching for new posts ===")
    queue = asyncio.Queue()
    state_ref = [state]

    @user_client.on(events.NewMessage(chats=SOURCE_CHANNEL))
    async def on_new_message(event):
        await queue.put(event.message)

    async def worker():
        nonlocal state_ref
        while True:
            msg = await queue.get()
            try:
                while paused_ref[0]:
                    await queue.put(msg)
                    await asyncio.sleep(10)
                    msg = await queue.get()
                log.info(f"New post: ID {msg.id}")
                state_ref[0] = await process_message(
                    user_client, bot_client, msg, state_ref[0], dedup
                )
            finally:
                queue.task_done()

    asyncio.create_task(worker())
    await user_client.run_until_disconnected()


async def main_async(lock_path: str):
    state = load_state()
    paused_ref = [False]

    log.info(
        f"Starting | Mode: {state['mode']} | "
        f"Processed: {state['total_processed']} | "
        f"Dupes skipped: {state.get('skipped_duplicates', 0)} | "
        f"Bundles tracked: {len(state.get('bundles', {}))}"
    )
    if USE_DRIVE_STAGING:
        log.warning(
            "Drive staging is ON. Service accounts often get storageQuotaExceeded on personal Drive. "
            "Set USE_DRIVE_STAGING=false in .env for direct mode (source → destination, same filename)."
        )
    else:
        log.info("Drive staging: OFF — direct mode (files posted to destination with same filename as source).")
    if CONCURRENT_FILES > 1:
        log.info(f"Parallel downloads: up to {CONCURRENT_FILES} files at a time (set CONCURRENT_FILES in .env).")

    user_client = get_user_client()
    bot_client = get_bot_client()
    user_session_file = USER_SESSION_PATH + '.session'
    if not sys.stdin.isatty() and not os.path.exists(user_session_file):
        print(
            "ERROR: First-time Telegram login required (no user session found).\n"
            "Run: docker compose down && ./start.sh login\n"
            "Enter phone and code, then Ctrl+C, then ./start.sh",
            file=sys.stderr
        )
        sys.exit(0)
    await user_client.start()
    await bot_client.start(bot_token=BOT_TOKEN)
    log.info("Both Telegram clients connected.")

    await register_admin_handlers(bot_client, paused_ref)

    dedup = BundleDeduplicationEngine()
    await dedup.load(user_client, fetch_limit=500)

    if state['mode'] == 'historical':
        state = await run_historical(user_client, bot_client, state, dedup, paused_ref)

    await run_live(user_client, bot_client, state, dedup, paused_ref)


def main():
    global log
    validate_env()
    lock_path = setup_lockfile()
    os.makedirs(TEMP_DIR, exist_ok=True)
    log = setup_logging()

    try:
        asyncio.run(main_async(lock_path))
    except KeyboardInterrupt:
        log.info("Stopped by user")
    except Exception as e:
        log.exception(f"Fatal: {e}")
        raise
    finally:
        remove_lockfile(lock_path)
