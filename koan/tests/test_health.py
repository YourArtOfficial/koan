"""Tests for app.health — unified health endpoint (Blueprint + registry)."""

import pytest
from flask import Flask

from app.health import _checks, health_bp, get_health_report, register_check


@pytest.fixture(autouse=True)
def clean_checks():
    """Reset the internal _checks registry before each test."""
    _checks.clear()
    yield
    _checks.clear()


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Minimal Flask app with health blueprint registered."""
    monkeypatch.setenv("KOAN_ROOT", str(tmp_path))
    flask_app = Flask(__name__)
    flask_app.register_blueprint(health_bp)
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def test_register_check():
    """register_check adds the function and critical flag to the internal registry."""
    fn = lambda: {"status": "ok"}
    register_check("demo", fn, critical=True)

    assert "demo" in _checks
    assert _checks["demo"]["fn"] is fn
    assert _checks["demo"]["critical"] is True


def test_health_endpoint_all_ok(client):
    """All modules OK -> HTTP 200, status 'ok'."""
    register_check("mod_a", lambda: {"status": "ok"})
    register_check("mod_b", lambda: {"status": "ok"})

    resp = client.get("/health")
    assert resp.status_code == 200

    data = resp.get_json()
    assert data["status"] == "ok"
    assert "latency_ms" in data
    assert "timestamp" in data
    assert data["modules"]["mod_a"]["status"] == "ok"
    assert data["modules"]["mod_b"]["status"] == "ok"


def test_health_endpoint_degraded(client):
    """One module in error -> HTTP 207, status 'degraded'."""
    register_check("healthy", lambda: {"status": "ok"})
    register_check("broken", lambda: {"status": "error", "error": "db down"})

    resp = client.get("/health")
    assert resp.status_code == 207

    data = resp.get_json()
    assert data["status"] == "degraded"
    assert data["modules"]["healthy"]["status"] == "ok"
    assert data["modules"]["broken"]["status"] == "error"


def test_module_returns_metrics(client):
    """Custom metrics returned by a check function are included in the report."""
    register_check("cache", lambda: {
        "status": "ok",
        "hit_rate": 0.95,
        "entries": 1200,
    })

    resp = client.get("/health")
    data = resp.get_json()

    mod = data["modules"]["cache"]
    assert mod["status"] == "ok"
    assert mod["hit_rate"] == 0.95
    assert mod["entries"] == 1200


def test_check_raises_exception(client):
    """A check function that raises is caught and the module is marked as error."""
    def exploding():
        raise RuntimeError("connection refused")

    register_check("flaky", exploding)

    resp = client.get("/health")
    assert resp.status_code == 207

    data = resp.get_json()
    assert data["status"] == "degraded"
    assert data["modules"]["flaky"]["status"] == "error"
    assert "connection refused" in data["modules"]["flaky"]["error"]
