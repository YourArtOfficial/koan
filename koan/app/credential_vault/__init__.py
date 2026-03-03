"""Credential Vault — Google Secret Manager integration for AI Governor.

Provides:
- gsm_client: CRUD operations on Google Secret Manager secrets
- registry: Metadata registry for secrets (vault_registry.yaml)
- grants: Citizen-to-project authorization management (vault_grants.yaml)
- injector: Temporary .env file generation with TTL
- scanner: Credential leak detection via detect-secrets
- audit: Cloud Audit Logs querying and anomaly detection
"""

import logging

__version__ = "0.1.0"

logger = logging.getLogger("credential_vault")


def _health_check() -> dict:
    """Health check for the credential vault module."""
    try:
        from app.credential_vault.helpers import get_gsm

        gsm = get_gsm()
        secrets_count = gsm.count_secrets()

        return {
            "status": "ok",
            "gsm_reachable": True,
            "secrets_count": secrets_count,
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "gsm_reachable": False}


try:
    from app.health import register_check
    register_check("credential_vault", _health_check, critical=True)
except ImportError:
    pass
