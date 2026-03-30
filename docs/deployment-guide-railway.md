# Deploying Koan on Railway — Without Forking

Guide pour déployer Koan sur Railway avec une config partagée en équipe, sans fork du repo upstream.

---

## Architecture

```
GitHub:
  koan/koan                 ← upstream (read-only, tu pin une version)
  ton-org/koan-config       ← ton repo de config partagé avec l'équipe

Railway:
  Service "koan"
    /app                    ← code Koan (depuis Dockerfile, rebuilt à chaque deploy)
    /app/instance            ← volume persistant (état runtime de l'agent)
```

**Principe clé** : le code Koan et ta config sont dans le container (éphémère).
L'état runtime de l'agent vit sur un volume persistant (durable).

---

## Catégories de fichiers

| Type | Fichiers | Qui les gère | Au redéploiement |
|------|----------|--------------|------------------|
| **Config** | `config.yaml`, `soul.md`, `projects.yaml`, `memory/global/*` | Toi (dans git) | Toujours écrasés depuis le repo |
| **État runtime** | `missions.md`, `outbox.md`, `journal/`, `conversation-history.jsonl` | L'agent | Jamais touchés |
| **Mémoire projet** | `memory/projects/*/learnings.md`, `memory/projects/*/context.md` | L'agent | Jamais touchés |
| **Secrets** | Tokens API, credentials | Dashboard Railway | Env vars, jamais dans git |

---

## Structure du repo `koan-config`

```
koan-config/
├── Dockerfile
├── bootstrap.sh
│
├── config.yaml                  # Config instance → écrasé à chaque deploy
├── soul.md                      # Personnalité agent → écrasé à chaque deploy
├── projects.yaml                # Projets suivis → écrasé à chaque deploy
├── memory/
│   └── global/
│       ├── genesis.md           # → écrasé à chaque deploy
│       ├── strategy.md          # → écrasé à chaque deploy
│       └── human-preferences.md # → écrasé à chaque deploy
│
├── templates/                   # Utilisés seulement au PREMIER lancement
│   ├── missions.md
│   ├── outbox.md
│   └── memory/
│       └── projects/
│           └── _template/
│               ├── context.md
│               ├── priorities.md
│               └── learnings.md
│
├── .env.example                 # Template des secrets (sans valeurs)
└── README.md
```

---

## Dockerfile

```dockerfile
FROM python:3.12-slim

# Dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl supervisor gnupg \
    && rm -rf /var/lib/apt/lists/*

# Node.js (pour Claude CLI)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs

# Claude CLI + GitHub CLI
RUN npm install -g @anthropic-ai/claude-code \
    && (curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg) \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y gh

# Cloner Koan upstream à une version précise
ARG KOAN_VERSION=main
RUN git clone --depth 1 --branch ${KOAN_VERSION} https://github.com/koan/koan.git /app

# Installer les dépendances Python
RUN pip install --no-cache-dir -r /app/koan/requirements.txt

# Copier la config de l'équipe
COPY . /config

# Script de bootstrap
COPY bootstrap.sh /bootstrap.sh
RUN chmod +x /bootstrap.sh

WORKDIR /app
ENV KOAN_ROOT=/app
ENV PYTHONPATH=/app/koan

CMD ["/bootstrap.sh"]
```

> **Mise à jour Koan** : change `KOAN_VERSION` (tag, branche ou commit SHA),
> redéploie. Le volume `instance/` n'est pas touché.

---

## bootstrap.sh

```bash
#!/bin/bash
set -e

INSTANCE="/app/instance"
CONFIG="/config"

mkdir -p "$INSTANCE/journal" "$INSTANCE/memory/global" "$INSTANCE/memory/projects"

# ============================================================
# CONFIG : toujours synchronisée depuis le repo
# Ces fichiers reflètent ce que l'équipe a décidé.
# ============================================================
cp "$CONFIG/config.yaml"    "$INSTANCE/config.yaml"
cp "$CONFIG/soul.md"        "$INSTANCE/soul.md"
cp "$CONFIG/projects.yaml"  "$INSTANCE/projects.yaml"

# Mémoire globale (rédigée par l'équipe, pas par l'agent)
if [ -d "$CONFIG/memory/global" ]; then
    cp -r "$CONFIG/memory/global/"* "$INSTANCE/memory/global/" 2>/dev/null || true
fi

# ============================================================
# ÉTAT RUNTIME : créé seulement au premier lancement
# Ces fichiers appartiennent à l'agent, jamais écrasés.
# ============================================================
[ -f "$INSTANCE/missions.md" ]                || cp "$CONFIG/templates/missions.md"   "$INSTANCE/missions.md"
[ -f "$INSTANCE/outbox.md" ]                  || cp "$CONFIG/templates/outbox.md"     "$INSTANCE/outbox.md"    2>/dev/null || touch "$INSTANCE/outbox.md"
[ -f "$INSTANCE/conversation-history.jsonl" ] || touch "$INSTANCE/conversation-history.jsonl"
[ -f "$INSTANCE/usage.md" ]                   || touch "$INSTANCE/usage.md"

# Templates mémoire projet (copiés par Koan quand il découvre un nouveau projet)
if [ ! -d "$INSTANCE/memory/projects/_template" ] && [ -d "$CONFIG/templates/memory/projects/_template" ]; then
    cp -r "$CONFIG/templates/memory/projects/_template" "$INSTANCE/memory/projects/_template"
fi

echo "✓ Config synced from repo. Runtime state preserved."

# Lancer Koan via supervisord
exec supervisord -c /app/koan/docker/supervisord.conf
```

---

## Variables d'environnement (Railway Dashboard)

### Obligatoires

```
KOAN_TELEGRAM_TOKEN=...          # Token du bot Telegram (@BotFather)
KOAN_TELEGRAM_CHAT_ID=...       # ID du chat Telegram
ANTHROPIC_API_KEY=sk-ant-...    # OU CLAUDE_CODE_OAUTH_TOKEN
```

### Recommandées

```
GH_TOKEN=ghp_...                # GitHub CLI (pour PRs, issues)
KOAN_EMAIL=koan@example.com     # Identité git de l'agent
```

---

## Setup Railway

### Première fois

1. **Créer le service** : New Project → Deploy from GitHub repo → sélectionner `koan-config`
2. **Ajouter un volume** : Settings → Volumes → Mount path: `/app/instance`
3. **Variables d'env** : Settings → Variables → ajouter les secrets ci-dessus
4. **Deploy** : le bootstrap crée `instance/` sur le volume

### Mettre à jour la config

```bash
# Dans koan-config/
vim soul.md                      # Modifier la personnalité
git add -A && git commit -m "update soul"
git push                         # Railway redéploie automatiquement
```

Résultat : `soul.md` est écrasé, `missions.md` et `journal/` restent intacts.

### Mettre à jour Koan

Modifier le `Dockerfile` :

```dockerfile
ARG KOAN_VERSION=v2.0.0          # Nouvelle version
```

Push → Railway rebuild le container avec le nouveau code, le volume persiste.

### Nouveau dev dans l'équipe

```bash
git clone git@github.com:ton-org/koan-config.git
cd koan-config
cp .env.example .env             # Remplir ses propres tokens
# En local, utiliser Koan directement :
git clone https://github.com/koan/koan.git ../koan
cd ../koan && make setup && make start
```

---

## Scénarios de survie

| Événement | Missions perdues ? | Config perdue ? |
|-----------|-------------------|-----------------|
| Push une nouvelle config | Non | Mise à jour |
| Mise à jour de Koan (nouveau tag) | Non | Conservée |
| Railway redéploie le container | Non | Re-synchronisée |
| Railway restart le service | Non | Re-synchronisée |
| Suppression du service Railway | **Oui** (sauvegarder le volume avant) | Non (dans git) |

---

## Résumé visuel

```
                    ┌─────────────────────────┐
                    │     koan-config (git)    │
                    │                          │
                    │  config.yaml             │
                    │  soul.md                 │
                    │  projects.yaml           │
                    │  memory/global/*         │
                    └────────┬────────────────┘
                             │ git push
                             ▼
                    ┌─────────────────────────┐
                    │    Railway (container)    │
                    │                          │
                    │  /app = Koan upstream    │
                    │  /config = ta config     │
                    │                          │
                    │  bootstrap.sh:           │
                    │    config → volume ✓     │
                    │    runtime → skip si     │
                    │              existe ✓    │
                    └────────┬────────────────┘
                             │ mount
                             ▼
                    ┌─────────────────────────┐
                    │  Volume /app/instance    │
                    │  (persistant)            │
                    │                          │
                    │  config.yaml    ← écrasé │
                    │  soul.md        ← écrasé │
                    │  missions.md    ← intact │
                    │  journal/       ← intact │
                    │  memory/projects ← intact│
                    └─────────────────────────┘
```
