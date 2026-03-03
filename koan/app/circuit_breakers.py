"""Governor — Circuit breakers for external services.

Provides pybreaker-based circuit breakers for:
- google_secret_manager
- github_api
- gitlab_api
- google_chat
- litellm

Parameters (fail_max, reset_timeout) are loaded from config.yaml
section governor.circuit_breakers. A LogListener logs state transitions.

Usage:
    from app.circuit_breakers import get_breaker
    breaker = get_breaker("github_api")
    with breaker:
        response = requests.get(...)
"""

import logging
from typing import Dict, Optional

import pybreaker

from app.utils import load_config

logger = logging.getLogger("governor.circuit_breakers")

BREAKER_NAMES = [
    "google_secret_manager",
    "github_api",
    "gitlab_api",
    "google_chat",
    "litellm",
]

DEFAULTS = {
    "google_secret_manager": {"fail_max": 3, "reset_timeout_seconds": 120},
    "github_api": {"fail_max": 5, "reset_timeout_seconds": 60},
    "gitlab_api": {"fail_max": 5, "reset_timeout_seconds": 60},
    "google_chat": {"fail_max": 3, "reset_timeout_seconds": 30},
    "litellm": {"fail_max": 3, "reset_timeout_seconds": 300},
}


class _LogListener(pybreaker.CircuitBreakerListener):
    """Logs circuit breaker state transitions."""

    def state_change(self, cb, old_state, new_state):
        logger.warning(
            "Circuit breaker '%s': %s → %s",
            cb.name, old_state.name, new_state.name,
        )

    def failure(self, cb, exc):
        logger.debug("Circuit breaker '%s' recorded failure: %s", cb.name, exc)


_listener = _LogListener()
_breakers: Dict[str, pybreaker.CircuitBreaker] = {}


def _load_cb_config() -> dict:
    """Load circuit breaker config from config.yaml."""
    config = load_config()
    return config.get("governor", {}).get("circuit_breakers", {})


def make_breaker(name: str) -> pybreaker.CircuitBreaker:
    """Create a circuit breaker with config from config.yaml or defaults."""
    cb_config = _load_cb_config()
    params = cb_config.get(name, DEFAULTS.get(name, {}))
    fail_max = params.get("fail_max", 5)
    reset_timeout = params.get("reset_timeout_seconds", 60)

    return pybreaker.CircuitBreaker(
        name=name,
        fail_max=fail_max,
        reset_timeout=reset_timeout,
        listeners=[_listener],
    )


def get_breaker(name: str) -> pybreaker.CircuitBreaker:
    """Get or create a circuit breaker by name.

    Breakers are singletons — created once and reused.
    """
    if name not in _breakers:
        _breakers[name] = make_breaker(name)
    return _breakers[name]


def get_all_breakers() -> Dict[str, pybreaker.CircuitBreaker]:
    """Return all initialized breakers (for health/status reporting)."""
    return dict(_breakers)


def reset_all():
    """Reset all circuit breakers (for testing)."""
    for cb in _breakers.values():
        cb.close()
    _breakers.clear()
