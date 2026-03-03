"""Tests for app.circuit_breakers — pybreaker-based circuit breakers."""

import time
from unittest.mock import patch

import pybreaker
import pytest


@pytest.fixture(autouse=True)
def _clean_breakers():
    """Reset all breakers before and after each test."""
    from app.circuit_breakers import reset_all

    reset_all()
    yield
    reset_all()


def _mock_cb_config(data: dict):
    """Mock load_config to return a specific governor.circuit_breakers config."""
    full_config = {"governor": {"circuit_breakers": data}} if data else {}
    return patch("app.circuit_breakers.load_config", return_value=full_config)


class TestMakeBreakerDefaults:
    def test_make_breaker_uses_defaults_when_no_config(self):
        from app.circuit_breakers import DEFAULTS, make_breaker

        with _mock_cb_config({}):
            breaker = make_breaker("github_api")

        assert breaker.name == "github_api"
        assert breaker.fail_max == DEFAULTS["github_api"]["fail_max"]
        assert breaker.reset_timeout == DEFAULTS["github_api"]["reset_timeout_seconds"]

    def test_make_breaker_unknown_name_uses_hardcoded_fallback(self):
        from app.circuit_breakers import make_breaker

        with _mock_cb_config({}):
            breaker = make_breaker("unknown_service")

        assert breaker.name == "unknown_service"
        assert breaker.fail_max == 5
        assert breaker.reset_timeout == 60


class TestGetBreakerSingleton:
    def test_returns_same_instance(self):
        from app.circuit_breakers import get_breaker

        with _mock_cb_config({}):
            b1 = get_breaker("github_api")
            b2 = get_breaker("github_api")

        assert b1 is b2

    def test_different_names_return_different_instances(self):
        from app.circuit_breakers import get_breaker

        with _mock_cb_config({}):
            b1 = get_breaker("github_api")
            b2 = get_breaker("google_chat")

        assert b1 is not b2
        assert b1.name == "github_api"
        assert b2.name == "google_chat"


class TestBreakerOpensAfterFailures:
    def test_circuit_opens_after_fail_max(self):
        from app.circuit_breakers import make_breaker

        with _mock_cb_config({"test_svc": {"fail_max": 2, "reset_timeout_seconds": 60}}):
            breaker = make_breaker("test_svc")

        assert breaker.current_state == "closed"

        def _fail():
            raise ValueError("simulated failure")

        # First failure: under threshold, original ValueError re-raised
        with pytest.raises(ValueError):
            breaker.call(_fail)
        assert breaker.current_state == "closed"

        # Second failure: reaches fail_max, CircuitBreakerError raised, circuit opens
        with pytest.raises(pybreaker.CircuitBreakerError):
            breaker.call(_fail)
        assert breaker.current_state == "open"

        # Subsequent calls rejected immediately
        with pytest.raises(pybreaker.CircuitBreakerError):
            breaker.call(lambda: None)


class TestBreakerResetsAfterTimeout:
    def test_half_open_after_timeout(self):
        from app.circuit_breakers import make_breaker

        with _mock_cb_config({"test_svc": {"fail_max": 1, "reset_timeout_seconds": 1}}):
            breaker = make_breaker("test_svc")

        def _fail():
            raise ValueError("boom")

        # fail_max=1: first failure trips the circuit immediately
        with pytest.raises(pybreaker.CircuitBreakerError):
            breaker.call(_fail)

        assert breaker.current_state == "open"

        # Before timeout: calls are still rejected
        with pytest.raises(pybreaker.CircuitBreakerError):
            breaker.call(lambda: "ok")

        time.sleep(1.1)

        # After timeout: circuit allows a trial call (half-open internally),
        # and a success transitions it back to closed
        result = breaker.call(lambda: "ok")
        assert result == "ok"
        assert breaker.current_state == "closed"


class TestResetAll:
    def test_clears_all_breakers(self):
        from app.circuit_breakers import get_all_breakers, get_breaker, reset_all

        with _mock_cb_config({}):
            get_breaker("github_api")
            get_breaker("google_chat")

        assert len(get_all_breakers()) == 2

        reset_all()

        assert get_all_breakers() == {}

    def test_closes_open_breakers_before_clearing(self):
        from app.circuit_breakers import get_breaker, reset_all

        with _mock_cb_config({"github_api": {"fail_max": 1, "reset_timeout_seconds": 300}}):
            breaker = get_breaker("github_api")

        def _fail():
            raise ValueError("fail")

        # fail_max=1: trips immediately
        with pytest.raises(pybreaker.CircuitBreakerError):
            breaker.call(_fail)

        assert breaker.current_state == "open"

        reset_all()

        assert breaker.current_state == "closed"


class TestLoadConfigParams:
    def test_breaker_picks_up_custom_config(self):
        from app.circuit_breakers import make_breaker

        custom = {"github_api": {"fail_max": 10, "reset_timeout_seconds": 120}}
        with _mock_cb_config(custom):
            breaker = make_breaker("github_api")

        assert breaker.fail_max == 10
        assert breaker.reset_timeout == 120

    def test_config_overrides_defaults_completely(self):
        from app.circuit_breakers import DEFAULTS, make_breaker

        custom = {"google_chat": {"fail_max": 99, "reset_timeout_seconds": 999}}
        with _mock_cb_config(custom):
            breaker = make_breaker("google_chat")

        assert breaker.fail_max == 99
        assert breaker.reset_timeout == 999
        assert breaker.fail_max != DEFAULTS["google_chat"]["fail_max"]


class TestGetAllBreakers:
    def test_returns_copy(self):
        from app.circuit_breakers import get_all_breakers, get_breaker

        with _mock_cb_config({}):
            get_breaker("github_api")

        result = get_all_breakers()
        result.clear()

        assert len(get_all_breakers()) == 1
