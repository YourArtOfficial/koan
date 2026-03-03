"""Advisor — Cross-platform duplication detection for AI Governor.

Provides:
- helpers: Config loading, YAML persistence, LLM calls, embedding, detection tracking
- heuristics: Regex patterns for data access detection (SQL, MongoDB, BigQuery, etc.)
- indexer: Semantic indexing of GitHub + GitLab repos (summaries, files, embeddings)
- catalog: MCP ArtMajeur resource catalog (build, refresh, search)
- analyzer: 5-pass commit analysis pipeline (heuristics → LLM summary → embedding → KNN → judge)
- detector: KNN similarity search via SQLite-vec (repos, MCP, citizens)
- notifier: Google Chat notifications for duplications and convergences
"""

import logging

__version__ = "0.1.0"

logger = logging.getLogger("advisor")


def _health_check() -> dict:
    """Health check for the advisor module."""
    try:
        from app.advisor.helpers import get_db_path, load_repo_index

        db_path = get_db_path()
        db_exists = db_path.exists()
        db_size_mb = round(db_path.stat().st_size / (1024 * 1024), 1) if db_exists else 0

        repos = load_repo_index()
        indexed_repos = len(repos)

        return {
            "status": "ok" if db_exists else "error",
            "db_exists": db_exists,
            "db_size_mb": db_size_mb,
            "indexed_repos": indexed_repos,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


try:
    from app.health import register_check
    register_check("advisor", _health_check, critical=False)
except ImportError:
    pass
