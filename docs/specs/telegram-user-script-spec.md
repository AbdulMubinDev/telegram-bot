# Telegram User Account Script — Functional Specification & Prompt Guide
### What the Script Must Do | Behavior Guidelines | Decision Rules

---

## Purpose of This Document

This document is a complete behavioral specification for the Python script that uses a **real Telegram user account** (via Telethon/MTProto) to read from a source channel. It describes exactly what the script must do, why it must do it that way, what decisions it should make automatically, and how it should behave in every scenario. Use this document as a prompt when asking an AI to write or improve the script, or as a specification when reviewing code written by a developer.

---

## Part 1 — What the Script Is and What It Must Not Be Confused With

### What This Script Is

This script runs as a **Telegram user account session**, not a bot. It uses the MTProto protocol (via Telethon) to access Telegram with the same capabilities as a real logged-in user. This is necessary because:

- The source channel is a **public channel where we have no admin access**
- The Telegram Bot API cannot read messages from a channel unless the bot is an admin
- The files are 3–5 GB each, which exceeds the Bot API's 20 MB download limit
- Only MTProto (real user session) can download files of this size and read any public channel

### What This Script Must NOT Do

- It must **not** use the Telegram Bot API for reading or downloading — only Telethon/MTProto
- It must **not** use a bot token for downloading from the source channel
- It must **not** post to the destination channel — that is the bot's job (a separate client)
- It must **not** delete or modify any messages in the source channel
- It must **not** be used to spam, flood, or send any messages anywhere
- It must **not** store the session credentials anywhere except the local `.session` file

---

## Part 2 — The Two Modes the Script Must Operate In

### Mode 1: Historical Mode (First Run and After Crashes)

When the script starts, it must first check `state.json` to determine what has already been processed. If there are unprocessed historical posts, it enters **Historical Mode**.

In Historical Mode the script must:

1. Fetch ALL posts from the source channel starting from the oldest post that has not yet been processed (determined by `last_processed_id` in `state.json`)
2. Process them **strictly in order from oldest to newest** — never newest-first
3. Continue until every historical post has been either processed, marked as duplicate, or marked as failed
4. After all historical posts are handled, automatically transition to Live Mode without stopping or restarting

The reason for oldest-first ordering: the files in the source channel are numbered parts of bundles (`.zip.001`, `.zip.002`...). If these are posted to the destination channel out of order, subscribers will be confused. Chronological order from the source must be preserved.

### Mode 2: Live Mode (After Historical Is Complete)

Once all historical posts are processed, the script enters **Live Mode** and stays running indefinitely. In Live Mode the script must:

1. Listen for new messages in the source channel in real time using Telethon's event listener (`events.NewMessage`)
2. Process each new post using the exact same pipeline as Historical Mode
3. Never stop listening unless the process is killed
4. If a new post arrives while another file is still being processed, queue it and process it after the current one completes — never process two files simultaneously

The reason for never stopping: the client is running a channel that mirrors the source. Any new post must appear in the destination channel as soon as possible after it appears in the source.

---

## Part 3 — The Bundle Detection Logic the Script Must Use

### Why Bundle Detection Is Required

The source channel posts files like this:

```
StationX - The Complete Python for Hacking Bundle.zip.001  →  3900 MB
StationX - The Complete Python for Hacking Bundle.zip.002  →  3900 MB
StationX - The Complete Python for Hacking Bundle.zip.003  →  3900 MB
StationX - The Complete Python for Hacking Bundle.zip.004  →  3900 MB
StationX - The Complete Python for Hacking Bundle.zip.005  →  3299 MB
```

Parts 001 through 004 are **different files with the same size**. If the deduplication logic only checks file size, it would incorrectly treat part 002 as a duplicate of part 001. If it only checks the filename title, it would correctly distinguish them — but would have no concept that they are related parts of the same bundle, making crash recovery and Drive organization impossible.

### What Bundle Detection Must Extract From Every Filename

For every file the script encounters, it must analyze the filename and extract:

- **base_name**: The series name with the serial number stripped out. Example: "StationX - The Complete Python for Hacking Bundle" (with ".zip.001" removed)
- **part_number**: The integer sequential number. Example: 1 (from ".001"), 3 (from ".part3"), 2 (from "Vol. 2")
- **is_part**: True if a serial number was detected, False if this is a standalone file
- **bundle_id**: A normalized, lowercased, slug-style string used as a grouping key and Drive subfolder name. Example: "stationx-complete-python-hacking-bundle-zip"

### Serial Number Patterns the Detector Must Recognize

The detector must strip all of these patterns:

| Pattern | Example | Extracted Part |
|---|---|---|
| Three-digit numeric extension | `file.zip.001` | 1 |
| `.partN` before extension | `file.part3.rar` | 3 |
| Word "part" followed by number | `Course Part 2.zip` | 2 |
| Word "vol" or "volume" followed by number | `Course Vol.3.zip` | 3 |
| Parenthesized number at end | `Course (4).zip` | 4 |
| Hyphen or underscore then number at end | `Course - 5.zip` | 5 |

If none of these patterns match, the file is treated as a standalone file (part_number = 0).

### The Composite Deduplication Key

The script must use this three-part composite key for all duplicate checks:

```
( bundle_id , part_number , file_size_bytes )
```

This key is unique because:
- Two files from the same bundle with the same part number and same size = identical file = DUPLICATE
- Two files from the same bundle with the same part number but different sizes = updated/corrected version = PROCESS IT
- Two files from the same bundle with different part numbers = different parts = PROCESS BOTH
- Two files from different bundles even with the same size = different content = PROCESS BOTH

---

## Part 4 — The Deduplication Check

### When the Check Runs

The deduplication check must run **before any download begins**. No file should ever be downloaded, uploaded to Drive, or touched in any way until after the dedup check confirms it is not already in the destination channel.

### How the Dedup Index Is Built

At startup, before processing any posts, the script must:

1. Fetch the most recent posts from the **destination channel** (the one the bot posts to, where the admin rights are)
2. For each post in the destination channel, run bundle detection on the filename and build the composite key `(bundle_id, part_number, file_size_bytes)`
3. Store all these keys in a set in memory — this is the dedup index
4. Fetch at least the last 500 posts from the destination channel when building this index (increase if the channel has more posts)

### How the Check Works During Processing

When the script is about to process a post from the source channel:

1. Extract the filename from the message
2. Get the file size in bytes from the message metadata (this does not require downloading — it is in the document metadata)
3. Run bundle detection on the filename to get `bundle_id` and `part_number`
4. Build the composite key `(bundle_id, part_number, file_size_bytes)`
5. Check if this key exists in the in-memory dedup index
6. If YES: log it as a duplicate, update `state.json` to mark this message ID as processed with a "duplicate" flag, and move to the next post — **do not download anything**
7. If NO: proceed with the download pipeline

### How the Dedup Index Stays Updated in Live Mode

When a file is successfully uploaded to the destination channel, the script must immediately add its composite key to the in-memory dedup index. This ensures that if the same file appears again in the source channel's live feed (rare but possible), it is correctly identified as a duplicate without needing to re-query the destination channel.

---

## Part 5 — The Download and Upload Pipeline

### This Is the Sequence for Every Non-Duplicate File

The script must follow this exact sequence for every file it processes. Skipping or reordering these steps is not allowed.

**Step 1 — Download from source channel via Telethon**

The file must be downloaded from the source channel message using `client.download_media()`. This uses the MTProto protocol and can handle files up to 4 GB. The file must be saved to a temporary directory (`/temp/`) with a filename that includes the original message ID to avoid collisions. The script must print/log the download progress percentage. After download completes, verify the file exists on disk and its size on disk matches the size reported in the Telegram message metadata.

**Step 2 — Upload the file to Google Drive (into the bundle subfolder)**

The file must be uploaded to Google Drive using a **resumable upload** with 100 MB chunks. Resumable upload is mandatory — standard upload will fail or timeout for 3–5 GB files. The file must be placed inside a bundle-specific subfolder, not in the root `TelegramArchive` folder. The subfolder name is the `bundle_id` from the bundle detector. If the subfolder does not exist, create it automatically before uploading. After the upload completes, Drive returns a file ID — save this ID for the verification step later.

**Step 3 — Delete the local temporary download**

After the Drive upload confirms completion (not before), delete the local downloaded file from `/temp/`. This frees disk space before the next step. Do not delete the local file if the Drive upload failed or was interrupted.

**Step 4 — Re-download the file from Google Drive**

Download the same file back from Drive to a new local path in `/temp/`. Use a different filename than Step 1 to avoid confusion (prefix with `up_` instead of `dl_`). This step exists because: (a) Drive is the archive/backup, so this confirms the file is intact in Drive before posting to Telegram, and (b) if the subsequent Telegram upload fails, retrying re-downloads from Drive rather than from the source Telegram channel, which is faster and avoids hitting source channel rate limits.

**Step 5 — Upload to the destination Telegram channel**

The bot client (not the user client) uploads the file to the destination channel. The caption must be the original filename from the source post — this is critical because the caption/filename is what the deduplication engine uses on future runs to build the dedup index. If the caption differs from the original filename, future runs will fail to detect it as a duplicate. The upload must use `send_file()` via Telethon with the bot session. After upload, Telegram returns a message ID — log this.

**Step 6 — Delete the local staging file**

After the Telegram upload confirms completion, delete the re-downloaded file from `/temp/`. Do not delete it if the upload failed.

**Step 7 — Upload verification**

Query the destination channel for its most recently posted message. Extract the filename and file size from that message. Compare these against the metadata of the most recently uploaded file in this bundle's Drive subfolder. If filename and size match: the upload was successful and the Drive copy can be deleted. If they do not match: do NOT delete the Drive file. Log a warning with both values so the mismatch can be investigated manually.

**Step 8 — Delete from Drive (only if Step 7 passed)**

Only if Step 7 confirmed a match, delete the file from Drive using the file ID saved in Step 2. This cleans up storage. The Drive subfolder should remain even if empty — it may receive more parts of the same bundle later.

**Step 9 — Update state.json**

Mark the message ID as processed in `state.json`. If the file is part of a bundle, also update the bundle's completion record (add the part number to `parts_completed`). Update the `last_processed_id` to the maximum of its current value and this message ID. Add the composite dedup key to the in-memory dedup index.

---

## Part 6 — State Tracking Requirements

### What state.json Must Track

The script must maintain a `state.json` file that contains at minimum:

- `last_processed_id`: the highest message ID that has been fully processed
- `processed_ids`: a list of all message IDs that have been handled (processed, duplicate, or failed)
- `mode`: either "historical" or "live"
- `total_processed`: count of files actually uploaded (not duplicates, not failed)
- `skipped_duplicates`: count of messages skipped because they were duplicates
- `failed_ids`: list of message IDs that failed, with error messages and bundle info
- `bundles`: a dictionary keyed by `bundle_id` containing completion status for each bundle

### The Bundle Completion Record

For each bundle that has been encountered, `state.json` must record:

- `display_name`: the human-readable series name (base_name from bundle detector)
- `total_parts_seen`: the highest part number encountered so far
- `parts_completed`: list of part numbers successfully uploaded
- `parts_failed`: list of part numbers that failed

This allows a human reading `state.json` to immediately see: "Bundle X has 5 parts. Parts 1, 2, 3, 5 are done. Part 4 failed and needs retry."

### When state.json Must Be Written

`state.json` must be written to disk after EVERY individual file is fully completed (success, duplicate, or failure). It must never be written only at the end of a batch — crashes happen mid-batch and the state must survive any crash.

### How Crash Recovery Works

If the script crashes at any point during processing:

1. On restart, it reads `state.json`
2. The `processed_ids` list tells it exactly which messages have been handled
3. The `last_processed_id` tells Telethon's `GetHistoryRequest` to fetch only messages with higher IDs
4. The dedup engine also reloads from the destination channel — this is a second layer of protection if `state.json` is ever corrupted
5. Processing resumes from exactly where it left off

The key design rule: **a message ID is only added to `processed_ids` and `state.json` after the entire pipeline for that message completes successfully**. If the script crashes partway through processing a file, that file's message ID is not in `processed_ids`, so it will be retried on the next run.

---

## Part 7 — Error Handling Rules

### For Network Errors During Telegram Download

If Telethon throws a connection error during download: retry up to 3 times with exponential backoff (5s, 15s, 45s). If all 3 retries fail: mark the message ID as failed in `state.json` with the error message, delete any partial local temp file, and continue to the next message. Never stop the entire run because one file failed.

### For Google Drive Upload Failures

If a Drive upload fails mid-way: do not delete the partial local file. The resumable upload can be retried from where it left off. Retry up to 3 times. If all retries fail: mark as failed, delete local file, continue.

### For Telegram FloodWaitError

When Telegram returns a FloodWait error (rate limiting): read the required wait time from the error, sleep for that duration plus 5 extra seconds, then retry the exact same operation once. Do not mark the message as failed due to FloodWait — it is a temporary condition, not a permanent failure.

### For Disk Space Errors

If a disk space error occurs during any file operation: immediately stop processing, send an alert (log the error prominently), and halt the agent. Do not attempt to continue processing with insufficient disk space, as partial downloads may corrupt the temp directory.

### For Session Expiry

If Telethon throws an AuthKeyError or similar session error: log the error clearly, stop the agent. Do not attempt to re-authenticate automatically because authentication requires interactive input (phone number + verification code). The user must manually delete the session file and re-run the script to authenticate.

---

## Part 8 — Logging Requirements

### What Must Be Logged for Every File

For each file processed, the log must contain:

- The source channel message ID
- The original filename
- The file size in MB
- The detected bundle_id and part number
- Whether it was detected as a duplicate (and skip reason)
- Progress percentage for each major step (download, Drive upload, Drive download, Telegram upload)
- Whether the upload verification passed or failed (with both values if failed)
- Whether the Drive file was deleted or kept
- Total time taken to process this file

### Log Level Rules

- Normal progress (each percentage update): print to console only, not to file (too verbose)
- Step completion (downloaded, uploaded, verified, deleted): INFO level to both console and file
- Duplicates detected: INFO level
- Verification mismatches: WARNING level
- Failed files: ERROR level with full exception traceback
- FloodWait events: WARNING level

---

## Part 9 — What the Script Must Log to Console vs File

The script must write structured logs to both the console and a rotating log file simultaneously. Console output is for real-time monitoring. Log file is for historical debugging and the n8n monitoring workflows that read it.

The log file path is configured in `.env` as `LOG_FILE`. The log must rotate daily and keep 14 days of history.

---

## Part 10 — Constraints and Rules the Script Must Never Violate

1. **Never process two files simultaneously.** Even in live mode, if a new post arrives while another is being processed, queue it and wait.

2. **Never delete a local temp file before confirming the previous step succeeded.** Local file after download: do not delete until Drive upload confirms. Local file after Drive re-download: do not delete until Telegram upload confirms.

3. **Never delete a Drive file without passing the verification check.** The verification check is non-negotiable. Drive is the safety net.

4. **Never skip the dedup check.** Even if running in historical mode where duplicates seem impossible, always run the dedup check. The dedup check is what prevents catastrophic re-uploading if `state.json` is lost.

5. **Never post a file with a modified caption.** The caption posted to the destination channel must be exactly the original filename from the source. Do not add prefixes, suffixes, emojis, or any additional text unless explicitly configured.

6. **Never resume processing at the wrong position.** The `last_processed_id` is the source of truth for where to resume. Never recalculate this from scratch — always read from `state.json`.

7. **Never ignore a FloodWait error.** Always sleep for the full required duration. Attempting to continue processing during a FloodWait will result in account restrictions.

8. **Never run two instances of the script simultaneously.** Running two instances causes race conditions in `state.json`, duplicate Drive uploads, and duplicate Telegram posts. The systemd service configuration prevents this, but the script should also check for a lockfile at startup.

---

## Part 11 — Configuration the Script Must Read from `.env`

| Variable | What It Is |
|---|---|
| `TG_API_ID` | Integer API ID from my.telegram.org |
| `TG_API_HASH` | String API hash from my.telegram.org |
| `BOT_TOKEN` | Bot token from BotFather (used only for the bot client that posts) |
| `SOURCE_CHANNEL` | Username of the public source channel (without @) |
| `DEST_CHANNEL_ID` | Numeric ID of the destination channel (format: -100XXXXXXXXXX) |
| `DRIVE_ROOT_FOLDER_ID` | ID of the TelegramArchive root folder in Google Drive |
| `CREDENTIALS_PATH` | Absolute path to the Google service account JSON file |
| `TEMP_DIR` | Absolute path to the temporary file directory |
| `STATE_FILE` | Absolute path to state.json |
| `LOG_FILE` | Absolute path to the log file |

The script must fail immediately with a clear error message if any of these variables are missing or empty.

---

## Part 12 — Summary of Decision Rules for the Script

When you ask an AI to write or review this script, it must make these decisions automatically:

| Situation | Decision |
|---|---|
| File's composite key (bundle_id + part + size) is in dedup index | Skip immediately, mark as duplicate |
| File's composite key is NOT in dedup index | Begin download pipeline |
| Drive upload fails | Retry 3x, then mark as failed and continue |
| Telegram FloodWait received | Sleep required duration + 5s, retry once |
| Upload verification fails (name/size mismatch) | Keep Drive file, log warning, still mark message as processed |
| Upload verification passes | Delete Drive file |
| Crash recovery on restart | Read state.json, skip all message IDs in processed_ids |
| New post arrives during live mode while processing another file | Queue it, process after current file completes |
| Session authentication error | Stop agent, require manual re-authentication |
| Disk full error | Stop agent immediately, alert via log |
| File has no document attached | Mark as processed (no action needed) |
| File is part of a bundle (is_part = True) | Upload to bundle subfolder in Drive, track in bundles section of state.json |
| File is standalone (is_part = False) | Upload to a subfolder named after the file itself |

---

*Specification v3.0 | For use as a prompt guide, developer spec, or AI instruction document*
