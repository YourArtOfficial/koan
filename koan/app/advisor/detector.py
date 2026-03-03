"""Detector — KNN similarity search via SQLite-vec.

Provides:
- find_similar_repos: search indexed files for similar code/functionality
- find_similar_mcp: search MCP catalog for similar data resources
- find_similar_citizens: find citizen repos working on similar projects
"""

import logging

from app.advisor.helpers import (
    get_db, load_repo_index, load_mcp_catalog, serialize_embedding,
    PLATFORM_GITHUB,
)

logger = logging.getLogger("advisor.detector")


def find_similar_repos(embedding: list[float], top_k: int = 5,
                       threshold: float = 0.60,
                       platform_filter: str | None = None) -> list[dict]:
    """Search indexed file summaries for similar content via KNN.

    Args:
        embedding: query embedding vector
        top_k: number of results to return
        threshold: minimum similarity score (cosine)
        platform_filter: filter by platform (e.g. "gitlab" for prod code)

    Returns:
        list of {repo_id, file_path, summary, similarity_score}
    """
    if not embedding:
        return []

    conn = get_db()
    results = []

    try:
        blob = serialize_embedding(embedding)

        rows = conn.execute(
            """SELECT rowid, distance
               FROM vec_file_summaries
               WHERE summary_embedding MATCH ?
               AND k = ?""",
            (blob, top_k * 3),
        ).fetchall()

        for row_id, distance in rows:
            similarity = 1.0 - distance
            if similarity < threshold:
                continue

            file_row = conn.execute(
                "SELECT repo_id, file_path, summary FROM file_summaries WHERE id = ?",
                (row_id,),
            ).fetchone()

            if not file_row:
                continue

            repo_id, file_path, summary = file_row

            if platform_filter:
                repo_platform = repo_id.split("/")[0] if "/" in repo_id else ""
                if repo_platform != platform_filter:
                    continue

            results.append({
                "repo_id": repo_id,
                "file_path": file_path,
                "summary": summary,
                "similarity_score": round(similarity, 3),
            })

        results.sort(key=lambda r: r["similarity_score"], reverse=True)
        return results[:top_k]

    except Exception as e:
        logger.error("KNN search error: %s", e)
        return []


def find_similar_mcp(embedding: list[float], top_k: int = 5,
                     threshold: float = 0.60) -> list[dict]:
    """Search MCP catalog embeddings for similar data resources.

    Args:
        embedding: query embedding vector
        top_k: number of results to return
        threshold: minimum similarity score

    Returns:
        list of {resource_id, name, description, similarity_score, mcp_tool}
    """
    if not embedding:
        return []

    conn = get_db()
    catalog = load_mcp_catalog()
    catalog_by_id = {r.get("id"): r for r in catalog}
    results = []

    try:
        blob = serialize_embedding(embedding)

        rows = conn.execute(
            """SELECT rowid, distance
               FROM vec_mcp_embeddings
               WHERE description_embedding MATCH ?
               AND k = ?""",
            (blob, top_k * 2),
        ).fetchall()

        for row_id, distance in rows:
            similarity = 1.0 - distance
            if similarity < threshold:
                continue

            mcp_row = conn.execute(
                "SELECT resource_id, description FROM mcp_embeddings WHERE id = ?",
                (row_id,),
            ).fetchone()

            if not mcp_row:
                continue

            resource_id, description = mcp_row
            resource_info = catalog_by_id.get(resource_id, {})

            results.append({
                "resource_id": resource_id,
                "name": resource_info.get("name", resource_id),
                "description": description,
                "similarity_score": round(similarity, 3),
                "mcp_tool": resource_info.get("mcp_tool", ""),
            })

        results.sort(key=lambda r: r["similarity_score"], reverse=True)
        return results[:top_k]

    except Exception as e:
        logger.error("MCP KNN search error: %s", e)
        return []


def find_similar_citizens(repo_id: str, embedding: list[float],
                          top_k: int = 3) -> list[dict]:
    """Find citizen repos working on similar projects.

    Args:
        repo_id: source repo to exclude from results
        embedding: query embedding vector
        top_k: number of results

    Returns:
        list of {repo_id, owner, owner_name, summary, similarity_score}
    """
    if not embedding:
        return []

    similar = find_similar_repos(embedding, top_k=top_k * 2,
                                 threshold=0.50, platform_filter=PLATFORM_GITHUB)

    index = load_repo_index()
    index_by_id = {r["id"]: r for r in index}

    results = []
    for match in similar:
        if match["repo_id"] == repo_id:
            continue

        repo_info = index_by_id.get(match["repo_id"], {})
        if repo_info.get("owner_type") != "citizen":
            continue

        results.append({
            "repo_id": match["repo_id"],
            "owner": repo_info.get("owner", ""),
            "owner_name": repo_info.get("owner_name"),
            "summary": repo_info.get("summary", match.get("summary", "")),
            "similarity_score": match["similarity_score"],
        })

    return results[:top_k]
