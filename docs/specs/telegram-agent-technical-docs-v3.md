# Telegram Channel Repost Agent — Technical Documentation v3.0
### Bundle-Aware Architecture | From Setup to Production

---

## Table of Contents

1. [What Changed in v3.0](#1-what-changed-in-v30)
2. [The Problem with Previous Deduplication](#2-the-problem-with-previous-deduplication)
3. [The Bundle-Aware Algorithm](#3-the-bundle-aware-algorithm)
4. [Final Architecture & Workflow](#4-final-architecture--workflow)
5. [Prerequisites & Accounts Setup](#5-prerequisites--accounts-setup)
6. [Phase 1 — Environment Setup](#6-phase-1--environment-setup)
7. [Phase 2 — Google Drive Handler](#7-phase-2--google-drive-handler)
8. [Phase 3 — Telegram Handler](#8-phase-3--telegram-handler)
9. [Phase 4 — Bundle Detector](#9-phase-4--bundle-detector)
10. [Phase 5 — Bundle-Aware Deduplication Engine](#10-phase-5--bundle-aware-deduplication-engine)
11. [Phase 6 — State Manager](#11-phase-6--state-manager)
12. [Phase 7 — Core Orchestrator](#12-phase-7--core-orchestrator)
13. [Phase 8 — n8n Integration](#13-phase-8--n8n-integration)
14. [Phase 9 — Error Handling](#14-phase-9--error-handling)
15. [Phase 10 — Testing](#15-phase-10--testing)
16. [Phase 11 — Production Deployment](#16-phase-11--production-deployment)
17. [Phase 12 — Monitoring](#17-phase-12--monitoring)
18. [Full File Structure](#18-full-file-structure)
19. [Common Errors & Fixes](#19-common-errors--fixes)

---

## 1. What Changed in v3.0

The previous deduplication used **title + file size** as the composite key. This breaks on channels like the one in your project where a single bundle is split into numbered parts:

```
StationX - The Complete Python for Hacking Bundle.zip.001  →  3900.0 MB
StationX - The Complete Python for Hacking Bundle.zip.002  →  3900.0 MB
StationX - The Complete Python for Hacking Bundle.zip.003  →  3900.0 MB
StationX - The Complete Python for Hacking Bundle.zip.004  →  3900.0 MB
StationX - The Complete Python for Hacking Bundle.zip.005  →  3299.3 MB
```

Parts 001–004 all share **the same file size (3900 MB)**. If a second different bundle also has parts of 3900 MB, the composite key `(title, size)` still holds uniqueness as long as titles differ — but the system still has no concept of "these files belong together." This creates three real problems:

- If the agent crashes after part 3 of 5, it re-processes 1 and 2 even though they're done (no group tracking)
- You cannot tell from state.json whether a bundle is complete or partial
- Drive folder is unorganized — all files dumped flat with no bundle grouping
- If the channel reposts a corrected version of a bundle with the same name but different size on part 5, the old dedup misses it

**v3.0 introduces bundle-aware processing** that solves all of these.

---

## 2. The Problem with Previous Deduplication

### Why Title + Size Alone Is Not Enough

| Filename | Size | Title+Size Key | Problem |
|---|---|---|---|
| Bundle_A.zip.001 | 3900 MB | (Bundle_A.zip.001, 3900MB) | Unique — OK |
| Bundle_A.zip.002 | 3900 MB | (Bundle_A.zip.002, 3900MB) | Unique — OK |
| Bundle_B.zip.001 | 3900 MB | (Bundle_B.zip.001, 3900MB) | Unique — OK |
| Bundle_A.zip.001 (repost) | 3900 MB | (Bundle_A.zip.001, 3900MB) | **Correctly blocked ✓** |

Title+size technically gives unique keys for these cases. However, the system still cannot answer:
- "Is Bundle_A complete (all 5 parts done)?"
- "Where do Bundle_A parts live in Drive?"
- "If I need to retry part 3 of Bundle_A, which Drive folder do I look in?"

### What Bundle-Aware Solves

| Capability | v2.0 | v3.0 |
|---|---|---|
| Detect duplicate individual parts | ✓ | ✓ |
| Group related parts under one bundle name | ✗ | ✓ |
| Track bundle completion (3/5 parts done) | ✗ | ✓ |
| Organize Drive into subfolders per bundle | ✗ | ✓ |
| Detect if a bundle was re-uploaded with a corrected part | ✗ | ✓ |
| Resume partial bundle after crash | ✗ | ✓ |

---

## 3. The Bundle-Aware Algorithm

### 3.1 How Bundle Detection Works

The `BundleDetector` class normalizes any filename into a structured fingerprint:

```
Input:  "StationX - The Complete Python for Hacking Bundle.zip.001"
Output: {
    "base_name":    "StationX - The Complete Python for Hacking Bundle",
    "extension":    "zip",
    "part_number":  1,
    "is_part":      True,
    "bundle_id":    "stationx-the-complete-python-for-hacking-bundle-zip"
}
```

The `bundle_id` is a normalized, lowercased, slug-style key that becomes:
- The Drive subfolder name for this bundle
- The grouping key in state.json
- The deduplication root key

### 3.2 Serial Number Patterns Detected

The detector strips all of these automatically:

| Pattern | Example Input | Detected Part |
|---|---|---|
| `.NNN` (3-digit ext) | `file.zip.001` | 1 |
| `.partN` | `file.part3.rar` | 3 |
| `Part N` / `part N` | `Course Part 2.zip` | 2 |
| `Vol N` / `Volume N` | `Course Vol.3.zip` | 3 |
| `(N)` | `Course (4).zip` | 4 |
| `- N` at end | `Course - 5.zip` | 5 |
| `_N` at end | `Course_06.zip` | 6 |

### 3.3 The Composite Fingerprint

A file is considered a duplicate if ALL THREE match:

```
bundle_id  +  part_number  +  file_size_bytes
```

This means:
- Same bundle, same part, same size → **DUPLICATE** (skip)
- Same bundle, same part, different size → **UPDATED VERSION** (re-process)
- Same bundle, different part → **DIFFERENT FILE** (process normally)
- Different bundle, same size → **DIFFERENT FILE** (process normally)

### 3.4 Drive Folder Structure (New in v3.0)

Instead of dumping all files flat into one Drive folder, each bundle gets its own subfolder:

```
TelegramArchive/
├── stationx-complete-python-hacking-bundle-zip/
│   ├── StationX - The Complete Python for Hacking Bundle.zip.001
│   ├── StationX - The Complete Python for Hacking Bundle.zip.002
│   ├── StationX - The Complete Python for Hacking Bundle.zip.003
│   ├── StationX - The Complete Python for Hacking Bundle.zip.004
│   └── StationX - The Complete Python for Hacking Bundle.zip.005
├── another-course-bundle-zip/
│   ├── AnotherCourse.zip.001
│   └── AnotherCourse.zip.002
└── standalone-file-zip/
    └── StandaloneFile.zip
```

---

## 4. Final Architecture & Workflow

```
┌───────────────────────────────────────────────────────────────────────────┐
│                      BUNDLE-AWARE LOOP WORKFLOW (v3.0)                    │
│                                                                            │
│  STARTUP                                                                   │
│  ┌─────────────────────────────────────────────────────────┐              │
│  │  1. Load state.json (which bundles/parts are done)       │              │
│  │  2. Load dedup index from destination channel            │              │
│  │  3. Connect user client + bot client                     │              │
│  └──────────────────────────┬──────────────────────────────┘              │
│                             │                                              │
│  ┌──────────────────────────▼──────────────────────────────┐              │
│  │  FETCH all posts from source channel (oldest → newest)   │◄──────────┐ │
│  └──────────────────────────┬──────────────────────────────┘           │ │
│                             │                                           │ │
│  ┌──────────────────────────▼──────────────────────────────┐           │ │
│  │  BUNDLE DETECTION                                        │           │ │
│  │  Extract: base_name, part_number, bundle_id              │           │ │
│  └────────────┬──────────────────────────┬─────────────────┘           │ │
│               │                          │                              │ │
│        Single File                  Part of Bundle                      │ │
│               │                          │                              │ │
│  ┌────────────▼──────────────┐  ┌────────▼──────────────────┐         │ │
│  │  DEDUP CHECK              │  │  BUNDLE DEDUP CHECK        │         │ │
│  │  (title + size)           │  │  (bundle_id + part + size) │         │ │
│  └────────────┬──────────────┘  └────────┬──────────────────┘         │ │
│               │                          │                              │ │
│      ┌────────┴────────┐        ┌────────┴────────┐                   │ │
│   DUPE?               NEW    DUPE?               NEW                   │ │
│      │                 │        │                  │                    │ │
│    SKIP             PROCESS   SKIP             PROCESS                 │ │
│      │                 │        │                  │                    │ │
│      └────────┬────────┘        └────────┬─────────┘                  │ │
│               │                          │                              │ │
│               └──────────┬───────────────┘                             │ │
│                          │                                              │ │
│  ┌───────────────────────▼─────────────────────────────────┐           │ │
│  │  DOWNLOAD from source channel via Telethon (MTProto)     │           │ │
│  │  Save to local /temp                                     │           │ │
│  └───────────────────────┬─────────────────────────────────┘           │ │
│                          │                                              │ │
│  ┌───────────────────────▼─────────────────────────────────┐           │ │
│  │  UPLOAD to Google Drive                                  │           │ │
│  │  Into bundle subfolder: TelegramArchive/{bundle_id}/     │           │ │
│  │  Delete local temp file                                  │           │ │
│  └───────────────────────┬─────────────────────────────────┘           │ │
│                          │                                              │ │
│  ┌───────────────────────▼─────────────────────────────────┐           │ │
│  │  RE-DOWNLOAD from Drive to local /temp                   │           │ │
│  │  (staging buffer for Telegram upload)                    │           │ │
│  └───────────────────────┬─────────────────────────────────┘           │ │
│                          │                                              │ │
│  ┌───────────────────────▼─────────────────────────────────┐           │ │
│  │  UPLOAD to destination Telegram channel                  │           │ │
│  │  Caption = original title (preserves serial numbers)     │           │ │
│  │  Delete local staging file                               │           │ │
│  └───────────────────────┬─────────────────────────────────┘           │ │
│                          │                                              │ │
│  ┌───────────────────────▼─────────────────────────────────┐           │ │
│  │  UPLOAD VERIFICATION                                     │           │ │
│  │  Last Drive file (name+size) == Last TG upload?          │           │ │
│  └────────────┬──────────────────────────┬─────────────────┘           │ │
│               │                          │                              │ │
│            MATCH                      NO MATCH                         │ │
│               │                          │                              │ │
│  ┌────────────▼───────────┐  ┌───────────▼────────────────┐            │ │
│  │  DELETE from Drive     │  │  KEEP Drive file as backup  │           │ │
│  │  (clean up storage)    │  │  Log warning for review     │           │ │
│  └────────────┬───────────┘  └───────────┬────────────────┘           │ │
│               └──────────────┬────────────┘                            │ │
│                              │                                          │ │
│  ┌───────────────────────────▼─────────────────────────────┐           │ │
│  │  UPDATE state.json                                       │           │ │
│  │  - Mark part as done                                     │           │ │
│  │  - Update bundle completion count                        │           │ │
│  │  - Add to dedup index in memory                          │           │ │
│  └───────────────────────────┬─────────────────────────────┘           │ │
│                              │                                          │ │
│                              └──────────── NEXT POST ───────────────────┘ │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Prerequisites & Accounts Setup

### 5.1 Telegram

**Create a Telegram App (MTProto credentials)**
1. Go to https://my.telegram.org → login with your personal account
2. Click **API Development Tools** → fill in App title, Short name, Platform: Other
3. Save `api_id` and `api_hash` — never share these

**Create Your Bot**
1. Message `@BotFather` → `/newbot` → save the Bot Token
2. Add bot as **Administrator** to your destination channel with Post Messages + Send Files permissions

**Get Destination Channel ID**
1. Forward any message from your channel to `@userinfobot`
2. Save the ID (format: `-100XXXXXXXXXX`)

### 5.2 Google Cloud

1. Create project at https://console.cloud.google.com
2. Enable **Google Drive API**
3. Create **Service Account** (Editor role) → download JSON → rename to `credentials.json`
4. In Drive, create folder `TelegramArchive` → share with service account `client_email` (Editor access)
5. Save the folder ID from the URL

---

## 6. Phase 1 — Environment Setup

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3.11 python3.11-venv python3-pip -y

mkdir -p /opt/telegram-agent
cd /opt/telegram-agent
python3.11 -m venv venv
source venv/bin/activate

pip install telethon google-api-python-client google-auth-httplib2 \
            google-auth-oauthlib python-dotenv aiofiles

mkdir -p temp logs
```

### `.env` File

```env
TG_API_ID=12345678
TG_API_HASH=your_api_hash_here
BOT_TOKEN=1234567890:ABCdef...
SOURCE_CHANNEL=sourcechannel
DEST_CHANNEL_ID=-100XXXXXXXXXX
DRIVE_ROOT_FOLDER_ID=your_root_folder_id
CREDENTIALS_PATH=/opt/telegram-agent/credentials.json
TEMP_DIR=/opt/telegram-agent/temp
STATE_FILE=/opt/telegram-agent/state.json
LOG_FILE=/opt/telegram-agent/logs/agent.log
```

---

## 7. Phase 2 — Google Drive Handler

Create `drive_handler.py`:

```python
import os
import io
import re
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/drive']
CREDENTIALS_PATH = os.getenv('CREDENTIALS_PATH')
DRIVE_ROOT_FOLDER_ID = os.getenv('DRIVE_ROOT_FOLDER_ID')


def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_PATH, scopes=SCOPES
    )
    return build('drive', 'v3', credentials=creds)


def get_or_create_subfolder(subfolder_name: str) -> str:
    """
    Gets the Drive folder ID for a bundle subfolder.
    Creates the subfolder inside TelegramArchive if it doesn't exist.
    Returns the subfolder ID.
    """
    service = get_drive_service()
    safe_name = re.sub(r'[^\w\s\-.]', '', subfolder_name)[:100]

    # Check if subfolder already exists
    results = service.files().list(
        q=(f"'{DRIVE_ROOT_FOLDER_ID}' in parents "
           f"and name='{safe_name}' "
           f"and mimeType='application/vnd.google-apps.folder' "
           f"and trashed=false"),
        fields='files(id, name)'
    ).execute()

    files = results.get('files', [])
    if files:
        return files[0]['id']

    # Create the subfolder
    folder_metadata = {
        'name': safe_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [DRIVE_ROOT_FOLDER_ID]
    }
    folder = service.files().create(body=folder_metadata, fields='id').execute()
    return folder.get('id')


def upload_to_drive(file_path: str, filename: str, bundle_id: str) -> str:
    """
    Uploads a file into the bundle's subfolder in Drive.
    Creates the subfolder automatically if it doesn't exist.
    Returns the Drive file ID.
    """
    service = get_drive_service()
    folder_id = get_or_create_subfolder(bundle_id)

    file_metadata = {'name': filename, 'parents': [folder_id]}
    media = MediaFileUpload(
        file_path,
        resumable=True,
        chunksize=100 * 1024 * 1024  # 100 MB chunks
    )
    request = service.files().create(
        body=file_metadata, media_body=media, fields='id,name,size'
    )
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Drive upload: {int(status.progress() * 100)}%", end='\r')

    print(f"\n  Drive upload complete → {bundle_id}/{filename}")
    return response.get('id')


def download_from_drive(drive_file_id: str, destination_path: str):
    """Downloads a file from Drive using chunked download."""
    service = get_drive_service()
    request = service.files().get_media(fileId=drive_file_id)
    fh = io.FileIO(destination_path, 'wb')
    downloader = MediaIoBaseDownload(fh, request, chunksize=100 * 1024 * 1024)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        if status:
            print(f"  Drive download: {int(status.progress() * 100)}%", end='\r')
    fh.close()
    print(f"\n  Drive download complete → {destination_path}")


def get_last_drive_file_in_folder(bundle_id: str) -> dict:
    """
    Returns metadata of the most recently uploaded file in a bundle's subfolder.
    Used for upload verification before Drive deletion.
    """
    service = get_drive_service()
    folder_id = get_or_create_subfolder(bundle_id)
    results = service.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        orderBy='createdTime desc',
        pageSize=1,
        fields='files(id, name, size)'
    ).execute()
    files = results.get('files', [])
    return files[0] if files else {}


def delete_from_drive(drive_file_id: str):
    """Deletes a file from Drive. Only called after upload verification passes."""
    service = get_drive_service()
    service.files().delete(fileId=drive_file_id).execute()
    print(f"  Drive file deleted: {drive_file_id}")
```

---

## 8. Phase 3 — Telegram Handler

Create `telegram_handler.py`:

```python
import os
import asyncio
from telethon import TelegramClient, events
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


def get_user_client():
    return TelegramClient('user_session', API_ID, API_HASH)


def get_bot_client():
    return TelegramClient('bot_session', API_ID, API_HASH)


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


async def get_last_dest_post(bot_client) -> dict:
    async for msg in bot_client.iter_messages(DEST_CHANNEL_ID, limit=1):
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


def get_size(message) -> int:
    if message.document:
        return message.document.size
    return 0
```

---

## 9. Phase 4 — Bundle Detector

This is the new core of v3.0. Create `bundle_detector.py`:

```python
import re
import unicodedata


# Ordered by specificity — most specific patterns first
SERIAL_PATTERNS = [
    # .001, .002, .010, .099  (3-digit numeric extension — most common for zip splits)
    (r'\.(\d{3})$', 'three_digit_ext'),

    # .part1.rar, .part01.rar, .part001.rar
    (r'\.part0*(\d+)\b', 'part_ext'),

    # Part 1, Part 2, Part01, part_2  (word "part" followed by number)
    (r'\bpart[-_\s]*0*(\d+)\b', 'part_word'),

    # Vol 1, Vol. 2, Volume 3, vol1
    (r'\b(?:vol(?:ume)?)[.\s-]*0*(\d+)\b', 'volume_word'),

    # (1), (2), (10)  — parenthesized number at end
    (r'\(0*(\d+)\)\s*$', 'paren_num'),

    # - 1, - 2, _1, _2  at end of name (after stripping extension)
    (r'[-_]\s*0*(\d+)\s*$', 'suffix_num'),
]


def slugify(text: str) -> str:
    """Converts a string to a URL-safe lowercase slug."""
    text = unicodedata.normalize('NFKD', text)
    text = text.encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^\w\s\-]', ' ', text)
    text = re.sub(r'[\s_]+', '-', text.strip())
    return text.lower()[:80]


def split_name_ext(filename: str) -> tuple:
    """
    Splits filename into (name_without_ext, extension).
    Handles compound extensions like .zip.001, .tar.gz.
    Returns (base, ext) where ext may be empty string.
    """
    # Handle .zip.001, .tar.gz.001 style
    compound = re.match(r'^(.*?)((?:\.\w+){1,2})$', filename)
    if compound:
        return compound.group(1), compound.group(2).lstrip('.')
    return filename, ''


def detect_bundle(filename: str) -> dict:
    """
    Analyzes a filename and returns structured bundle information.

    Returns a dict:
    {
        'filename':     original filename,
        'base_name':    series name with serial part stripped,
        'part_number':  integer part number (0 if not a series),
        'extension':    file extension(s),
        'is_part':      True if part of a multi-part series,
        'bundle_id':    normalized slug for grouping and Drive subfolder,
        'pattern_type': which pattern matched (for debugging)
    }

    Examples:
        "Course.zip.001"         → base="Course", part=1, bundle_id="course-zip"
        "Course.zip.002"         → base="Course", part=2, bundle_id="course-zip"
        "Course Part 3.zip"      → base="Course", part=3, bundle_id="course-zip"
        "Course Vol.2.rar"       → base="Course", part=2, bundle_id="course-rar"
        "Standalone.zip"         → base="Standalone", part=0, is_part=False
    """
    # Work on the full filename for pattern matching
    name_lower = filename.lower()

    for pattern, pattern_type in SERIAL_PATTERNS:
        match = re.search(pattern, name_lower, re.IGNORECASE)
        if match:
            part_number = int(match.group(1))

            # Strip the matched serial portion from the original filename
            base_stripped = re.sub(
                pattern, '', filename, flags=re.IGNORECASE
            ).strip(' .-_')

            # Get clean extension from original (not the serial number)
            # For .zip.001: extension becomes "zip", base becomes series name
            base_name, extension = split_name_ext(base_stripped)
            if not extension:
                _, extension = split_name_ext(filename.lower())
                # Remove the matched serial from extension area
                extension = re.sub(pattern, '', extension, flags=re.IGNORECASE).strip('.')

            # Build bundle_id from base name + primary extension
            primary_ext = extension.split('.')[0] if extension else ''
            bundle_id = slugify(f"{base_name} {primary_ext}") if primary_ext else slugify(base_name)

            return {
                'filename': filename,
                'base_name': base_name.strip(),
                'part_number': part_number,
                'extension': extension,
                'is_part': True,
                'bundle_id': bundle_id,
                'pattern_type': pattern_type
            }

    # Not a numbered part — standalone file
    base_name, extension = split_name_ext(filename)
    return {
        'filename': filename,
        'base_name': base_name,
        'part_number': 0,
        'extension': extension,
        'is_part': False,
        'bundle_id': slugify(filename),
        'pattern_type': None
    }


def build_dedup_key(bundle_info: dict, file_size_bytes: int) -> tuple:
    """
    Builds the composite deduplication key.
    Format: (bundle_id, part_number, file_size_bytes)

    For standalone files: (bundle_id, 0, file_size_bytes)
    For bundle parts:     (bundle_id, part_number, file_size_bytes)

    Why this works:
    - Same bundle, same part, same size  → DUPLICATE (all three match)
    - Same bundle, same part, diff size  → UPDATED FILE (re-process)
    - Same bundle, diff part             → DIFFERENT FILE (part_number differs)
    - Different bundle, same size        → DIFFERENT FILE (bundle_id differs)
    """
    return (
        bundle_info['bundle_id'],
        bundle_info['part_number'],
        file_size_bytes
    )
```

---

## 10. Phase 5 — Bundle-Aware Deduplication Engine

Create `dedup_engine.py`:

```python
from bundle_detector import detect_bundle, build_dedup_key
from telegram_handler import get_destination_posts


class BundleDeduplicationEngine:
    """
    Deduplication using composite key: (bundle_id, part_number, file_size_bytes)

    This correctly handles:
    - Multi-part archives (.zip.001, .zip.002, ...) — each part tracked individually
    - Same series, different sizes — treated as different (updated) files
    - Same size across different series — no false collisions
    - Standalone files — tracked as (bundle_id, 0, size)

    The index is populated from the destination channel at startup and
    updated in-memory as new files are processed, staying accurate in live mode.
    """

    def __init__(self):
        self._index: set = set()
        self._loaded = False

    async def load(self, bot_client, fetch_limit: int = 500):
        """
        Loads destination channel history into the dedup index.
        Call once at startup.
        """
        print(f"Loading dedup index from destination channel ({fetch_limit} posts)...")
        posts = await get_destination_posts(bot_client, limit=fetch_limit)
        for filename, size in posts:
            bundle_info = detect_bundle(filename)
            key = build_dedup_key(bundle_info, size)
            self._index.add(key)
        self._loaded = True
        print(f"Dedup index loaded: {len(self._index)} entries.")

    def is_duplicate(self, filename: str, file_size_bytes: int) -> bool:
        """
        Returns True if this file (identified by bundle_id + part + size)
        already exists in the destination channel.
        """
        if not self._loaded:
            raise RuntimeError("Call .load() before using the dedup engine.")
        bundle_info = detect_bundle(filename)
        key = build_dedup_key(bundle_info, file_size_bytes)
        return key in self._index

    def mark_uploaded(self, filename: str, file_size_bytes: int):
        """Adds a newly uploaded file to the in-memory index."""
        bundle_info = detect_bundle(filename)
        key = build_dedup_key(bundle_info, file_size_bytes)
        self._index.add(key)

    def get_bundle_info(self, filename: str) -> dict:
        """Convenience method to get bundle info for a filename."""
        return detect_bundle(filename)
```

---

## 11. Phase 6 — State Manager

Create `state_manager.py`:

```python
import json
import os
from dotenv import load_dotenv

load_dotenv()
STATE_FILE = os.getenv('STATE_FILE', 'state.json')


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {
            "last_processed_id": 0,
            "processed_ids": [],
            "mode": "historical",
            "total_processed": 0,
            "skipped_duplicates": 0,
            "failed_ids": [],
            "bundles": {}
            # bundles structure:
            # {
            #   "bundle-id-slug": {
            #     "display_name": "Original Series Name",
            #     "total_parts_seen": 5,
            #     "parts_completed": [1, 2, 3],
            #     "parts_failed": [4],
            #     "drive_folder_id": "1abc..."
            #   }
            # }
        }
    with open(STATE_FILE, 'r') as f:
        return json.load(f)


def save_state(state: dict):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def mark_processed(state: dict, message_id: int, bundle_info: dict = None) -> dict:
    state['processed_ids'].append(message_id)
    state['last_processed_id'] = max(state['last_processed_id'], message_id)
    state['total_processed'] += 1

    if bundle_info and bundle_info.get('is_part'):
        bid = bundle_info['bundle_id']
        if bid not in state['bundles']:
            state['bundles'][bid] = {
                'display_name': bundle_info['base_name'],
                'total_parts_seen': 0,
                'parts_completed': [],
                'parts_failed': []
            }
        bundle = state['bundles'][bid]
        part = bundle_info['part_number']
        if part not in bundle['parts_completed']:
            bundle['parts_completed'].append(part)
        bundle['total_parts_seen'] = max(
            bundle['total_parts_seen'],
            bundle_info['part_number']
        )

    save_state(state)
    return state


def mark_duplicate(state: dict, message_id: int) -> dict:
    state['processed_ids'].append(message_id)
    state['last_processed_id'] = max(state['last_processed_id'], message_id)
    state['skipped_duplicates'] += 1
    save_state(state)
    return state


def mark_failed(state: dict, message_id: int, error: str,
                bundle_info: dict = None) -> dict:
    state['failed_ids'].append({
        "id": message_id,
        "error": error,
        "bundle_id": bundle_info.get('bundle_id') if bundle_info else None,
        "part": bundle_info.get('part_number') if bundle_info else None
    })
    if bundle_info and bundle_info.get('is_part'):
        bid = bundle_info['bundle_id']
        if bid in state['bundles']:
            part = bundle_info['part_number']
            if part not in state['bundles'][bid]['parts_failed']:
                state['bundles'][bid]['parts_failed'].append(part)
    save_state(state)
    return state
```

---

## 12. Phase 7 — Core Orchestrator

Create `main.py`:

```python
import asyncio
import os
import logging
from dotenv import load_dotenv
from telethon import events
from telethon.errors import FloodWaitError

from telegram_handler import (
    get_user_client, get_bot_client, get_all_posts,
    download_file, upload_file, get_last_dest_post,
    get_filename, get_size
)
from drive_handler import (
    upload_to_drive, download_from_drive,
    get_last_drive_file_in_folder, delete_from_drive
)
from bundle_detector import detect_bundle
from dedup_engine import BundleDeduplicationEngine
from state_manager import (
    load_state, save_state,
    mark_processed, mark_duplicate, mark_failed
)

load_dotenv()

TEMP_DIR = os.getenv('TEMP_DIR')
LOG_FILE = os.getenv('LOG_FILE')
BOT_TOKEN = os.getenv('BOT_TOKEN')
SOURCE_CHANNEL = os.getenv('SOURCE_CHANNEL')

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger(__name__)


async def process_message(user_client, bot_client, message, state, dedup):
    msg_id = message.id

    if msg_id in state['processed_ids']:
        return state

    if not message.document:
        log.info(f"[{msg_id}] No file — skipping")
        return mark_processed(state, msg_id)

    filename = get_filename(message)
    file_size = get_size(message)
    bundle_info = detect_bundle(filename)
    size_mb = file_size / (1024 * 1024)

    log.info(
        f"[{msg_id}] File: '{filename}' ({size_mb:.1f} MB) | "
        f"Bundle: '{bundle_info['bundle_id']}' | "
        f"Part: {bundle_info['part_number'] if bundle_info['is_part'] else 'standalone'}"
    )

    # ── STEP 1: BUNDLE-AWARE DEDUP CHECK ─────────────────────────────────────
    if dedup.is_duplicate(filename, file_size):
        log.info(f"[{msg_id}] DUPLICATE — skipping.")
        return mark_duplicate(state, msg_id)

    local_dl = None
    local_ul = None
    drive_file_id = None

    try:
        # ── STEP 2: DOWNLOAD FROM TELEGRAM ───────────────────────────────────
        log.info(f"[{msg_id}] 1/5 Downloading from Telegram...")
        local_dl = await download_file(user_client, message, f"dl_{msg_id}_{filename}")

        # ── STEP 3: UPLOAD TO DRIVE (bundle subfolder) ───────────────────────
        log.info(f"[{msg_id}] 2/5 Uploading to Drive folder '{bundle_info['bundle_id']}'...")
        drive_file_id = upload_to_drive(local_dl, filename, bundle_info['bundle_id'])

        os.remove(local_dl)
        local_dl = None

        # ── STEP 4: RE-DOWNLOAD FROM DRIVE ───────────────────────────────────
        log.info(f"[{msg_id}] 3/5 Re-downloading from Drive...")
        local_ul = os.path.join(TEMP_DIR, f"up_{msg_id}_{filename}")
        download_from_drive(drive_file_id, local_ul)

        # ── STEP 5: UPLOAD TO DESTINATION TELEGRAM CHANNEL ───────────────────
        log.info(f"[{msg_id}] 4/5 Uploading to destination channel...")
        try:
            await upload_file(bot_client, local_ul, caption=filename)
        except FloodWaitError as e:
            log.warning(f"[{msg_id}] FloodWait {e.seconds}s — retrying...")
            await asyncio.sleep(e.seconds + 5)
            await upload_file(bot_client, local_ul, caption=filename)

        os.remove(local_ul)
        local_ul = None

        # ── STEP 6: UPLOAD VERIFICATION ──────────────────────────────────────
        log.info(f"[{msg_id}] 5/5 Verifying upload...")
        drive_meta = get_last_drive_file_in_folder(bundle_info['bundle_id'])
        tg_last = await get_last_dest_post(bot_client)

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

        # ── STEP 7: UPDATE STATE & DEDUP INDEX ───────────────────────────────
        dedup.mark_uploaded(filename, file_size)
        state = mark_processed(state, msg_id, bundle_info)
        log.info(f"[{msg_id}] ✅ Done.")

    except Exception as e:
        log.error(f"[{msg_id}] ❌ Failed: {e}")
        state = mark_failed(state, msg_id, str(e), bundle_info)
        for path in [local_dl, local_ul]:
            if path and os.path.exists(path):
                os.remove(path)

    return state


async def run_historical(user_client, bot_client, state, dedup):
    log.info("=== HISTORICAL MODE ===")
    messages = await get_all_posts(user_client, last_processed_id=state['last_processed_id'])

    if not messages:
        log.info("No new posts. Switching to LIVE MODE.")
        state['mode'] = 'live'
        save_state(state)
        return state

    total = len(messages)
    for i, msg in enumerate(messages, 1):
        log.info(f"─── {i}/{total} ───")
        state = await process_message(user_client, bot_client, msg, state, dedup)
        await asyncio.sleep(2)

    log.info("=== Historical complete. Switching to LIVE MODE. ===")
    state['mode'] = 'live'
    save_state(state)
    return state


async def run_live(user_client, bot_client, state, dedup):
    log.info("=== LIVE MODE: Watching for new posts ===")

    @user_client.on(events.NewMessage(chats=SOURCE_CHANNEL))
    async def handler(event):
        nonlocal state
        log.info(f"New post: ID {event.message.id}")
        state = await process_message(user_client, bot_client, event.message, state, dedup)

    await user_client.run_until_disconnected()


async def main():
    state = load_state()
    log.info(
        f"Starting | Mode: {state['mode']} | "
        f"Processed: {state['total_processed']} | "
        f"Dupes skipped: {state.get('skipped_duplicates', 0)} | "
        f"Bundles tracked: {len(state.get('bundles', {}))}"
    )

    user_client = get_user_client()
    bot_client = get_bot_client()
    await user_client.start()
    await bot_client.start(bot_token=BOT_TOKEN)
    log.info("Both Telegram clients connected.")

    dedup = BundleDeduplicationEngine()
    await dedup.load(bot_client, fetch_limit=500)

    if state['mode'] == 'historical':
        state = await run_historical(user_client, bot_client, state, dedup)

    await run_live(user_client, bot_client, state, dedup)


if __name__ == '__main__':
    asyncio.run(main())
```

---

## 13. Phase 8 — n8n Integration

n8n handles scheduling and alerting only — never in the file transfer path.

**Workflow 1: Keep Agent Alive (Every 5 min)**
```bash
pgrep -f "python main.py" || /opt/telegram-agent/venv/bin/python /opt/telegram-agent/main.py &
```

**Workflow 2: Daily Status with Bundle Report (9 AM)**
```bash
python3 -c "
import json
with open('/opt/telegram-agent/state.json') as f:
    s = json.load(f)
bundles = s.get('bundles', {})
incomplete = [(k,v) for k,v in bundles.items() if len(v['parts_failed']) > 0]
print(f\"Processed: {s['total_processed']}\nDupes: {s['skipped_duplicates']}\nFailed: {len(s['failed_ids'])}\nBundles tracked: {len(bundles)}\nBundles with failures: {len(incomplete)}\")
"
```

**Workflow 3: Failure Alert (Every 30 min)**
```bash
python3 -c "
import json
with open('/opt/telegram-agent/state.json') as f:
    s = json.load(f)
print(len(s['failed_ids']))
"
```

---

## 14. Phase 9 — Error Handling

| Failure Scenario | Handling |
|---|---|
| Telegram download timeout | Telethon retries internally |
| Drive upload interrupted | Resumable upload continues from last chunk |
| VPS crash | state.json only updated on full success |
| Duplicate detected | Dedup engine blocks before any download |
| Drive deletion mismatch | Drive file kept; warning logged |
| FloodWait | Sleep exact duration + 5s, retry once |
| Bundle partially processed | state.json tracks per-part completion; retry resumes from missing parts |

**Retry Failed Posts** — create `retry_failed.py`:
```python
import json

with open('state.json', 'r') as f:
    state = json.load(f)

failed_ids = [item['id'] for item in state['failed_ids']]
state['processed_ids'] = [i for i in state['processed_ids'] if i not in failed_ids]

# Also clear failed parts from bundle tracking
for bid, bundle in state.get('bundles', {}).items():
    bundle['parts_failed'] = []

state['failed_ids'] = []

with open('state.json', 'w') as f:
    json.dump(state, f, indent=2)

print(f"Reset {len(failed_ids)} failed posts for retry.")
```

---

## 15. Phase 10 — Testing

### Test the Bundle Detector First (No Telegram Needed)

Create `test_bundle_detector.py` and run it standalone:

```python
from bundle_detector import detect_bundle, build_dedup_key

test_files = [
    ("StationX - The Complete Python for Hacking Bundle.zip.001", 3900 * 1024 * 1024),
    ("StationX - The Complete Python for Hacking Bundle.zip.002", 3900 * 1024 * 1024),
    ("StationX - The Complete Python for Hacking Bundle.zip.005", 3299 * 1024 * 1024),
    ("AnotherCourse.zip.001", 3900 * 1024 * 1024),  # Same size, different bundle
    ("Course Part 1.zip", 1000 * 1024 * 1024),
    ("Course Part 2.zip", 1000 * 1024 * 1024),
    ("Standalone.zip", 500 * 1024 * 1024),
]

print("=== Bundle Detection Test ===\n")
keys_seen = set()
for filename, size in test_files:
    info = detect_bundle(filename)
    key = build_dedup_key(info, size)
    is_dup = key in keys_seen
    keys_seen.add(key)
    print(f"File: {filename}")
    print(f"  bundle_id:   {info['bundle_id']}")
    print(f"  part_number: {info['part_number']}")
    print(f"  is_part:     {info['is_part']}")
    print(f"  dedup_key:   {key}")
    print(f"  DUPLICATE:   {is_dup}")
    print()
```

Expected output: all 7 files should have unique keys. If any show `DUPLICATE: True` on first run, the detector has a bug.

### Full Pipeline Test

1. Set `SOURCE_CHANNEL` to a small test channel (not the real one)
2. Run `python main.py` — authenticate with phone + code on first run
3. Process 3–5 posts
4. Run agent again immediately — all should be detected as duplicates and skipped
5. Check Drive: bundle subfolders should be created correctly
6. Check destination channel: titles should match source exactly

---

## 16. Phase 11 — Production Deployment

```bash
sudo nano /etc/systemd/system/telegram-agent.service
```

```ini
[Unit]
Description=Telegram Repost Agent v3
After=network.target

[Service]
Type=simple
User=root
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

```bash
sudo systemctl daemon-reload
sudo systemctl enable telegram-agent
sudo systemctl start telegram-agent
tail -f /opt/telegram-agent/logs/agent.log
```

### VPS Disk Recommendation

| Component | Space |
|---|---|
| OS + Python | ~5 GB |
| Peak temp (one 3.9 GB part in-flight, 2× peak) | ~8 GB |
| Logs | ~500 MB |
| **Recommended total** | **30–50 GB SSD** |

### Log Rotation

```bash
sudo nano /etc/logrotate.d/telegram-agent
```
```
/opt/telegram-agent/logs/*.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
}
```

---

## 17. Phase 12 — Monitoring

### Sample state.json with Bundle Tracking

```json
{
  "last_processed_id": 5042,
  "processed_ids": [1001, 1002, 1003, 1004, 1005],
  "mode": "historical",
  "total_processed": 5,
  "skipped_duplicates": 0,
  "failed_ids": [],
  "bundles": {
    "stationx-complete-python-hacking-bundle-zip": {
      "display_name": "StationX - The Complete Python for Hacking Bundle",
      "total_parts_seen": 5,
      "parts_completed": [1, 2, 3, 4, 5],
      "parts_failed": []
    }
  }
}
```

At a glance you can see: Bundle A has 5 parts, all 5 completed, none failed.

---

## 18. Full File Structure

```
/opt/telegram-agent/
│
├── main.py                  ← Core orchestrator
├── telegram_handler.py      ← Telegram read/write via MTProto
├── drive_handler.py         ← Drive upload/download with bundle subfolders
├── bundle_detector.py       ← Serial number stripping + bundle fingerprinting
├── dedup_engine.py          ← Bundle-aware deduplication engine
├── state_manager.py         ← State + bundle completion tracking
├── retry_failed.py          ← Reset failed posts for retry
├── test_bundle_detector.py  ← Unit test for detector (run before deployment)
│
├── .env
├── credentials.json
├── user_session.session
├── bot_session.session
├── state.json
├── temp/
├── logs/
│   ├── agent.log
│   └── agent-error.log
└── venv/
```

---

## 19. Common Errors & Fixes

| Error | Cause | Fix |
|---|---|---|
| `AuthKeyError` | Session file corrupted | Delete `.session`, re-authenticate |
| `ChannelPrivateError` | Source channel not public | Verify channel username |
| `FloodWaitError` | Too many requests | Handled automatically |
| `OSError: No space left` | Disk full in /temp | Clear temp/, upgrade VPS disk |
| `HttpError 403` on Drive | Service account not shared to folder | Re-share root Drive folder |
| `ChatWriteForbiddenError` | Bot not admin in destination | Add bot as admin |
| Bundle parts getting wrong bundle_id | Unusual serial number format | Add new pattern to `SERIAL_PATTERNS` in bundle_detector.py |
| Different bundles sharing bundle_id | Two series have nearly identical names | Check slugify output; adjust slug length or add discriminator |
| Dedup skipping a file it shouldn't | Size collision + bundle_id collision | Check bundle_detector test output; size+bundle_id should always differ |

---

*Documentation v3.0 | Bundle-aware deduplication with per-part state tracking and Drive subfolder organization*
