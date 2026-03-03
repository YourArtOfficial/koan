"""GitLab scan orchestrator — 2-pass strategy.

Pass 1: Detect active projects (last_activity_at check)
Pass 2: Scan commits/MRs only for active projects (incremental via timestamps)
"""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from app.watcher.github_client import load_scan_state, save_scan_state
from app.watcher.gitlab_client import GitLabClient
from app.watcher.normalizer import (
    normalize_gitlab_commit,
    normalize_gitlab_mr,
    normalize_gitlab_issue,
)
from app.watcher.journal import append_event
from app.watcher.helpers import classify_author, load_repos, save_repos, update_repo_in_list

logger = logging.getLogger("watcher.scanner")


def run_gitlab_scan(config: dict, instance_dir: Path) -> dict:
    """Run a full GitLab scan cycle.

    Returns a summary dict with: projects_scanned, new_commits, new_mrs,
    new_issues, duration_seconds.
    """
    start_time = time.time()
    gitlab_config = config.get("gitlab", {})
    timeout_minutes = gitlab_config.get("scan_timeout_minutes", 5)
    branches = gitlab_config.get("branches", ["main", "master"])

    summary = {
        "projects_scanned": 0,
        "new_commits": 0,
        "new_mrs": 0,
        "new_issues": 0,
        "duration_seconds": 0,
    }

    try:
        client = GitLabClient.from_config(config)
    except ValueError as e:
        logger.error("GitLab client init failed: %s", e)
        _notify_scan_error(instance_dir, str(e))
        return summary

    # Load state once, mutate in memory, save once at end
    state = load_scan_state(instance_dir)
    gitlab_state = state.setdefault("gitlab", {})
    projects_state = gitlab_state.setdefault("projects", {})

    # Load repos once, mutate in memory, save once at end
    repos = load_repos()

    # Pass 1: List active projects
    projects = client.list_group_projects()
    if not projects:
        logger.warning("No projects found in GitLab group")
        return summary

    for project in projects:
        elapsed = time.time() - start_time
        if elapsed > timeout_minutes * 60:
            logger.warning("Scan timeout after %.1fs", elapsed)
            break

        project_name = project["name"]
        project_id = project["id"]
        project_state = projects_state.get(project_name, {})

        # Pass 2: Scan commits for each configured branch
        last_commit_at = project_state.get("last_commit_at")
        for branch in branches:
            commits = client.get_recent_commits(
                project_id, since=last_commit_at, branch=branch
            )
            for commit in commits:
                event = normalize_gitlab_commit(
                    commit, project_name, branch=branch, classify_fn=classify_author
                )
                append_event(instance_dir, event)
                update_repo_in_list(repos, project_name, "gitlab", event.author, event.timestamp)
                summary["new_commits"] += 1

            if commits:
                newest = commits[0].get("created_at", last_commit_at)
                if not last_commit_at or (newest and newest > last_commit_at):
                    last_commit_at = newest

        if last_commit_at:
            projects_state.setdefault(project_name, {})["last_commit_at"] = last_commit_at

        summary["projects_scanned"] += 1

    # Scan group-level MRs
    global_last_mr = _get_latest_timestamp(projects_state, "last_mr_at")
    mrs = client.get_recent_merge_requests(since=global_last_mr)
    for mr in mrs:
        event = normalize_gitlab_mr(mr, classify_fn=classify_author)
        append_event(instance_dir, event)
        summary["new_mrs"] += 1

        if event.repo and event.repo != "unknown":
            mr_updated = mr.get("updated_at")
            if mr_updated:
                projects_state.setdefault(event.repo, {})["last_mr_at"] = mr_updated

    # Scan group-level issues
    global_last_issue = _get_latest_timestamp(projects_state, "last_issue_at")
    issues = client.get_recent_issues(since=global_last_issue)
    for issue in issues:
        event = normalize_gitlab_issue(issue, classify_fn=classify_author)
        append_event(instance_dir, event)
        summary["new_issues"] += 1

    # Single save of state and repos at end
    gitlab_state["last_scan"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_scan_state(instance_dir, state)
    save_repos(repos)

    summary["duration_seconds"] = time.time() - start_time
    logger.info(
        "GitLab scan complete: %d projects, %d commits, %d MRs, %d issues in %.1fs",
        summary["projects_scanned"],
        summary["new_commits"],
        summary["new_mrs"],
        summary["new_issues"],
        summary["duration_seconds"],
    )
    return summary


def _get_latest_timestamp(projects_state: dict, key: str) -> str | None:
    """Find the latest timestamp across all projects for a given key."""
    latest = None
    for pstate in projects_state.values():
        ts = pstate.get(key) if isinstance(pstate, dict) else None
        if ts and (not latest or ts > latest):
            latest = ts
    return latest


def _notify_scan_error(instance_dir: Path, error_msg: str) -> None:
    """Notify governors of a scan error."""
    try:
        from app.watcher.helpers import notify
        notify(f"Erreur scan GitLab : {error_msg}")
    except Exception as e:
        logger.warning("Failed to notify scan error: %s", e)
