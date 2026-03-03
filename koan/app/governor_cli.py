"""AI Governor CLI — Direct skill execution without Telegram bridge.

Bypasses awake.py and the messaging bridge. Loads the SkillRegistry,
constructs a SkillContext, and calls execute_skill() directly.

Two handler return patterns are supported:
  1. Return string (governor.watcher, governor.advisor, etc.)
  2. Side-effect outbox (governor.status) — writes to instance/outbox.md
"""

import argparse
import difflib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from app.skills import SkillContext, build_registry, execute_skill
from app.utils import KOAN_ROOT, load_config


class CLIContext(SkillContext):
    """SkillContext subclass that also supports dict-style .get() access.

    Some handlers use ctx.args (attribute), others use ctx.get("args") (dict-style).
    This hybrid supports both patterns without modifying existing handlers.
    """

    def get(self, key: str, default=None):
        return getattr(self, key, default)

VERSION = "1.0.0"
INSTANCE_DIR = KOAN_ROOT / "instance"
OUTBOX_FILE = INSTANCE_DIR / "outbox.md"

# Exit codes per cli-interface.yaml contract
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_SKILL_NOT_FOUND = 2
EXIT_DOCKER_DOWN = 3
EXIT_CONFIG_MISSING = 4

# ANSI colors (disabled when piped or --json)
_USE_COLOR = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"

def _green(t: str) -> str: return _c("32", t)
def _yellow(t: str) -> str: return _c("33", t)
def _red(t: str) -> str: return _c("31", t)
def _bold(t: str) -> str: return _c("1", t)
def _dim(t: str) -> str: return _c("2", t)


# ── Registry ────────────────────────────────────────────────────────

_registry = None

def _get_registry():
    global _registry
    if _registry is None:
        extra_dirs = []
        instance_skills = INSTANCE_DIR / "skills"
        if instance_skills.is_dir():
            extra_dirs.append(instance_skills)
        _registry = build_registry(extra_dirs)
    return _registry


# ── Skill dispatch ──────────────────────────────────────────────────

# Maps CLI commands to skill handler directory names
# Format: command -> (handler_dir, prepend_command_to_args)
SKILL_MAP = {
    "status":   ("governor.status", False),
    "watcher":  ("governor.watcher", False),
    "advisor":  ("governor.advisor", False),
    "autonomy": ("governor.autonomy", False),
    "rollout":  ("governor.rollout", False),
    "offboard": ("governor.offboard", False),
    "budget":   ("governor/budget", True),
    "keys":     ("governor/keys", True),
    "vault":    ("governor.vault", False),
    "env":      ("governor.env", False),
    "scan":     ("governor.scan", False),
}


def _find_skill(command: str):
    """Find a skill by command name.

    Prefers direct handler.py path (most reliable for governor skills),
    then falls back to registry lookup.
    """
    entry = SKILL_MAP.get(command)
    if entry is None:
        return None, None

    handler_dir, prepend = entry

    # Strategy 1: direct handler.py path (reliable — ignores SKILL.md inconsistencies)
    handler_path = INSTANCE_DIR / "skills" / handler_dir / "handler.py"
    if handler_path.exists():
        from app.skills import Skill
        skill = Skill(
            name=command,
            scope="governor",
            handler_path=handler_path,
            skill_dir=handler_path.parent,
        )
        return skill, prepend

    # Strategy 2: registry lookup (for skills with proper SKILL.md)
    registry = _get_registry()
    qualified_name = handler_dir.replace("/", ".")
    skill = registry.get_by_qualified_name(qualified_name)
    if skill and skill.has_handler():
        return skill, prepend

    return None, None


def dispatch_skill(command: str, action: str, extra_args: str,
                   flags: argparse.Namespace) -> tuple[int, str]:
    """Dispatch a CLI command to the appropriate skill handler.

    Returns (exit_code, result_text).
    """
    if command not in SKILL_MAP:
        return EXIT_SKILL_NOT_FOUND, _suggest_command(command)

    skill, prepend = _find_skill(command)
    if skill is None:
        return EXIT_SKILL_NOT_FOUND, f"Skill pour '{command}' non trouvé."

    # Build args string
    if prepend:
        args_str = f"{command} {action} {extra_args}".strip()
    else:
        args_str = f"{action} {extra_args}".strip()

    # Capture outbox state before execution (for outbox-pattern handlers)
    outbox_before = _read_outbox()

    ctx = CLIContext(
        koan_root=KOAN_ROOT,
        instance_dir=INSTANCE_DIR,
        command_name=command,
        args=args_str,
    )

    start = time.monotonic()
    result = execute_skill(skill, ctx)
    elapsed = time.monotonic() - start

    # Handle outbox pattern: if result is None, check outbox for new content
    if result is None:
        outbox_after = _read_outbox()
        if len(outbox_after) > len(outbox_before):
            result = outbox_after[len(outbox_before):].strip()
            # Clean up appended content
            _write_outbox(outbox_before)

    if result is None:
        result = f"Commande exécutée (pas de sortie). [{elapsed:.1f}s]"

    if flags.verbose:
        result += f"\n{_dim(f'[{elapsed:.1f}s | skill={qualified} | args={args_str!r}]')}"

    return EXIT_OK, result


def _read_outbox() -> str:
    try:
        return OUTBOX_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _write_outbox(content: str):
    OUTBOX_FILE.write_text(content, encoding="utf-8")


def _suggest_command(command: str) -> str:
    all_commands = list(SKILL_MAP.keys()) + ["simulate", "tunnel"]
    matches = difflib.get_close_matches(command, all_commands, n=3, cutoff=0.5)
    msg = f"Commande inconnue : '{command}'"
    if matches:
        suggestions = ", ".join(matches)
        msg += f"\nCommandes similaires : {suggestions}"
    msg += f"\nTapez 'governor --help' pour la liste complète."
    return msg


# ── Google Chat notify ──────────────────────────────────────────────

def send_to_gchat(title: str, body: str, thread_key: Optional[str] = None) -> bool:
    """Send a message to Google Chat via webhook. Returns True on success."""
    import requests

    webhook_url = _get_gchat_url()
    if not webhook_url:
        return False

    card = {
        "cardsV2": [{
            "cardId": f"governor-{thread_key or 'default'}",
            "card": {
                "header": {
                    "title": f"AI Governor — {title}",
                    "imageUrl": "https://fonts.gstatic.com/s/i/short-term/release/googlesymbols/security/default/24px.svg",
                    "imageType": "CIRCLE",
                },
                "sections": [{
                    "widgets": [{
                        "textParagraph": {"text": body[:3000]}
                    }]
                }]
            }
        }]
    }

    params = {}
    if thread_key:
        params["threadKey"] = thread_key
        params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"

    try:
        url = webhook_url
        if params:
            url += "&" if "?" in url else "?"
            url += "&".join(f"{k}={v}" for k, v in params.items())
        resp = requests.post(url, json=card, timeout=10)
        if resp.status_code == 429:
            time.sleep(2)
            resp = requests.post(url, json=card, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def _get_gchat_url() -> Optional[str]:
    url = os.environ.get("GCHAT_WEBHOOK_URL")
    if url:
        return url
    config = load_config()
    env_key = config.get("go_live", {}).get("gchat_webhook_url_env", "GCHAT_WEBHOOK_URL")
    return os.environ.get(env_key)


# ── Docker check ────────────────────────────────────────────────────

def _check_docker() -> Optional[str]:
    """Check if Docker is running. Returns error message or None."""
    try:
        subprocess.run(
            ["docker", "info"],
            capture_output=True, timeout=5,
        )
        return None
    except FileNotFoundError:
        return "Docker non installé. Installez Docker Desktop : https://docker.com"
    except subprocess.TimeoutExpired:
        return "Docker ne répond pas. Ouvrez Docker Desktop et relancez."
    except Exception:
        return "Docker non démarré. Ouvrez Docker Desktop, puis relancez."


# ── Argparse ────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="governor",
        description="AI Governor CLI — Exécution directe des skills sans Telegram",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commandes disponibles:
  status              Health check unifié de tous les modules
  watcher             Surveillance des repos GitHub et GitLab
  advisor             Détection de duplications et recommandations
  autonomy            Gestion des niveaux d'autonomie
  rollout             Gestion du déploiement progressif
  budget              Gestion des budgets API
  vault               Gestion des credentials
  env                 Injection de variables d'environnement
  scan                Scan des credentials dans le code
  simulate            Simuler des événements pour tester le pipeline
  tunnel              Gestion du tunnel pour les webhooks GitHub

Exemples:
  governor status
  governor watcher scan
  governor advisor analyze https://github.com/org/repo/commit/abc123
  governor advisor feedback DET-042 relevant --notes "Bonne détection"
  governor simulate commit --author dany-yourart --repo emailfactory --message "test"
  governor --json status
""",
    )
    parser.add_argument("--version", action="version", version=f"governor {VERSION}")
    parser.add_argument("--json", dest="output_json", action="store_true",
                        help="Sortie en JSON brut")
    parser.add_argument("--notify", action="store_true",
                        help="Envoyer aussi le résultat sur Google Chat")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="Exécuter sans envoyer de notifications")
    parser.add_argument("--verbose", action="store_true",
                        help="Afficher les logs de debug")
    parser.add_argument("command", nargs="?", help="Commande governor (status, watcher, advisor, ...)")
    parser.add_argument("rest", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)

    return parser


# ── Main ────────────────────────────────────────────────────────────

def main() -> int:
    global _USE_COLOR

    parser = _build_parser()
    args = parser.parse_args()

    if args.output_json:
        _USE_COLOR = False

    if not args.command:
        parser.print_help()
        return EXIT_OK

    command = args.command.lower()
    rest = args.rest or []

    # Extract action (first positional after command) and remaining args
    action = rest[0] if rest else ""
    extra_args = " ".join(rest[1:]) if len(rest) > 1 else ""

    # Handle simulate and tunnel separately (not standard skills)
    if command == "simulate":
        from app.simulator import handle_simulate
        return handle_simulate(action, extra_args, args)

    if command == "tunnel":
        return _handle_tunnel(action, args)

    # Standard skill dispatch
    exit_code, result = dispatch_skill(command, action, extra_args, args)

    if exit_code == EXIT_SKILL_NOT_FOUND:
        print(_red(result), file=sys.stderr)
        return exit_code

    # Output formatting
    if args.output_json:
        output = json.dumps({
            "command": command,
            "action": action,
            "result": result,
            "exit_code": exit_code,
        }, ensure_ascii=False, indent=2)
        print(output)
    else:
        if args.dry_run:
            print(_yellow("[DRY RUN] ") + result)
        else:
            print(result)

    # --notify: also send to Google Chat
    if args.notify and not args.dry_run:
        title = f"{command} {action}".strip()
        ok = send_to_gchat(title, result, thread_key=command)
        if ok:
            print(_dim("→ Notification envoyée sur Google Chat"))
        else:
            print(_yellow("→ Échec envoi Google Chat (vérifiez GCHAT_WEBHOOK_URL)"))

    return exit_code


# ── Tunnel commands (US5) ───────────────────────────────────────────

def _handle_tunnel(action: str, flags: argparse.Namespace) -> int:
    if action == "status":
        return _tunnel_status()
    elif action == "start":
        return _tunnel_start()
    elif action == "stop":
        return _tunnel_stop()
    else:
        print("Usage: governor tunnel [status|start|stop]")
        return EXIT_ERROR


def _tunnel_status() -> int:
    try:
        result = subprocess.run(
            ["pgrep", "-f", "cloudflared.*tunnel"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            pids = result.stdout.strip().split("\n")
            print(_green("Tunnel actif") + f" (PID: {', '.join(pids)})")
        else:
            print(_yellow("Tunnel inactif") + " — lancez 'governor tunnel start'")
    except Exception as e:
        print(_red(f"Erreur vérification tunnel : {e}"))
    return EXIT_OK


def _tunnel_start() -> int:
    try:
        subprocess.Popen(
            ["cloudflared", "tunnel", "--url", "http://localhost:5001"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(_green("Tunnel cloudflared démarré") + " → http://localhost:5001")
        print(_dim("L'URL publique apparaîtra dans les logs cloudflared."))
        return EXIT_OK
    except FileNotFoundError:
        print(_red("cloudflared non installé.") + " Installez avec : brew install cloudflared")
        return EXIT_ERROR


def _tunnel_stop() -> int:
    try:
        subprocess.run(["pkill", "-f", "cloudflared.*tunnel"], check=True)
        print(_green("Tunnel arrêté."))
        return EXIT_OK
    except subprocess.CalledProcessError:
        print(_yellow("Aucun tunnel actif à arrêter."))
        return EXIT_OK
