"""Notifier — Google Chat notifications specific to Advisor.

Reuses the watcher notifier infrastructure (Cards v2, threading, queue).
Tone: informative, never accusatory.
"""

import logging
from datetime import datetime, timezone

from app.advisor.helpers import (
    DET_DUPLICATION_MCP,
    CONFIDENCE_HIGH,
)

logger = logging.getLogger("advisor.notifier")


def notify_duplication(detection: dict, config: dict) -> None:
    """Send a Google Chat notification for a duplication detection.

    Tone: "Il existe déjà..." — informative, helpful.
    """
    source_author_name = detection.get("source_author_name") or detection.get("source_author", "")
    source_repo = detection.get("source_repo", "").split("/")[-1]
    target_name = detection.get("target_name", "?")
    target_desc = detection.get("target_description", "")
    confidence = detection.get("confidence", "medium")
    det_type = detection.get("type", "")
    det_id = detection.get("id", "")

    if det_type == DET_DUPLICATION_MCP:
        title = f"Recommandation — {source_repo}"
        body = (
            f"Salut {source_author_name},\n\n"
            f"Les données que tu accèdes dans ton projet {source_repo} "
            f"sont déjà disponibles via le MCP ArtMajeur "
            f"(ressource : {target_name}).\n\n"
            f"{target_desc}\n\n"
            f"Tu peux utiliser l'outil MCP directement — c'est plus simple et déjà maintenu.\n\n"
            f"Confiance : {'élevée' if confidence == CONFIDENCE_HIGH else 'moyenne'}"
        )
    else:
        title = f"Recommandation — {source_repo}"
        body = (
            f"Salut {source_author_name},\n\n"
            f"Il existe déjà un module similaire dans le code de production ArtMajeur "
            f"(GitLab, module {target_name}).\n\n"
            f"{target_desc}\n\n"
            f"Tu peux contacter le mainteneur de ce module pour voir "
            f"si tu peux réutiliser ce qui existe.\n\n"
            f"Confiance : {'élevée' if confidence == CONFIDENCE_HIGH else 'moyenne'}"
        )

    if detection.get("previously_false_positive"):
        body += "\n\n⚠️ Ce pattern a déjà été signalé comme faux positif auparavant."

    card = _build_advisor_card(title, body, det_id)
    thread_key = f"advisor-{source_repo}-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    author = detection.get("source_author", "")

    _send_notification(body, card, thread_key, config, author_login=author)


def notify_convergence(detection: dict, config: dict) -> None:
    """Send Google Chat notifications to both citizens for a convergence.

    Each citizen receives a personalized notification mentioning the other.
    """
    source_name = detection.get("source_author_name") or detection.get("source_author", "")
    source_repo = detection.get("source_repo", "").split("/")[-1]
    target_name = detection.get("target_name", "?")
    target_desc = detection.get("target_description", "")
    det_id = detection.get("id", "")

    target_owner = ""
    target_owner_name = ""
    try:
        from app.advisor.helpers import load_repo_index
        index = load_repo_index()
        target_repo_info = next(
            (r for r in index if r.get("id") == detection.get("target_id")),
            {},
        )
        target_owner = target_repo_info.get("owner", "")
        target_owner_name = target_repo_info.get("owner_name", "")
    except Exception:
        pass

    title = "Projet similaire détecté"
    body = (
        f"Salut {source_name},\n\n"
        f"Ton projet {source_repo} a des similitudes avec le projet {target_name}"
    )
    if target_owner_name:
        body += f" de {target_owner_name} ({target_owner})"
    body += (
        f".\n\n{target_desc}\n\n"
        f"N'hésitez pas à en discuter ensemble !"
    )

    card = _build_advisor_card(title, body, det_id)
    thread_key = f"advisor-convergence-{det_id}"
    author = detection.get("source_author", "")

    _send_notification(body, card, thread_key, config, author_login=author)


def notify_governors_report(report: str, config: dict) -> None:
    """Send a report summary to governors via Google Chat."""
    title = "Rapport Advisor"
    card = _build_advisor_card(title, report[:1000], "report")
    thread_key = f"advisor-report-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"

    _send_notification(report[:1000], card, thread_key, config)


def _build_advisor_card(title: str, body: str, det_id: str) -> list:
    """Build a Google Chat Card v2 for advisor notifications."""
    widgets = [
        {"textParagraph": {"text": body}},
    ]

    if det_id and det_id != "report":
        # CLI feedback instructions (works with webhooks, no Chat App needed)
        feedback_text = (
            f"<b>Feedback :</b>\n"
            f"<code>governor advisor feedback {det_id} relevant</code>\n"
            f"<code>governor advisor feedback {det_id} false-positive</code>\n"
            f"<code>governor advisor feedback {det_id} ignore</code>"
        )
        widgets.append({"textParagraph": {"text": feedback_text}})

    return [{
        "cardId": f"advisor-{det_id}",
        "card": {
            "header": {
                "title": title,
                "subtitle": "AI Governor — Advisor",
            },
            "sections": [{"widgets": widgets}],
        },
    }]


def _send_notification(text: str, cards: list, thread_key: str,
                       config: dict, author_login: str = "") -> bool:
    """Send notification using watcher's notification infrastructure.

    Checks the notification router before sending.
    """
    # Check notification router and autonomy level
    if author_login:
        try:
            from app.notification_router import get_router
            router = get_router()
            if not router.should_notify("advisor", author_login):
                logger.debug("Advisor notification skipped for %s (not in active rollout group)", author_login)
                return False

            behavior = router.check_autonomy("advisor")
            if behavior == "log_only":
                logger.info("Advisor in watch mode — logging only, not notifying citizen %s", author_login)
                return False
            elif behavior == "ask_governor":
                logger.info("Advisor in supervise mode — notifying governors for validation")
                # In supervise mode, the notification still goes out but to governors
                # The governor will decide whether to forward to the citizen
        except ImportError:
            pass

    try:
        from app.watcher.notifier import send_notification
        return send_notification(text=text, cards=cards, thread_key=thread_key)
    except ImportError:
        logger.warning("Watcher notifier not available, writing to outbox")
        try:
            from app.utils import KOAN_ROOT, append_to_outbox
            outbox = KOAN_ROOT / "instance" / "outbox.md"
            append_to_outbox(outbox, f"\n[Advisor] {text[:500]}\n")
        except Exception:
            pass
        return False
    except Exception as e:
        logger.error("Notification send failed: %s", e)
        return False
