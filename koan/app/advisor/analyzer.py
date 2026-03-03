"""Analyzer — 5-pass commit analysis pipeline for duplication detection.

Pipeline:
1. Filter citizen only (classify_author)
2. Scan for data patterns (heuristics)
3. Summarize diff with LLM (Haiku)
4. Embed + KNN search (sqlite-vec)
5. LLM judge if score >= threshold (Sonnet)
"""

import json
import logging
from datetime import datetime, timezone
from hashlib import md5

from app.advisor.helpers import (
    get_advisor_config,
    get_db,
    summarize_with_llm,
    embed_text,
    call_llm_judge,
    serialize_embedding,
    upsert_vec_embedding,
    load_detections,
    save_detections,
    load_repo_index,
    is_duplicate_detection,
    load_detection_history,
    update_detection_history,
    DET_DUPLICATION_GITLAB,
    DET_DUPLICATION_MCP,
    DET_CONVERGENCE_CITIZEN,
    STATUS_PENDING,
    STATUS_NOTIFIED,
    STATUS_FALSE_POSITIVE,
    PLATFORM_GITHUB,
    PLATFORM_GITLAB,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_LOW,
    CONFIDENCE_NONE,
)
from app.advisor.heuristics import scan_for_data_patterns
from app.advisor.detector import find_similar_repos, find_similar_mcp

logger = logging.getLogger("advisor.analyzer")

DIFF_SUMMARY_PROMPT = """Résume en 3-5 phrases en français ce que fait ce commit.
Décris la fonctionnalité ajoutée/modifiée d'un point de vue utilisateur, pas technique.

Auteur : {author}
Message de commit : {message}
Diff :
{content}"""

JUDGE_PROMPT = """Tu es un expert en détection de code dupliqué fonctionnellement.

Compare ces deux modules et détermine s'ils font la même chose d'un point de vue fonctionnel
(même si le code est complètement différent).

Module citizen (nouveau) :
{citizen_summary}

Module existant ({target_name}) :
{target_summary}

Réponds en JSON strict :
{{"is_duplicate": true/false, "confidence": 0.0-1.0, "explanation": "..."}}

Sois strict : seule une vraie duplication fonctionnelle compte (même objectif business).
Des modules dans le même domaine mais avec des buts différents ne sont PAS des duplications."""

MCP_JUDGE_PROMPT = """Tu es un expert en détection de duplications d'accès aux données.

Un citizen crée un accès direct à des données qui sont peut-être déjà accessibles
via un outil MCP existant.

Code du citizen :
{citizen_summary}

Ressource MCP existante ({resource_name}) :
{resource_description}
Outil MCP : {mcp_tool}

Réponds en JSON strict :
{{"is_duplicate": true/false, "confidence": 0.0-1.0, "explanation": "..."}}

Sois strict : le citizen doit accéder aux MÊMES données que la ressource MCP.
Un accès au même type de base de données mais à des données différentes n'est PAS une duplication."""


def analyze_commit(event: dict, config: dict) -> list[dict]:
    """Analyze a citizen commit for duplications (5-pass pipeline).

    Args:
        event: WatcherEvent dict from journal
        config: advisor config section

    Returns:
        list of Detection dicts (can be empty)
    """
    # Pass 1: filter citizen only
    author_type = event.get("author_type", "unknown")
    if author_type != "citizen":
        return []

    author = event.get("author", "")
    author_name = event.get("author_name", "")
    summary_text = event.get("summary", "")
    diff_content = event.get("diff", summary_text)

    # Pass 2: heuristic scan
    heuristic_flags = scan_for_data_patterns(diff_content)
    heuristic_score = min(len(heuristic_flags) * 0.3, 1.0)

    # Pass 3: LLM summary
    commit_summary = summarize_with_llm(
        DIFF_SUMMARY_PROMPT.format(
            author=author_name or author,
            message=event.get("title", summary_text[:200]),
            content=diff_content[:5000],
        ),
        config,
    )
    if not commit_summary:
        commit_summary = summary_text

    # Pass 4: embedding + KNN
    embedding = embed_text(commit_summary, config)

    _store_commit_analysis(event, commit_summary, embedding, heuristic_flags)

    detections = []
    threshold = config.get("similarity_threshold", 0.60)

    # Load detection history once for dedup checks
    history = load_detection_history()

    if embedding:
        # Search GitLab production repos
        gitlab_matches = find_similar_repos(
            embedding, top_k=3, threshold=threshold,
            platform_filter=PLATFORM_GITLAB,
        )
        for match in gitlab_matches:
            prompt = JUDGE_PROMPT.format(
                citizen_summary=commit_summary[:2000],
                target_name=match.get("repo_id", ""),
                target_summary=match.get("summary", "")[:2000],
            )
            det = _evaluate_match(
                event, commit_summary, heuristic_score,
                match, DET_DUPLICATION_GITLAB, prompt, config, history,
            )
            if det:
                detections.append(det)

        # Search MCP catalog if heuristic flags detected
        if heuristic_flags:
            mcp_matches = find_similar_mcp(embedding, top_k=3, threshold=threshold)
            for match in mcp_matches:
                prompt = MCP_JUDGE_PROMPT.format(
                    citizen_summary=commit_summary[:2000],
                    resource_name=match.get("name", ""),
                    resource_description=match.get("description", "")[:1000],
                    mcp_tool=match.get("mcp_tool", ""),
                )
                det = _evaluate_match(
                    event, commit_summary, heuristic_score,
                    match, DET_DUPLICATION_MCP, prompt, config, history,
                )
                if det:
                    detections.append(det)

    if detections:
        save_detections(detections)

    return detections


def analyze_batch(days: int, config: dict) -> list[dict]:
    """Batch analysis over recent citizen commits.

    Combines GitLab duplication (US2), MCP duplication (US3),
    and citizen convergence (US4) detection.
    """
    events = _read_citizen_events(days)
    all_detections = []

    for event in events:
        try:
            dets = analyze_commit(event, config)
            all_detections.extend(dets)
        except Exception as e:
            logger.error("Error analyzing event %s: %s", event.get("id", "?"), e)

    try:
        convergences = _detect_citizen_convergences(config)
        all_detections.extend(convergences)
    except Exception as e:
        logger.error("Error in convergence detection: %s", e)

    return all_detections


def compute_confidence(embedding_similarity: float, llm_judge_score: float,
                       heuristic_score: float) -> tuple[float, str]:
    """Compute composite confidence score.

    Formula: 0.4 * embedding + 0.4 * judge + 0.2 * heuristic

    Returns:
        (score, label) where label = high/medium/low/none
    """
    score = (0.4 * embedding_similarity +
             0.4 * llm_judge_score +
             0.2 * heuristic_score)
    score = round(min(max(score, 0.0), 1.0), 3)

    if score >= 0.80:
        label = CONFIDENCE_HIGH
    elif score >= 0.60:
        label = CONFIDENCE_MEDIUM
    elif score >= 0.40:
        label = CONFIDENCE_LOW
    else:
        label = CONFIDENCE_NONE

    return score, label


def generate_report(days: int, config: dict) -> str:
    """Generate a structured detection report for governors."""
    dets = load_detections(days)

    if not dets:
        return f"Rapport Advisor — {days} derniers jours\n\nAucune détection."

    by_type = {}
    for d in dets:
        t = d.get("type", "unknown")
        by_type.setdefault(t, []).append(d)

    total = len(dets)
    fp_count = sum(1 for d in dets if d.get("status") == STATUS_FALSE_POSITIVE)
    ack_count = sum(1 for d in dets if d.get("status") == STATUS_ACKNOWLEDGED)
    relevant_count = sum(1 for d in dets if d.get("status") == "relevant")
    ignore_count = sum(1 for d in dets if d.get("status") == "ignore")
    feedback_total = fp_count + ack_count + relevant_count + ignore_count
    notified_count = sum(
        1 for d in dets
        if d.get("status") in (STATUS_NOTIFIED, STATUS_FALSE_POSITIVE, STATUS_ACKNOWLEDGED, "relevant", "ignore")
    )

    lines = [f"Rapport Advisor — {days} derniers jours"]

    type_labels = {
        DET_DUPLICATION_GITLAB: "Duplications avec la production GitLab",
        DET_DUPLICATION_MCP: "Duplications avec le MCP",
        DET_CONVERGENCE_CITIZEN: "Convergences entre citizens",
    }

    for det_type, label in type_labels.items():
        type_dets = by_type.get(det_type, [])
        if type_dets:
            lines.append(f"\n## {label}")
            for i, d in enumerate(type_dets, 1):
                conf = d.get("confidence", "?").upper()
                source = d.get("source_repo", "?")
                target = d.get("target_name", "?")
                status = d.get("status", STATUS_PENDING)
                created = d.get("created_at", "")[:10]
                lines.append(f"{i}. {source} → {target} ({conf}, {created})")
                lines.append(f"   Status : {status}")
                if d.get("explanation"):
                    lines.append(f"   {d['explanation'][:100]}")

    lines.append("\n## Statistiques")
    lines.append(f"• Total détections : {total}")
    lines.append(f"• Notifications envoyées : {notified_count}")

    # Feedback summary with pertinence rate
    if feedback_total > 0:
        pertinence_rate = round((relevant_count + ack_count) / feedback_total * 100)
        lines.append(f"\n## Feedback ({feedback_total} verdicts)")
        lines.append(f"• Pertinents : {relevant_count}")
        lines.append(f"• Acknowledged : {ack_count}")
        lines.append(f"• Faux positifs : {fp_count}")
        lines.append(f"• Ignorés : {ignore_count}")
        lines.append(f"• Taux de pertinence : {pertinence_rate}%")
        if pertinence_rate < 70:
            lines.append("  ⚠️ Taux de pertinence faible — envisagez d'augmenter similarity_threshold")
    elif fp_count:
        fp_rate = round(fp_count / total * 100) if total else 0
        lines.append(f"• Faux positifs : {fp_count} ({fp_rate}%)")

    return "\n".join(lines)


# ── Internal helpers ─────────────────────────────────────────────────

def _evaluate_match(event: dict, commit_summary: str,
                    heuristic_score: float, match: dict,
                    det_type: str, judge_prompt: str,
                    config: dict, history: dict) -> dict | None:
    """Evaluate a KNN match with LLM judge and create Detection if warranted.

    Unified handler for both GitLab and MCP duplication detection.
    """
    platform = event.get("platform", PLATFORM_GITHUB)
    source_repo = f"{platform}/{event.get('repo', '')}"
    target_id = match.get("repo_id") or match.get("resource_id", "")

    # Check dedup and false positive history
    if is_duplicate_detection(source_repo, target_id, pairs=history):
        return None

    pair_key = f"{source_repo}:{target_id}"
    entry = history.get(pair_key, {})
    fp_count = entry.get("false_positive_count", 0)
    if fp_count >= 2:
        return None

    previously_fp = fp_count == 1

    similarity = match.get("similarity_score", 0.0)

    # Pass 5: LLM judge
    judge_score, explanation = call_llm_judge(judge_prompt, config)

    score, label = compute_confidence(similarity, judge_score, heuristic_score)

    notification_threshold = config.get("notification_threshold", 0.60)
    if score < notification_threshold:
        return None

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    det_id = "det-{}-{}".format(
        now.strftime("%Y%m%d"),
        md5("{}{}{}".format(source_repo, target_id, now_iso).encode()).hexdigest()[:8],
    )

    # Derive target name
    if "/" in target_id:
        target_name = target_id.split("/")[-1]
    else:
        target_name = match.get("name", target_id)

    detection = {
        "id": det_id,
        "type": det_type,
        "source_repo": source_repo,
        "source_commit": event.get("id", ""),
        "source_author": event.get("author", ""),
        "source_author_name": event.get("author_name", ""),
        "target_id": target_id,
        "target_name": target_name,
        "target_description": (match.get("summary") or match.get("description", ""))[:200],
        "confidence": label,
        "confidence_score": score,
        "explanation": explanation,
        "previously_false_positive": previously_fp,
        "status": STATUS_PENDING,
        "notified_at": None,
        "feedback_at": None,
        "feedback_by": None,
        "created_at": now_iso,
    }

    _notify_detection(detection, config)
    return detection


def _store_commit_analysis(event: dict, summary: str,
                           embedding: list[float],
                           heuristic_flags: list[str]) -> None:
    """Store commit analysis result in SQLite."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    platform = event.get("platform", PLATFORM_GITHUB)

    try:
        conn.execute(
            """INSERT OR IGNORE INTO commit_analyses
               (event_id, repo_id, author, author_name, summary, embedding,
                heuristic_flags, analyzed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.get("id", ""),
                f"{platform}/{event.get('repo', '')}",
                event.get("author", ""),
                event.get("author_name", ""),
                summary,
                serialize_embedding(embedding) if embedding else None,
                json.dumps(heuristic_flags),
                now,
            ),
        )

        if embedding:
            row = conn.execute(
                "SELECT id FROM commit_analyses WHERE event_id = ?",
                (event.get("id", ""),),
            ).fetchone()
            if row:
                upsert_vec_embedding(
                    conn, "vec_commit_analyses", "summary_embedding",
                    row[0], embedding,
                )

        conn.commit()
    except Exception as e:
        logger.error("Error storing commit analysis: %s", e)


def _notify_detection(detection: dict, config: dict) -> None:
    """Send notification for a detection."""
    try:
        from app.advisor.notifier import notify_duplication, notify_convergence

        det_type = detection.get("type", "")
        if det_type.startswith("duplication"):
            notify_duplication(detection, config)
        elif det_type == DET_CONVERGENCE_CITIZEN:
            notify_convergence(detection, config)

        detection["status"] = STATUS_NOTIFIED
        detection["notified_at"] = datetime.now(timezone.utc).isoformat()

        update_detection_history(
            detection.get("source_repo", ""),
            detection.get("target_id", ""),
        )
    except ImportError:
        logger.warning("Notifier not available, detection not sent")
    except Exception as e:
        logger.error("Notification failed for %s: %s", detection.get("id"), e)


def _detect_citizen_convergences(config: dict) -> list[dict]:
    """Detect similar citizen repos (convergence detection)."""
    from app.advisor.detector import find_similar_citizens

    index = load_repo_index()
    citizen_repos = [r for r in index if r.get("owner_type") == "citizen"]
    detections = []
    checked_pairs = set()
    history = load_detection_history()

    for repo in citizen_repos:
        repo_id = repo.get("id", "")
        summary = repo.get("summary", "")
        if not summary:
            continue

        embedding = embed_text(summary, config)
        if not embedding:
            continue

        similar = find_similar_citizens(repo_id, embedding, top_k=3)

        for match in similar:
            pair = tuple(sorted([repo_id, match["repo_id"]]))
            if pair in checked_pairs:
                continue
            checked_pairs.add(pair)

            if match["similarity_score"] < config.get("similarity_threshold", 0.60):
                continue

            if is_duplicate_detection(repo_id, match["repo_id"], pairs=history):
                continue

            now = datetime.now(timezone.utc)
            now_iso = now.isoformat()
            det_id = "det-{}-{}".format(
                now.strftime("%Y%m%d"),
                md5("{}{}{}".format(repo_id, match["repo_id"], now_iso).encode()).hexdigest()[:8],
            )

            conv_score, conv_label = compute_confidence(
                match["similarity_score"], 0.0, 0.0,
            )

            detection = {
                "id": det_id,
                "type": DET_CONVERGENCE_CITIZEN,
                "source_repo": repo_id,
                "source_commit": "",
                "source_author": repo.get("owner", ""),
                "source_author_name": repo.get("owner_name", ""),
                "target_id": match["repo_id"],
                "target_name": match["repo_id"].split("/")[-1] if "/" in match["repo_id"] else match["repo_id"],
                "target_description": match.get("summary", "")[:200],
                "confidence": conv_label,
                "confidence_score": conv_score,
                "explanation": "Projets similaires détectés (similarité: {:.0%})".format(
                    match["similarity_score"]
                ),
                "status": STATUS_PENDING,
                "notified_at": None,
                "feedback_at": None,
                "feedback_by": None,
                "created_at": now_iso,
            }

            _notify_detection(detection, config)
            detections.append(detection)

    if detections:
        save_detections(detections)

    return detections


def _read_citizen_events(days: int) -> list[dict]:
    """Read citizen events from watcher journal."""
    try:
        from app.watcher.journal import read_events
        from app.watcher.helpers import INSTANCE_DIR
        return read_events(
            INSTANCE_DIR, days=days,
            author_type="citizen",
            limit=500,
        )
    except ImportError:
        logger.warning("Watcher journal not available")
        return []
