"""Topic dedupe across runs.

Actions runners are wiped between runs, so the memory of what has already been
covered lives in a JSON file that the workflow commits back to the repo. It
doubles as a readable history of what the bot has posted.
"""

import json
import time
from pathlib import Path

import config


def _load() -> dict:
    path = Path(config.STATE_FILE)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _save(data: dict) -> None:
    path = Path(config.STATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def _prune(data: dict) -> dict:
    cutoff = time.time() - config.DEDUPE_DAYS * 86400
    return {k: v for k, v in data.items() if v > cutoff}


def was_seen(topic: str) -> bool:
    return topic.lower().strip() in _prune(_load())


def mark_seen(topic: str) -> None:
    data = _prune(_load())
    data[topic.lower().strip()] = time.time()
    _save(data)
