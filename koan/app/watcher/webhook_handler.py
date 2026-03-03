"""Flask webhook routes for GitHub event reception.

Registers POST /webhook/github and GET /webhook/github/health on the Flask app.
"""

import json
import logging
from pathlib import Path

from flask import Response, request

from app.watcher.normalizer import (
    normalize_github_push,
    normalize_github_pr,
    normalize_github_issue,
    normalize_github_create,
    normalize_github_member,
    normalize_github_repo,
    normalize_github_org,
)
from app.watcher.github_client import (
    verify_github_signature,
    get_webhook_secret,
    is_duplicate,
    save_processed_delivery,
)
from app.watcher.journal import append_event, count_events_today, get_last_event
from app.watcher.helpers import classify_author, update_repo_activity

logger = logging.getLogger("watcher.webhook_handler")

GITHUB_NORMALIZERS = {
    "push": normalize_github_push,
    "pull_request": normalize_github_pr,
    "issues": normalize_github_issue,
    "create": normalize_github_create,
    "member": normalize_github_member,
    "repository": normalize_github_repo,
    "organization": normalize_github_org,
}


def register_webhooks(app, instance_dir: Path):
    """Register GitHub webhook routes on the Flask app."""

    @app.route("/webhook/github", methods=["POST"])
    def github_webhook():
        payload_body = request.data
        event_type = request.headers.get("X-GitHub-Event", "")
        delivery_id = request.headers.get("X-GitHub-Delivery", "")
        signature = request.headers.get("X-Hub-Signature-256", "")

        if event_type == "ping":
            logger.info("Received GitHub ping webhook")
            return _json_response({"status": "pong"}, 200)

        secret = get_webhook_secret(instance_dir)
        if secret:
            if not verify_github_signature(payload_body, secret, signature):
                logger.warning("Invalid GitHub webhook signature")
                return _json_response(
                    {"status": "error", "message": "invalid signature"}, 403
                )
        else:
            logger.warning("No webhook secret configured — skipping signature verification")

        if delivery_id and is_duplicate(instance_dir, delivery_id):
            logger.debug("Duplicate delivery: %s", delivery_id)
            return _json_response({"status": "duplicate"}, 409)

        try:
            payload = json.loads(payload_body)
        except (json.JSONDecodeError, ValueError):
            return _json_response(
                {"status": "error", "message": "invalid JSON"}, 400
            )

        normalizer = GITHUB_NORMALIZERS.get(event_type)
        if not normalizer:
            logger.debug("Unsupported event type: %s", event_type)
            return _json_response({"status": "ignored", "event": event_type}, 200)

        try:
            event = normalizer(
                payload,
                delivery_id=delivery_id,
                classify_fn=classify_author,
            )

            append_event(instance_dir, event)

            if delivery_id:
                save_processed_delivery(instance_dir, delivery_id)

            if event.repo:
                update_repo_activity(
                    event.repo, "github", event.author, event.timestamp
                )

            _trigger_notifications(instance_dir, event)

            logger.info(
                "Processed %s event for %s by %s",
                event.type, event.repo, event.author,
            )

            return _json_response({"status": "received"}, 200)

        except Exception as e:
            logger.exception("Error processing %s event: %s", event_type, e)
            return _json_response(
                {"status": "error", "message": str(e)}, 500
            )

    @app.route("/webhook/github/health", methods=["GET"])
    def github_webhook_health():
        last = get_last_event(instance_dir)
        return _json_response({
            "status": "ok",
            "webhook_active": True,
            "last_event": last.get("timestamp") if last else None,
            "events_today": count_events_today(instance_dir),
        }, 200)


def _trigger_notifications(instance_dir: Path, event) -> None:
    """Check if event needs notification and queue it."""
    try:
        from app.watcher.helpers import check_and_notify
        check_and_notify(instance_dir, event)
    except ImportError:
        logger.debug("Notification module not available")
    except Exception as e:
        logger.warning("Notification check failed: %s", e)


def normalize_and_store(instance_dir: Path, event_type: str, payload: dict,
                        delivery_id: str) -> None:
    """Normalize a GitHub event and store it in the journal.

    Used by catch-up to process recovered deliveries.
    """
    normalizer = GITHUB_NORMALIZERS.get(event_type)
    if not normalizer:
        return

    event = normalizer(payload, delivery_id=delivery_id, classify_fn=classify_author)
    append_event(instance_dir, event)
    if event.repo:
        update_repo_activity(event.repo, "github", event.author, event.timestamp)


def _json_response(data: dict, status: int) -> Response:
    return Response(
        json.dumps(data),
        status=status,
        content_type="application/json",
    )
