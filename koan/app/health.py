"""Governor — Unified health check endpoint.

Blueprint Flask exposing GET /health that aggregates health status
from all registered modules (watcher, advisor, budget_controller, credential_vault).

Each module registers a check function via register_check(name, fn, critical).
The endpoint returns a HealthReport JSON:
  - status: ok | degraded
  - latency_ms: total collection time
  - timestamp: ISO 8601
  - modules: dict of module → {status, ...metrics}

HTTP codes: 200 if all OK, 207 (Multi-Status) if degraded.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Callable, Dict

from flask import Blueprint, jsonify

logger = logging.getLogger("governor.health")

health_bp = Blueprint("health", __name__)

_checks: Dict[str, dict] = {}


def register_check(name: str, fn: Callable, critical: bool = False):
    """Register a module health check.

    Args:
        name: Module identifier (e.g. "watcher", "advisor").
        fn: Callable returning a dict of metrics. Must return {"status": "ok"|"error", ...}.
            If the function raises, the module is marked as error.
        critical: If True, a failure degrades the overall agent status.
    """
    _checks[name] = {"fn": fn, "critical": critical}
    logger.info("Health check registered: %s (critical=%s)", name, critical)


def _run_checks() -> dict:
    """Execute all registered checks and build the HealthReport."""
    start = time.monotonic()
    modules = {}
    has_error = False

    for name, check in _checks.items():
        try:
            result = check["fn"]()
            if not isinstance(result, dict):
                result = {"status": "ok"}
            if "status" not in result:
                result["status"] = "ok"
        except Exception as e:
            logger.warning("Health check failed for %s: %s", name, e)
            result = {"status": "error", "error": str(e)}

        if result["status"] != "ok":
            has_error = True

        modules[name] = result

    latency_ms = round((time.monotonic() - start) * 1000, 1)
    overall = "degraded" if has_error else "ok"

    return {
        "status": overall,
        "latency_ms": latency_ms,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "modules": modules,
    }


@health_bp.route("/health")
def health_endpoint():
    """GET /health — aggregated health report."""
    report = _run_checks()
    code = 200 if report["status"] == "ok" else 207
    return jsonify(report), code


def get_health_report() -> dict:
    """Programmatic access to the health report (used by skills)."""
    return _run_checks()
