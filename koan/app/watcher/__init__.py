"""Watcher — GitHub & GitLab monitoring for AI Governor.

Provides:
- normalizer: Unified event format (WatcherEvent) for both platforms
- journal: JSONL append-only event storage with filtering
- github_client: Webhook signature verification and catch-up
- gitlab_client: Read-only polling via python-gitlab
- webhook_handler: Flask routes for GitHub webhook reception
- scanner: GitLab periodic scan orchestrator
- notifier: Google Chat notifications (Cards v2, threading, queue)
- helpers: Config loading, author classification, repo tracking
"""

import logging

__version__ = "1.0.0"

logger = logging.getLogger("watcher")


def _health_check() -> dict:
    """Health check for the watcher module."""
    try:
        from app.watcher.helpers import load_repos, INSTANCE_DIR

        repos = load_repos()
        repos_count = len(repos)

        journal_dir = INSTANCE_DIR / "watcher" / "events"
        journal_ok = journal_dir.exists()

        events_today = 0
        if journal_ok:
            from datetime import date
            today_file = journal_dir / f"{date.today().isoformat()}.jsonl"
            if today_file.exists():
                events_today = sum(1 for _ in open(today_file))

        return {
            "status": "ok",
            "repos_count": repos_count,
            "journal_dir_ok": journal_ok,
            "events_today": events_today,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


try:
    from app.health import register_check
    register_check("watcher", _health_check, critical=False)
except ImportError:
    pass
