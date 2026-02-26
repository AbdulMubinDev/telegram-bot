"""
State manager for Telegram repost agent (v3.0).
Persists last_processed_id, processed_ids, bundles, failed_ids to state.json.
"""
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
