"""Budget Controller — LiteLLM Proxy integration for AI Governor.

Provides:
- litellm_client: Admin API client for user/key/spend management
- webhook_handler: Flask route for budget alert webhooks
- alert_formatter: Human-readable alert message formatting
"""

__version__ = "0.1.0"


def _health_check() -> dict:
    """Health check for the budget controller module."""
    try:
        from app.budget_controller.litellm_client import LiteLLMClient
        from app.utils import load_config

        config = load_config()
        client = LiteLLMClient.from_config(config)
        client.health()

        keys = client.list_keys()
        active_keys = len(keys)

        return {
            "status": "ok",
            "litellm_reachable": True,
            "active_keys": active_keys,
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "litellm_reachable": False}


try:
    from app.health import register_check
    register_check("budget_controller", _health_check, critical=True)
except ImportError:
    pass
