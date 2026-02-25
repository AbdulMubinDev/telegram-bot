"""
Telegram handler for repost agent (v3.0).
User client (MTProto) for reading/downloading; bot client for posting to destination.
"""
import os
import asyncio
from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import DocumentAttributeFilename
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv('TG_API_ID'))
API_HASH = os.getenv('TG_API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
SOURCE_CHANNEL = os.getenv('SOURCE_CHANNEL')
DEST_CHANNEL_ID = int(os.getenv('DEST_CHANNEL_ID'))
TEMP_DIR = os.getenv('TEMP_DIR')

# Session files in same dir as state.json so they persist in Docker (data/ volume)
STATE_FILE = os.getenv('STATE_FILE', 'state.json')
SESSION_DIR = os.path.dirname(os.path.abspath(STATE_FILE))
USER_SESSION_PATH = os.path.join(SESSION_DIR, 'user_session')
BOT_SESSION_PATH = os.path.join(SESSION_DIR, 'bot_session')


def get_user_client():
    return TelegramClient(USER_SESSION_PATH, API_ID, API_HASH)


def get_bot_client():
    return TelegramClient(BOT_SESSION_PATH, API_ID, API_HASH)


async def get_all_posts(client, last_processed_id: int = 0) -> list:
    channel = await client.get_entity(SOURCE_CHANNEL)
    all_messages = []
    offset_id = 0
    limit = 100

    print(f"Fetching posts from @{SOURCE_CHANNEL}...")
    while True:
        history = await client(GetHistoryRequest(
            peer=channel, limit=limit, offset_date=None,
            offset_id=offset_id, max_id=0,
            min_id=last_processed_id, add_offset=0, hash=0
        ))
        if not history.messages:
            break
        all_messages.extend(history.messages)
        offset_id = history.messages[-1].id
        print(f"  Fetched {len(all_messages)} posts...", end='\r')
        if len(history.messages) < limit:
            break
        await asyncio.sleep(1)

    all_messages.reverse()
    print(f"\nTotal to process: {len(all_messages)}")
    return all_messages


async def get_destination_posts(client, limit: int = 500) -> list:
    """Returns list of (filename, file_size_bytes) tuples from destination channel."""
    channel = await client.get_entity(DEST_CHANNEL_ID)
    posts = []
    async for msg in client.iter_messages(channel, limit=limit):
        fname = get_filename(msg)
        size = get_size(msg)
        if fname:
            posts.append((fname, size))
    return posts


async def download_file(client, message, filename: str) -> str:
    local_path = os.path.join(TEMP_DIR, filename)
    size_mb = get_size(message) / (1024 * 1024)
    print(f"  Downloading: {filename} ({size_mb:.1f} MB)")
    await client.download_media(
        message, file=local_path,
        progress_callback=lambda c, t: print(f"  TG DL: {c/t*100:.1f}%", end='\r')
    )
    print(f"\n  Downloaded: {local_path}")
    return local_path


async def upload_file(bot_client, file_path: str, caption: str) -> int:
    print(f"  Uploading to destination channel...")
    msg = await bot_client.send_file(
        DEST_CHANNEL_ID, file_path, caption=caption,
        progress_callback=lambda c, t: print(f"  TG UL: {c/t*100:.1f}%", end='\r')
    )
    print(f"\n  Uploaded. Message ID: {msg.id}")
    return msg.id


async def get_last_dest_post(client) -> dict:
    """Use user client (bots cannot read channel history)."""
    async for msg in client.iter_messages(DEST_CHANNEL_ID, limit=1):
        return {'filename': get_filename(msg), 'size': get_size(msg)}
    return {}


def get_filename(message) -> str:
    if message.document:
        for attr in message.document.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                return attr.file_name
    if message.text:
        return message.text.split('\n')[0].strip()
    return ''


def get_message_caption(message) -> str:
    """Full text/caption of the message (for reposting so destination looks like source)."""
    return (message.text or '').strip()


def get_size(message) -> int:
    if message.document:
        return message.document.size
    return 0
