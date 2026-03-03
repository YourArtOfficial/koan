"""Catalog — MCP ArtMajeur resource catalog management.

Provides:
- build_mcp_catalog: create comprehensive catalog with all known MCP resources
- refresh_mcp_catalog: update catalog by querying MCP tools
- search_mcp_catalog: semantic search against catalog embeddings
"""

import json
import logging
from datetime import datetime, timezone

from app.advisor.helpers import (
    get_db,
    embed_text,
    load_mcp_catalog,
    save_mcp_catalog,
    serialize_embedding,
    upsert_vec_embedding,
)

logger = logging.getLogger("advisor.catalog")

MCP_RESOURCES = [
    {
        "id": "sql_account",
        "type": "sql",
        "name": "Account",
        "description": "Utilisateurs de la plateforme ArtMajeur — collectionneurs, artistes, galeries. 98 colonnes incluant profil, préférences, abonnements, statistiques.",
        "key_fields": ["id", "email", "username", "type", "country", "created_at"],
        "mcp_tool": "db_execute_sql_query",
        "access_example": "SELECT id, username, type FROM Account WHERE country='FR' LIMIT 10",
    },
    {
        "id": "sql_artwork",
        "type": "sql",
        "name": "Artwork",
        "description": "Oeuvres d'art sur ArtMajeur — caractéristiques, prix, disponibilité, dimensions, matériaux. 89 colonnes.",
        "key_fields": ["id", "title", "artist_id", "price", "category", "status"],
        "mcp_tool": "db_execute_sql_query",
        "access_example": "SELECT id, title, price FROM Artwork WHERE category='painting' LIMIT 10",
    },
    {
        "id": "sql_artist",
        "type": "sql",
        "name": "Artist",
        "description": "Profils artistes ArtMajeur — biographie, spécialités, statistiques de ventes, collections.",
        "key_fields": ["id", "account_id", "specialty", "country"],
        "mcp_tool": "db_execute_sql_query",
        "access_example": "SELECT id, account_id, specialty FROM Artist LIMIT 10",
    },
    {
        "id": "sql_gallery",
        "type": "sql",
        "name": "Gallery",
        "description": "Galeries d'art sur ArtMajeur — profil galerie, artistes représentés, localisation.",
        "key_fields": ["id", "name", "account_id", "country"],
        "mcp_tool": "db_execute_sql_query",
        "access_example": "SELECT id, name, country FROM Gallery LIMIT 10",
    },
    {
        "id": "sql_artwork_embedding",
        "type": "sql",
        "name": "ArtworkEmbedding",
        "description": "Embeddings vectoriels des oeuvres pour la recherche par similarité visuelle.",
        "key_fields": ["artwork_id", "embedding"],
        "mcp_tool": "db_execute_sql_query",
        "access_example": "SELECT artwork_id FROM ArtworkEmbedding LIMIT 5",
    },
    {
        "id": "sql_collection",
        "type": "sql",
        "name": "Collection",
        "description": "Collections d'oeuvres créées par les artistes — regroupements thématiques.",
        "key_fields": ["id", "artist_id", "name"],
        "mcp_tool": "db_execute_sql_query",
        "access_example": "SELECT id, name FROM Collection LIMIT 10",
    },
    {
        "id": "sql_order",
        "type": "sql",
        "name": "Order",
        "description": "Commandes et transactions sur ArtMajeur — achats, paiements, statuts.",
        "key_fields": ["id", "buyer_id", "seller_id", "total", "status", "created_at"],
        "mcp_tool": "db_execute_sql_query",
        "access_example": "SELECT id, total, status FROM `Order` WHERE status='completed' LIMIT 10",
    },
    {
        "id": "sql_product",
        "type": "sql",
        "name": "Product",
        "description": "Produits dérivés (prints, reproductions) générés à partir des oeuvres originales.",
        "key_fields": ["id", "artwork_id", "type", "price"],
        "mcp_tool": "db_execute_sql_query",
        "access_example": "SELECT id, artwork_id, type, price FROM Product LIMIT 10",
    },
    {
        "id": "sql_invoice",
        "type": "sql",
        "name": "Invoice",
        "description": "Factures générées pour les commandes — détails fiscaux, montants, TVA.",
        "key_fields": ["id", "order_id", "amount", "tax"],
        "mcp_tool": "db_execute_sql_query",
        "access_example": "SELECT id, order_id, amount FROM Invoice LIMIT 10",
    },
    {
        "id": "sql_notification",
        "type": "sql",
        "name": "Notification",
        "description": "Notifications envoyées aux utilisateurs — alertes, messages, événements.",
        "key_fields": ["id", "account_id", "type", "read"],
        "mcp_tool": "db_execute_sql_query",
        "access_example": "SELECT id, type, read FROM Notification WHERE account_id=123 LIMIT 10",
    },
    {
        "id": "mongo_iris_search",
        "type": "mongodb",
        "name": "irisYourSearch",
        "description": "Sessions de recherche utilisateurs via l'assistant IA Iris — requêtes, résultats, interactions.",
        "key_fields": ["session_id", "query", "results", "created_at"],
        "mcp_tool": "mongo_execute_pipeline",
        "access_example": "db.irisYourSearch.aggregate([{$match: {created_at: {$gte: ISODate('2026-01-01')}}}, {$limit: 10}])",
    },
    {
        "id": "mongo_iris_chat",
        "type": "mongodb",
        "name": "irisYourChat",
        "description": "Conversations avec l'assistant IA Iris — messages, contexte, réponses générées.",
        "key_fields": ["session_id", "messages", "created_at"],
        "mcp_tool": "mongo_execute_pipeline",
        "access_example": "db.irisYourChat.aggregate([{$sort: {created_at: -1}}, {$limit: 10}])",
    },
    {
        "id": "mongo_iris_match",
        "type": "mongodb",
        "name": "irisYourMatch",
        "description": "Recommandations d'oeuvres par Iris — matching artiste-collectionneur basé sur les préférences.",
        "key_fields": ["user_id", "matches", "score"],
        "mcp_tool": "mongo_execute_pipeline",
        "access_example": "db.irisYourMatch.aggregate([{$sort: {score: -1}}, {$limit: 10}])",
    },
    {
        "id": "mongo_recsys",
        "type": "mongodb",
        "name": "recSysExperiments",
        "description": "Expériences du système de recommandation — A/B tests, métriques, résultats.",
        "key_fields": ["experiment_id", "variant", "metrics"],
        "mcp_tool": "mongo_execute_pipeline",
        "access_example": "db.recSysExperiments.aggregate([{$sort: {created_at: -1}}, {$limit: 5}])",
    },
    {
        "id": "bigquery_events",
        "type": "bigquery",
        "name": "events_YYYYMMDD",
        "description": "Données de navigation GA4 depuis mars 2025 — page views, sessions, événements utilisateur, parcours de navigation.",
        "key_fields": ["event_date", "event_name", "user_pseudo_id", "event_params"],
        "mcp_tool": "bigquery_execute_query",
        "access_example": "SELECT event_name, COUNT(*) FROM `analytics.events_*` WHERE _TABLE_SUFFIX >= '20260101' GROUP BY 1 LIMIT 10",
    },
    {
        "id": "bigquery_users",
        "type": "bigquery",
        "name": "users",
        "description": "Table des utilisateurs GA4 — propriétés utilisateur, première visite, dernière activité.",
        "key_fields": ["user_id", "user_properties", "first_touch"],
        "mcp_tool": "bigquery_execute_query",
        "access_example": "SELECT user_id, user_properties FROM `analytics.users` LIMIT 10",
    },
    {
        "id": "bigquery_pseudonymous",
        "type": "bigquery",
        "name": "pseudonymous_users",
        "description": "Utilisateurs pseudonymisés GA4 — identifiants anonymes, propriétés agrégées.",
        "key_fields": ["pseudo_user_id", "user_properties"],
        "mcp_tool": "bigquery_execute_query",
        "access_example": "SELECT pseudo_user_id FROM `analytics.pseudonymous_users` LIMIT 10",
    },
    {
        "id": "bigquery_action_logs",
        "type": "bigquery",
        "name": "action_logs",
        "description": "Logs d'actions internes — actions utilisateur et système trackées pour l'analyse.",
        "key_fields": ["action", "user_id", "timestamp", "metadata"],
        "mcp_tool": "bigquery_execute_query",
        "access_example": "SELECT action, COUNT(*) FROM `analytics.action_logs` GROUP BY 1 LIMIT 10",
    },
    {
        "id": "hubspot_emails",
        "type": "hubspot",
        "name": "Marketing emails",
        "description": "Emails marketing envoyés via HubSpot — campagnes, templates, statistiques d'envoi, taux d'ouverture.",
        "key_fields": ["id", "name", "subject", "stats"],
        "mcp_tool": "hubspot_list_marketing_emails",
        "access_example": "hubspot_list_marketing_emails(limit=10)",
    },
]


def build_mcp_catalog(config: dict) -> list[dict]:
    """Build the MCP catalog with all known resources and their embeddings.

    Returns list of MCPResource dicts.
    """
    now = datetime.now(timezone.utc).isoformat()
    resources = []

    conn = get_db()

    for resource in MCP_RESOURCES:
        entry = {**resource, "refreshed_at": now}

        embedding = embed_text(resource["description"], config)
        entry["embedding_generated"] = bool(embedding)

        if embedding:
            _store_mcp_embedding(conn, resource["id"], resource["description"], embedding)

        resources.append(entry)

    conn.commit()

    save_mcp_catalog(resources)
    logger.info("MCP catalog built: %d resources", len(resources))
    return resources


def refresh_mcp_catalog(config: dict) -> dict:
    """Refresh the MCP catalog — update descriptions and recompute embeddings.

    Returns {"resources_updated": int, "resources_added": int}
    """
    existing = load_mcp_catalog()
    existing_ids = {r["id"] for r in existing}

    stats = {"resources_updated": 0, "resources_added": 0}
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()

    for resource in MCP_RESOURCES:
        if resource["id"] in existing_ids:
            for ex in existing:
                if ex["id"] == resource["id"]:
                    ex["description"] = resource["description"]
                    ex["key_fields"] = resource["key_fields"]
                    ex["access_example"] = resource["access_example"]
                    ex["refreshed_at"] = now

                    embedding = embed_text(resource["description"], config)
                    if embedding:
                        _store_mcp_embedding(conn, resource["id"], resource["description"], embedding)
                        ex["embedding_generated"] = True

                    stats["resources_updated"] += 1
                    break
        else:
            entry = {**resource, "refreshed_at": now}
            embedding = embed_text(resource["description"], config)
            if embedding:
                _store_mcp_embedding(conn, resource["id"], resource["description"], embedding)
                entry["embedding_generated"] = True
            existing.append(entry)
            stats["resources_added"] += 1

    conn.commit()

    save_mcp_catalog(existing)
    logger.info("MCP catalog refreshed: %d updated, %d added",
                stats["resources_updated"], stats["resources_added"])
    return stats


def search_mcp_catalog(query: str, top_k: int = 5) -> list[dict]:
    """Semantic search against MCP catalog embeddings.

    Args:
        query: natural language description
        top_k: max results

    Returns:
        list of MCPResource dicts with similarity_score
    """
    from app.advisor.helpers import get_advisor_config
    config = get_advisor_config()

    embedding = embed_text(query, config)
    if not embedding:
        return _keyword_search(query, top_k)

    from app.advisor.detector import find_similar_mcp
    results = find_similar_mcp(embedding, top_k=top_k, threshold=0.30)

    if not results:
        return _keyword_search(query, top_k)

    catalog = load_mcp_catalog()
    catalog_by_id = {r["id"]: r for r in catalog}

    enriched = []
    for r in results:
        resource_info = catalog_by_id.get(r["resource_id"], {})
        enriched.append({
            **resource_info,
            "similarity_score": r["similarity_score"],
        })

    return enriched


def _keyword_search(query: str, top_k: int = 5) -> list[dict]:
    """Fallback keyword search when embeddings are unavailable."""
    catalog = load_mcp_catalog()
    query_lower = query.lower()

    scored = []
    for r in catalog:
        text = f"{r.get('name', '')} {r.get('description', '')} {r.get('type', '')}".lower()
        words = query_lower.split()
        score = sum(1 for w in words if w in text)
        if score > 0:
            scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:top_k]]


def _store_mcp_embedding(conn, resource_id: str, description: str,
                         embedding: list[float]) -> None:
    """Store or update MCP embedding in SQLite."""
    now = datetime.now(timezone.utc).isoformat()

    try:
        conn.execute(
            """INSERT OR REPLACE INTO mcp_embeddings
               (resource_id, description, embedding, updated_at)
               VALUES (?, ?, ?, ?)""",
            (resource_id, description, serialize_embedding(embedding), now),
        )

        row = conn.execute(
            "SELECT id FROM mcp_embeddings WHERE resource_id = ?",
            (resource_id,),
        ).fetchone()

        if row:
            upsert_vec_embedding(
                conn, "vec_mcp_embeddings", "description_embedding",
                row[0], embedding,
            )
    except Exception as e:
        logger.error("Error storing MCP embedding for %s: %s", resource_id, e)
