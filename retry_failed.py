"""
Reset failed posts so they can be retried on the next run.
Removes failed_ids and clears failed parts from bundle tracking.
"""
import json
import os
from dotenv import load_dotenv

load_dotenv()
STATE_FILE = os.getenv('STATE_FILE', 'state.json')


def run_retry_failed() -> int:
    """
    Reset failed posts so they can be retried. Safe to call from code.
    Returns the number of failed posts that were reset.
    """
    if not os.path.exists(STATE_FILE):
        return 0
    with open(STATE_FILE, 'r') as f:
        state = json.load(f)
    failed_ids = [item['id'] for item in state['failed_ids']]
    state['processed_ids'] = [i for i in state['processed_ids'] if i not in failed_ids]
    for bid, bundle in state.get('bundles', {}).items():
        bundle['parts_failed'] = []
    state['failed_ids'] = []
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)
    return len(failed_ids)


def main():
    n = run_retry_failed()
    if n == 0:
        print("No failed posts to reset (or no state.json).")
    else:
        print(f"Reset {n} failed posts for retry.")
