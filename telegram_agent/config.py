"""
Project config with Django-style BASE_DIR. Paths in .env can be relative to project root
(e.g. data/temp, data/logs) and work on any OS. Absolute paths are left unchanged.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Project root (parent of this package = telegram-bot/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_path(path: str) -> str:
    """If path is relative, resolve against BASE_DIR; otherwise normalize and return."""
    if not path:
        return path
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(BASE_DIR, path))


# Paths: resolve relative to BASE_DIR so .env can use data/temp, data/logs, etc.
_state = os.getenv('STATE_FILE') or 'data/state.json'
_temp = os.getenv('TEMP_DIR') or 'data/temp'
_log = os.getenv('LOG_FILE') or 'data/logs/agent.log'
_creds = os.getenv('CREDENTIALS_PATH') or 'data/credentials.json'

STATE_FILE = resolve_path(_state)
TEMP_DIR = resolve_path(_temp)
LOG_FILE = resolve_path(_log)
CREDENTIALS_PATH = resolve_path(_creds)

# So os.getenv() elsewhere returns resolved paths (Django-style)
os.environ['STATE_FILE'] = STATE_FILE
os.environ['TEMP_DIR'] = TEMP_DIR
os.environ['LOG_FILE'] = LOG_FILE
os.environ['CREDENTIALS_PATH'] = CREDENTIALS_PATH

# Non-path env (other modules use os.getenv for these)
DRIVE_ROOT_FOLDER_ID = os.getenv('DRIVE_ROOT_FOLDER_ID')
