"""GitHub webhook signature verification, deduplication, and catch-up.

Handles:
- HMAC-SHA256 signature verification for incoming webhooks
- Delivery deduplication via scan_state.yaml
- Catch-up of missed deliveries via GitHub API
"""

import hashlib
import hmac
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

from app.utils import atomic_write

logger = logging.getLogger("watcher.github_client")

MAX_DELIVERIES_CACHE = 1000

_webhook_secret_cache: tuple[str | None, float] = (None, 0.0)
_SECRET_CACHE_TTL = 300  # 5 minutes


def get_webhook_secret(instance_dir: Path) -> str | None:
    """Load the GitHub webhook secret from env var or GSM (cached 5 min)."""
    global _webhook_secret_cache
    cached_value, cached_at = _webhook_secret_cache
    if cached_value and (time.time() - cached_at) < _SECRET_CACHE_TTL:
        return cached_value

    env_secret = os.environ.get("GITHUB_WEBHOOK_SECRET")
    if env_secret:
        _webhook_secret_cache = (env_secret, time.time())
        return env_secret

    try:
        from app.credential_vault.helpers import get_gsm
        from app.watcher.helpers import get_watcher_config

        config = get_watcher_config()
        secret_name = config.get("github", {}).get("webhook_secret_gsm", "")
        if not secret_name:
            return None

        gsm = get_gsm()
        value = gsm.access_secret(secret_name)
        _webhook_secret_cache = (value, time.time())
        return value
    except (ImportError, ValueError, OSError) as e:
        logger.error("Failed to load webhook secret from GSM: %s", e)
        return None


def verify_github_signature(payload_body: bytes, secret: str,
                            signature_header: str) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature.

    Uses hmac.compare_digest for constant-time comparison (anti timing-attack).
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected_sig = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_sig, signature_header)


# ── Scan state management ────────────────────────────────────────────

def _scan_state_path(instance_dir: Path) -> Path:
    return instance_dir / "watcher" / "scan_state.yaml"


def load_scan_state(instance_dir: Path) -> dict:
    """Load scan_state.yaml."""
    path = _scan_state_path(instance_dir)
    if not path.exists():
        return {
            "github": {
                "webhook_id": None,
                "last_delivery_check": None,
                "processed_deliveries": [],
            },
            "gitlab": {"last_scan": None, "projects": {}},
        }
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as e:
        logger.error("Error loading scan_state: %s", e)
        return {}


def save_scan_state(instance_dir: Path, state: dict) -> None:
    """Save scan_state.yaml atomically."""
    path = _scan_state_path(instance_dir)
    content = yaml.dump(state, default_flow_style=False, allow_unicode=True, sort_keys=False)
    atomic_write(path, content)


def is_duplicate(instance_dir: Path, delivery_guid: str) -> bool:
    """Check if a delivery GUID has already been processed."""
    state = load_scan_state(instance_dir)
    processed = state.get("github", {}).get("processed_deliveries", [])
    return delivery_guid in set(processed)


def save_processed_delivery(instance_dir: Path, delivery_guid: str) -> None:
    """Add a delivery GUID to the processed list (sliding window)."""
    state = load_scan_state(instance_dir)
    github = state.setdefault("github", {})
    processed = github.setdefault("processed_deliveries", [])

    if delivery_guid not in set(processed):
        processed.append(delivery_guid)

    if len(processed) > MAX_DELIVERIES_CACHE:
        github["processed_deliveries"] = processed[-MAX_DELIVERIES_CACHE:]

    save_scan_state(instance_dir, state)


# ── Catch-up ─────────────────────────────────────────────────────────

def catch_up_deliveries(org: str, hook_id: int, token: str,
                        instance_dir: Path, normalize_and_store_fn=None) -> dict:
    """Fetch missed webhook deliveries from GitHub API.

    Lists recent deliveries via GET /orgs/{org}/hooks/{hook_id}/deliveries,
    compares with processed GUIDs, and processes the missing ones.
    Batches state saves to avoid N+1 file I/O.
    """
    state = load_scan_state(instance_dir)
    github = state.setdefault("github", {})
    processed = set(github.get("processed_deliveries", []))

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }

    url = f"https://api.github.com/orgs/{org}/hooks/{hook_id}/deliveries"
    params = {"per_page": 100}

    summary = {"checked": 0, "missed": 0, "recovered": 0, "errors": 0}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        deliveries = resp.json()
    except requests.RequestException as e:
        logger.error("Failed to fetch deliveries: %s", e)
        summary["errors"] = 1
        return summary

    summary["checked"] = len(deliveries)

    for delivery in deliveries:
        guid = delivery.get("guid", "")
        if guid in processed:
            continue

        summary["missed"] += 1

        detail_url = f"{url}/{delivery['id']}"
        try:
            detail_resp = requests.get(detail_url, headers=headers, timeout=30)
            detail_resp.raise_for_status()
            detail = detail_resp.json()

            if normalize_and_store_fn:
                payload = detail.get("request", {}).get("payload", {})
                event_type = detail.get("event", "unknown")
                normalize_and_store_fn(event_type, payload, guid)

            processed.add(guid)
            summary["recovered"] += 1
        except requests.RequestException as e:
            logger.error("Failed to fetch delivery %s: %s", guid, e)
            summary["errors"] += 1

    # Single batch save at the end
    processed_list = list(processed)
    if len(processed_list) > MAX_DELIVERIES_CACHE:
        processed_list = processed_list[-MAX_DELIVERIES_CACHE:]
    github["processed_deliveries"] = processed_list
    github["last_delivery_check"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    save_scan_state(instance_dir, state)

    return summary
