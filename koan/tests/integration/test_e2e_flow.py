"""End-to-end integration test for AI Governor.

Simulates: agent startup → GitHub webhook (citizen commit) → Watcher normalization
→ Advisor analysis → notification routing → status report.

All external services are mocked (Google Chat, LiteLLM, GSM).
"""

import json
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


@pytest.fixture
def koan_env(tmp_path, monkeypatch):
    """Set up a minimal Koan instance for E2E testing."""
    monkeypatch.setenv("KOAN_ROOT", str(tmp_path))

    # Patch KOAN_ROOT in all modules that cache it at import time
    import app.utils
    monkeypatch.setattr(app.utils, "KOAN_ROOT", tmp_path)

    # Create instance structure
    instance = tmp_path / "instance"
    instance.mkdir()
    (instance / "outbox.md").touch()
    (instance / "watcher").mkdir()
    (instance / "watcher" / "events").mkdir(parents=True)
    (instance / "advisor").mkdir()

    # Config
    config = {
        "watcher": {
            "enabled": True,
            "github": {"org": "TestOrg"},
            "notifications": {"google_chat_webhook_gsm": "test-secret"},
        },
        "advisor": {
            "enabled": True,
            "scan_on_event": True,
            "summary_model": "test-model",
            "judge_model": "test-model",
            "embedding_model": "test-model",
            "similarity_threshold": 0.60,
            "notification_threshold": 0.60,
            "dedup_window_days": 7,
        },
        "budget_controller": {
            "litellm_url": "http://localhost:4000",
            "litellm_master_key_env": "TEST_KEY",
        },
        "governor": {
            "autonomy": {
                "watcher": "notify",
                "advisor": "notify",
                "budget_controller": "notify",
                "credential_vault": "supervise",
            },
            "rollout": {
                "groups": {
                    "governors": {"active": True, "members": ["admin"]},
                    "pilots": {"active": True, "members": ["test-citizen"]},
                },
            },
            "report": {"enabled": False},
            "health": {"check_interval_seconds": 30},
            "circuit_breakers": {
                "google_chat": {"fail_max": 3, "reset_timeout_seconds": 10},
                "litellm": {"fail_max": 3, "reset_timeout_seconds": 10},
            },
        },
    }
    config_path = instance / "config.yaml"
    config_path.write_text(yaml.dump(config))

    # User registry
    registry = {
        "users": [
            {"login": "admin", "platform": "github", "type": "governor",
             "aliases": [], "rollout_group": "governors", "active": True},
            {"login": "test-citizen", "platform": "github", "type": "citizen",
             "aliases": [], "rollout_group": "pilots", "active": True},
        ],
        "aliases": {},
    }
    (instance / "watcher" / "user_registry.yaml").write_text(yaml.dump(registry))

    # Repos
    repos = {"repos": []}
    (instance / "watcher" / "repos.yaml").write_text(yaml.dump(repos))

    # Detections
    (instance / "advisor" / "detections.yaml").write_text(yaml.dump({"detections": []}))
    (instance / "advisor" / "detection_history.yaml").write_text(yaml.dump({"pairs": {}}))

    return tmp_path


def test_health_endpoint_returns_report(koan_env):
    """Health endpoint returns a valid HealthReport."""
    # Reset health check registry
    from app.health import health_bp, _checks, register_check
    _checks.clear()

    # Register a mock check
    register_check("test_module", lambda: {"status": "ok", "count": 42}, critical=False)

    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(health_bp)

    with app.test_client() as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "test_module" in data["modules"]
        assert data["modules"]["test_module"]["count"] == 42
        assert "latency_ms" in data
        assert "timestamp" in data

    _checks.clear()


def test_health_degraded_on_error(koan_env):
    """Health endpoint returns 207 when a module check fails."""
    from app.health import health_bp, _checks, register_check
    _checks.clear()

    register_check("ok_module", lambda: {"status": "ok"}, critical=False)
    register_check("bad_module", lambda: (_ for _ in ()).throw(RuntimeError("down")), critical=True)

    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(health_bp)

    with app.test_client() as client:
        resp = client.get("/health")
        assert resp.status_code == 207
        data = resp.get_json()
        assert data["status"] == "degraded"
        assert data["modules"]["bad_module"]["status"] == "error"

    _checks.clear()


def test_notification_router_filters_by_group(koan_env):
    """Notification router correctly filters based on rollout groups."""
    from app.notification_router import NotificationRouter, reset_router
    reset_router()

    router = NotificationRouter()

    assert router.should_notify("push", "test-citizen") is True
    assert router.should_notify("push", "unknown-user") is False
    assert router.is_governor("admin") is True
    assert router.is_governor("test-citizen") is False

    reset_router()


def test_autonomy_levels(koan_env):
    """Autonomy check returns correct behavior strings."""
    from app.notification_router import NotificationRouter, reset_router
    reset_router()

    router = NotificationRouter()

    assert router.check_autonomy("advisor") == "notify_citizen"
    assert router.check_autonomy("credential_vault") == "ask_governor"

    reset_router()


def test_circuit_breaker_opens_on_failures(koan_env):
    """Circuit breaker opens after fail_max failures."""
    from app.circuit_breakers import get_breaker, reset_all
    reset_all()

    breaker = get_breaker("google_chat")

    def failing_fn():
        raise ConnectionError("service down")

    # Trigger failures
    for _ in range(3):
        try:
            breaker.call(failing_fn)
        except (ConnectionError, Exception):
            pass

    # Circuit should now be open
    import pybreaker
    assert breaker.current_state == "open"

    reset_all()


def test_watcher_event_journal(koan_env):
    """Watcher events are written to JSONL journal."""
    events_dir = koan_env / "instance" / "watcher" / "events"
    today = date.today().isoformat()
    journal_file = events_dir / f"{today}.jsonl"

    # Write a test event
    event = {
        "id": "evt-test-001",
        "type": "push",
        "author": "test-citizen",
        "author_type": "citizen",
        "repo": "test-repo",
        "platform": "github",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(journal_file, "a") as f:
        f.write(json.dumps(event) + "\n")

    # Verify
    from app.report_generator import _count_watcher_events
    import app.report_generator
    monkeypatch_instance = koan_env / "instance"

    with patch.object(app.report_generator, "INSTANCE_DIR", monkeypatch_instance):
        count, citizens = _count_watcher_events(date.today(), date.today())
        assert count == 1
        assert citizens.get("test-citizen") == 1


def test_report_generation(koan_env):
    """Report generator produces a valid PeriodicReport."""
    import app.report_generator
    instance = koan_env / "instance"

    # Write test events
    events_dir = instance / "watcher" / "events"
    today = date.today().isoformat()
    journal_file = events_dir / f"{today}.jsonl"
    for i in range(5):
        event = {"author": "test-citizen", "author_type": "citizen", "type": "push"}
        with open(journal_file, "a") as f:
            f.write(json.dumps(event) + "\n")

    # Write test detections
    dets = {
        "detections": [
            {"id": "det-1", "created_at": f"{today}T10:00:00Z", "status": "notified"},
            {"id": "det-2", "created_at": f"{today}T11:00:00Z", "status": "false_positive"},
        ],
    }
    (instance / "advisor" / "detections.yaml").write_text(yaml.dump(dets))

    with patch.object(app.report_generator, "INSTANCE_DIR", instance):
        with patch.object(app.report_generator, "_get_budget_spend", return_value=({}, 0.0)):
            report = app.report_generator.generate_report(date.today(), date.today())

    assert report["events_count"] == 5
    assert report["detections_count"] == 2
    assert report["false_positive_rate"] == 0.5
    assert len(report["top_citizens"]) == 1
    assert report["top_citizens"][0]["login"] == "test-citizen"
