"""JSONL event journal — append-only storage with file locking.

Events are stored as one JSON object per line in daily files:
  instance/watcher/events/YYYY-MM-DD.jsonl
"""

import fcntl
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.watcher.normalizer import WatcherEvent

logger = logging.getLogger("watcher.journal")


def _events_dir(instance_dir: Path) -> Path:
    return instance_dir / "watcher" / "events"


def _today_file(instance_dir: Path) -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return _events_dir(instance_dir) / f"{today}.jsonl"


def append_event(instance_dir: Path, event: WatcherEvent) -> None:
    """Append an event to today's JSONL file with file locking."""
    events_dir = _events_dir(instance_dir)
    events_dir.mkdir(parents=True, exist_ok=True)

    filepath = _today_file(instance_dir)
    line = json.dumps(event.to_dict(), ensure_ascii=False) + "\n"

    with open(filepath, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(line)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

    logger.debug("Event %s appended to %s", event.id, filepath.name)


def read_events(instance_dir: Path, days: int = 30, author: str | None = None,
                repo: str | None = None, type: str | None = None,
                platform: str | None = None, author_type: str | None = None,
                limit: int = 20, offset: int = 0) -> list[dict]:
    """Read and filter events from JSONL files.

    Reads files from the last `days` days, applies filters, returns
    events in reverse chronological order with pagination.
    """
    events_dir = _events_dir(instance_dir)
    if not events_dir.exists():
        return []

    now = datetime.now(timezone.utc)
    all_events = []

    for day_offset in range(days):
        day = now - timedelta(days=day_offset)
        filepath = events_dir / f"{day.strftime('%Y-%m-%d')}.jsonl"
        if not filepath.exists():
            continue

        try:
            with open(filepath, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if author and event.get("author") != author:
                        continue
                    if repo and event.get("repo") != repo:
                        continue
                    if type and event.get("type") != type:
                        continue
                    if platform and event.get("platform") != platform:
                        continue
                    if author_type and event.get("author_type") != author_type:
                        continue

                    all_events.append(event)
        except OSError as e:
            logger.warning("Error reading %s: %s", filepath, e)

    all_events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

    return all_events[offset:offset + limit]


def count_events_today(instance_dir: Path) -> int:
    """Count events in today's journal file."""
    filepath = _today_file(instance_dir)
    if not filepath.exists():
        return 0
    try:
        with open(filepath, "r") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def count_events_period(instance_dir: Path, days: int = 7) -> int:
    """Count events over a period."""
    events_dir = _events_dir(instance_dir)
    if not events_dir.exists():
        return 0

    now = datetime.now(timezone.utc)
    total = 0
    for day_offset in range(days):
        day = now - timedelta(days=day_offset)
        filepath = events_dir / f"{day.strftime('%Y-%m-%d')}.jsonl"
        if filepath.exists():
            try:
                with open(filepath, "r") as f:
                    total += sum(1 for line in f if line.strip())
            except OSError:
                pass
    return total


def get_last_event(instance_dir: Path) -> dict | None:
    """Get the most recent event."""
    events = read_events(instance_dir, days=1, limit=1)
    return events[0] if events else None
