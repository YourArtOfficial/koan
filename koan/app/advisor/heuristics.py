"""Regex heuristics for data access pattern detection in diffs."""

import logging
import re

logger = logging.getLogger("advisor.heuristics")

DEFAULT_DATA_PATTERNS = {
    "sql": [r"CREATE TABLE", r"SELECT.*FROM", r"psycopg2", r"sqlalchemy"],
    "nosql": [r"pymongo", r"MongoClient", r"collection\.", r"aggregate"],
    "bigquery": [r"google-cloud-bigquery", r"bigquery\.Client", r"INFORMATION_SCHEMA"],
    "hubspot": [r"hubspot", r"HubSpot", r"crm\.properties"],
    "analytics": [r"navigation", r"page_view", r"session", r"user_event", r"GA4"],
    "search": [r"elasticsearch", r"Elasticsearch", r"algolia", r"meilisearch"],
}

_compiled_patterns: dict[str, list[re.Pattern]] | None = None


def _get_compiled_patterns() -> dict[str, list[re.Pattern]]:
    """Load and compile data patterns (cached at module level)."""
    global _compiled_patterns
    if _compiled_patterns is not None:
        return _compiled_patterns

    from app.utils import load_config
    config = load_config().get("advisor", {})
    raw = config.get("data_patterns", DEFAULT_DATA_PATTERNS)

    _compiled_patterns = {}
    for category, regexes in raw.items():
        compiled = []
        for regex in regexes:
            try:
                compiled.append(re.compile(regex, re.IGNORECASE))
            except re.error as e:
                logger.warning("Invalid regex '%s' in category '%s': %s",
                               regex, category, e)
        _compiled_patterns[category] = compiled

    return _compiled_patterns


def scan_for_data_patterns(diff_text: str) -> list[str]:
    """Scan diff text for data access patterns.

    Args:
        diff_text: raw diff content or code content

    Returns:
        list of matched pattern categories (e.g. ["sql", "bigquery"])
    """
    if not diff_text:
        return []

    patterns = _get_compiled_patterns()
    matched = []

    for category, compiled_list in patterns.items():
        for pattern in compiled_list:
            if pattern.search(diff_text):
                matched.append(category)
                break

    return matched
