# Maitrise des couts — AI Governor

> Registre complet des services, cles, couts, et process de gouvernance pour les citizen developers.

---

## Table des matieres

1. [Vue d'ensemble](#1-vue-densemble)
2. [Registre des services et cles](#2-registre-des-services-et-cles)
3. [Couts IA — LiteLLM Proxy](#3-couts-ia--litellm-proxy)
4. [Couts infrastructure Governor](#4-couts-infrastructure-governor)
5. [Couts citizens — le process](#5-couts-citizens--le-process)
6. [Process d'ajout d'un nouveau service](#6-process-dajout-dun-nouveau-service)
7. [Detection et compliance](#7-detection-et-compliance)
8. [Daily report et visibilite](#8-daily-report-et-visibilite)

---

## 1. Vue d'ensemble

Les couts sont repartis en trois categories :

| Categorie | Qui paye | Tracking | Maitrise |
|-----------|----------|----------|----------|
| **IA (LLM)** | Compte central | LiteLLM Proxy (budget par user, alertes) | Totale |
| **Infrastructure Governor** | Compte GCP central | Couts fixes (~50$/mois) | Totale |
| **Services externes citizens** | Compte centralise | Registry + API polling | A mettre en place |

Principe : **le citizen ne cree jamais de compte sur un service externe**. La tech provisionne, le governor tracke.

---

## 2. Registre des services et cles

### A. Services IA (trackes via LiteLLM)

| Service | Cle d'environnement | Obligatoire | Modeles | Cout trackable |
|---------|---------------------|:-----------:|---------|:--------------:|
| Anthropic | `ANTHROPIC_API_KEY` | Oui | claude-opus, claude-sonnet, claude-haiku | Oui |
| OpenAI | `OPENAI_API_KEY` | Non | gpt-4o, gpt-4o-mini | Oui |
| Google Gemini | `GOOGLE_API_KEY` | Non | gemini-flash, gemini-pro | Oui |
| Voyage AI | `VOYAGE_API_KEY` | Oui | voyage-3, voyage-3-lite (embeddings) | Oui |
| Local LLM | `KOAN_LOCAL_LLM_BASE_URL`, `_MODEL`, `_API_KEY` | Non | Ollama, llama.cpp, etc. | N/A (gratuit) |

Toutes ces cles sont stockees dans le `.env` (local) ou Google Secret Manager (cloud). Elles ne sont **jamais partagees avec les citizens** — les citizens accedent aux LLMs via des **cles virtuelles LiteLLM** avec budget individuel.

### B. Infrastructure Governor (couts fixes)

| Service | Cles | Cout mensuel | Notes |
|---------|------|:------------:|-------|
| LiteLLM Proxy | `LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY` | ~1$ | Scale-to-zero sur Cloud Run |
| PostgreSQL | `LITELLM_DB_PASSWORD` | ~12$ | Cloud SQL micro (spend tracking) |
| Google Cloud Run | ADC + `GOOGLE_CLOUD_PROJECT` | ~35-40$ | Worker Pool always-on |
| Google Cloud Storage | ADC | ~0.05$ | Config, rapports, detections |
| Google Secret Manager | ADC | 0$ | Free tier suffisant |
| Cloud Scheduler | ADC | ~0$ | Daily reports |
| Cloudflare Tunnel | Tunnel UUID + credentials | 0$ | Mac Mini uniquement |
| **Total** | | **~48-53$** | |

### C. Communication (gratuit)

| Service | Cles | Usage |
|---------|------|-------|
| Telegram | `KOAN_TELEGRAM_TOKEN`, `KOAN_TELEGRAM_CHAT_ID` | Bridge principal (polling + outbox) |
| Slack | `KOAN_SLACK_BOT_TOKEN`, `KOAN_SLACK_APP_TOKEN`, `KOAN_SLACK_CHANNEL_ID` | Bridge alternatif |
| Google Chat | `GCHAT_WEBHOOK_URL` / `KOAN_GCHAT_WEBHOOK_URL` | Notifications governors |
| SMTP | `KOAN_SMTP_HOST`, `_PORT`, `_USER`, `_PASSWORD`, `EMAIL_KOAN_OWNER` | Notifications email |

### D. Dev Tools (gratuit)

| Service | Cles | Usage |
|---------|------|-------|
| GitHub | `GITHUB_USER`, `GITHUB_TOKEN`/`GH_TOKEN`, `GITHUB_WEBHOOK_SECRET` | Repos, PRs, @mentions |
| GitLab | `GITLAB_TOKEN` | Surveillance repos (watcher) |
| Claude Code CLI | `CLAUDE_AUTH_TOKEN` (Docker) ou OAuth local | Execution agent |
| Git identity | `KOAN_EMAIL` | Signature des commits |

### E. Services externes citizens (a tracker)

| Service | Cles | Statut actuel |
|---------|------|---------------|
| Railway | Aucune centralisee | Spec existe, pas de tracking |
| Supabase, Resend, etc. | Ad hoc par citizen | Aucun tracking |

---

## 3. Couts IA — LiteLLM Proxy

Le proxy LiteLLM est la pierre angulaire du controle des couts IA. Il agit comme passerelle unique entre les citizens et les fournisseurs LLM.

### Comment ca marche

```
Citizen (Claude/Cursor/Copilot)
        │
        │  cle virtuelle LiteLLM (sk-citizen-xxx)
        ▼
┌───────────────────┐
│   LiteLLM Proxy   │──► Anthropic (ANTHROPIC_API_KEY)
│   (port 4000)     │──► OpenAI (OPENAI_API_KEY)
│                   │──► Google (GOOGLE_API_KEY)
│   Budget par user │──► Voyage (VOYAGE_API_KEY)
│   Alertes webhook │
│   Spend tracking  │
└───────────────────┘
```

### Commandes governor

```bash
# Budget
governor budget status                 # Vue globale tous citizens
governor budget status theo            # Detail pour un citizen
governor budget set theo 50            # Fixer budget mensuel (EUR)
governor budget approve <request-id>   # Approuver une demande

# Cles virtuelles
governor keys list                     # Toutes les cles
governor keys list --user theo         # Cles d'un citizen
governor keys create theo              # Generer une cle
governor keys revoke <key>             # Revoquer une cle
```

### Seuils d'alerte

Configures dans `config.yaml` :

```yaml
budget_controller:
  litellm_url: http://litellm-proxy:4000
  litellm_master_key_env: LITELLM_MASTER_KEY
  eur_usd_rate: 1.08
  global_budget_eur: 300
  alert_threshold_percent: 80
```

Et les seuils internes de l'agent Koan :

```yaml
budget:
  warn_at_percent: 70    # Passe en mode review (missions plus legeres)
  stop_at_percent: 85    # Arret complet de l'agent
```

---

## 4. Couts infrastructure Governor

L'infrastructure Governor tourne sur Google Cloud Platform avec des couts fixes previsibles.

| Composant | Service GCP | Tier | Cout mensuel |
|-----------|-------------|------|:------------:|
| Agent + Bridge | Cloud Run (Worker Pool) | Always-on, 1 CPU / 512MB | ~35-40$ |
| BDD LiteLLM | Cloud SQL | db-f1-micro, 10GB SSD | ~12$ |
| LiteLLM Proxy | Cloud Run | Scale-to-zero | ~1$ |
| Stockage | Cloud Storage | Standard | ~0.05$ |
| Secrets | Secret Manager | Free tier | 0$ |
| Scheduler | Cloud Scheduler | 3 jobs/mois gratuits | 0$ |
| **Total** | | | **~48-53$** |

Ces couts sont **independants du nombre de citizens**. Le seul facteur de variation est l'utilisation de Cloud SQL si le volume de logs LiteLLM augmente significativement.

---

## 5. Couts citizens — le process

### Regle fondamentale

> **Seul Railway est autorise comme plateforme de deploiement.**
> Tout autre service necessite une demande formelle via `/service-request`.

Cette contrainte est imposee via le `CLAUDE.md` des projets citizens :

```markdown
## Deploiement
- Seul provider autorise : **Railway**
- Tout deploiement sur un autre service necessite une demande via /service-request
- Ne JAMAIS creer de comptes sur d'autres platforms (Vercel, Fly, Render, etc.)
- Les credentials de deploiement sont fournies via variables d'environnement
```

### Pourquoi un seul provider ?

1. **Une seule API de billing a integrer** — Railway expose une API GraphQL pour les couts
2. **Un seul compte centralise** — La tech gere le compte, les citizens n'ont pas le mot de passe
3. **Un seul circuit de monitoring** — Simplifie le daily report et les alertes
4. **Deploiement via GitHub** — Le citizen push, Railway deploy automatiquement via le repo connecte

### Registry des services : `instance/services.yaml`

Chaque service provisionne pour un citizen est enregistre dans ce fichier :

```yaml
defaults:
  allowed_providers: [railway]
  require_approval_for_new: true

services:
  # Service standard — Railway pour le deploy
  - project: app-theo
    citizen: theo
    provider: railway
    plan: hobby
    monthly_budget_eur: 5
    api_token_vault_key: RAILWAY_TOKEN  # cle partagee, compte centralise
    tracked: true

  # Service additionnel approuve
  - project: app-theo
    citizen: theo
    provider: supabase
    plan: free
    monthly_budget_eur: 0
    approved_by: stephane
    approved_at: 2026-03-01
    api_token_vault_key: SUPABASE_KEY_THEO
    tracked: true
```

---

## 6. Process d'ajout d'un nouveau service

Quand un citizen a besoin d'un service non-standard (base de donnees, envoi d'emails, stockage, etc.), il passe par le process suivant :

### Flow complet

```
1. Citizen fait /service-request <provider> "<justification>"
   │
   ▼
2. Mission [governance] creee + notification governor
   │
   ▼
3. Tech evalue le besoin
   ├── Existe deja ? → Partager la cle existante via vault
   ├── Couvert par Railway ? → Refuser, utiliser les addons Railway
   └── Nouveau besoin legitime ? → Continuer ↓
   │
   ▼
4. Tech cree le compte sur le provider
   │
   ▼
5. Tech enregistre dans le governor :

   # Stocker la cle dans le vault
   governor vault store <PROVIDER>_KEY "valeur" \
     --project <projet> --citizen <nom>

   # Enregistrer le service dans le registry
   governor services register <projet> <provider> \
     --plan <plan> --budget-eur <montant> \
     --api-token-vault-key <PROVIDER>_KEY

   # Si le provider a une API de billing, configurer le polling
   governor costs configure <provider> \
     --api-token-vault-key <PROVIDER>_API_TOKEN
   │
   ▼
6. Citizen recoit les credentials via :
   governor env inject <projet>    # .env temporaire 24h TTL
   │
   ▼
7. Governor commence le cost tracking automatique
   │
   ▼
8. Daily report inclut le nouveau service
```

### Commandes governor prevues

```bash
# Gestion des services autorises
governor services list                           # Tous les services trackes
governor services list --citizen theo            # Services d'un citizen
governor services register <projet> <provider>   # Enregistrer un service
governor services remove <projet> <provider>     # Retirer un service

# Couts infra
governor costs poll                              # Rafraichir depuis les APIs
governor costs status                            # Vue globale
governor costs citizen <nom>                     # Par citizen
governor costs set-limit <nom> <montant-eur>     # Fixer un plafond
governor costs alert-threshold <percent>         # Seuil d'alerte
```

---

## 7. Detection et compliance

### Watcher : fichiers de deploiement surveilles

Le watcher GitHub detecte automatiquement les fichiers de deploiement dans les commits des citizens :

| Fichier | Provider | Action |
|---------|----------|--------|
| `vercel.json` | Vercel | Alerte immediate au governor |
| `fly.toml` | Fly.io | Alerte immediate au governor |
| `render.yaml` | Render | Alerte immediate au governor |
| `netlify.toml` | Netlify | Alerte immediate au governor |
| `heroku.yml` / `Procfile` | Heroku | Alerte immediate au governor |
| `docker-compose.yml` | Divers | Review (peut etre legitime) |
| `railway.toml` | Railway | OK (autorise) |
| `.env` / `*.key` / `*.pem` | Secrets | Alerte credential |

### Triple couche de protection

| Couche | Mecanisme | Quand | Qui |
|--------|-----------|-------|-----|
| **CLAUDE.md** | L'agent IA du citizen refuse de deployer ailleurs | A chaque action de l'agent | Agent IA |
| **Watcher GitHub** | Detection des fichiers de deploy non-autorises | A chaque commit/PR | Governor automatique |
| **Compte Railway centralise** | Le citizen n'a pas les credentials du compte Railway | Permanent | Tech |

### Risques residuels

| Risque | Probabilite | Mitigation |
|--------|:-----------:|------------|
| Citizen cree un compte Railway personnel | Faible | Le CLAUDE.md interdit, le watcher detecte `railway.toml` |
| Citizen deploie manuellement (sans agent) | Moyenne | Watcher detecte les fichiers de config dans les commits |
| Citizen utilise un service sans fichier de config | Faible | Scan de credentials (`governor scan`) detecte les tokens inconnus |
| Service gratuit non-declare | Faible | Pas d'impact financier, mais manque de visibilite |

---

## 8. Daily report et visibilite

Le daily report agrege tous les couts pour donner une vue unifiee au governor.

### Format du rapport

```
## Couts du jour — 2026-03-09

### IA (LiteLLM)
Total : 12.40 EUR (4 citizens actifs)

| Citizen | Modele principal | Depense | Budget | % |
|---------|-----------------|---------|--------|---|
| theo    | claude-sonnet   | 5.20 EUR | 50 EUR | 10.4% |
| dany    | gpt-4o          | 4.10 EUR | 75 EUR | 5.5% |
| art236  | gemini-pro      | 2.40 EUR | 30 EUR | 8.0% |
| emma    | claude-haiku    | 0.70 EUR | 20 EUR | 3.5% |

### Infrastructure citizens
Total : 8.20 EUR

| Citizen | Service  | Projet    | Cout     | Budget | % |
|---------|----------|-----------|----------|--------|---|
| theo    | Railway  | app-theo  | 3.00 EUR | 10 EUR | 30% |
| theo    | Supabase | app-theo  | 0.00 EUR | 0 EUR  | - |
| dany    | Railway  | app-dany  | 5.20 EUR | 15 EUR | 35% |

### Total consolide
IA + Infra : 20.60 EUR / budget global 300 EUR (6.9%)

### Alertes
- dany : Railway a 35% du budget mensuel (progression rapide)
```

### Source des donnees

| Donnee | Source | Frequence |
|--------|--------|-----------|
| Depenses IA par citizen | LiteLLM `/spend/logs` | Temps reel |
| Depenses IA par modele | LiteLLM `/global/spend/models` | Temps reel |
| Budget IA restant | LiteLLM `/user/info` | Temps reel |
| Couts Railway | Railway API GraphQL | Quotidien (polling) |
| Couts autres services | API du provider | Quotidien (polling) |
| Services enregistres | `instance/services.yaml` | Statique |

---

## Inventaire complet des cles (28 secrets)

Pour reference, voici la liste exhaustive de toutes les cles/secrets du systeme :

```
# IA (via LiteLLM — jamais exposees aux citizens)
ANTHROPIC_API_KEY             # Anthropic Claude
OPENAI_API_KEY                # OpenAI GPT
GOOGLE_API_KEY                # Google Gemini
VOYAGE_API_KEY                # Voyage AI (embeddings)

# LiteLLM Proxy
LITELLM_MASTER_KEY            # Cle admin du proxy
LITELLM_SALT_KEY              # Salt pour hash des cles virtuelles
LITELLM_DB_PASSWORD           # Mot de passe PostgreSQL

# Google Cloud Platform
GOOGLE_CLOUD_PROJECT          # ID du projet GCP
GOOGLE_APPLICATION_CREDENTIALS # Chemin vers ADC (si pas de default)

# Communication
KOAN_TELEGRAM_TOKEN           # Token bot Telegram
KOAN_TELEGRAM_CHAT_ID         # ID du chat Telegram
KOAN_SLACK_BOT_TOKEN          # Token bot Slack (xoxb-)
KOAN_SLACK_APP_TOKEN          # Token app Slack (xapp-)
KOAN_SLACK_CHANNEL_ID         # ID du channel Slack
GCHAT_WEBHOOK_URL             # Webhook Google Chat (cloud)
KOAN_GCHAT_WEBHOOK_URL        # Webhook Google Chat (local)
KOAN_SMTP_HOST                # Serveur SMTP
KOAN_SMTP_PORT                # Port SMTP
KOAN_SMTP_USER                # User SMTP
KOAN_SMTP_PASSWORD            # Mot de passe SMTP
EMAIL_KOAN_OWNER              # Email destinataire

# Dev Tools
GITHUB_USER                   # Username GitHub du bot
GITHUB_TOKEN / GH_TOKEN       # Token GitHub
GITHUB_WEBHOOK_SECRET         # Secret webhook GitHub
GITLAB_TOKEN                  # Token GitLab
CLAUDE_AUTH_TOKEN              # Token Claude CLI (Docker)
KOAN_EMAIL                    # Email pour les commits git

# Local LLM (optionnel)
KOAN_LOCAL_LLM_BASE_URL       # URL du serveur local
KOAN_LOCAL_LLM_MODEL          # Nom du modele
KOAN_LOCAL_LLM_API_KEY        # Cle API (souvent vide)
```

### Ou sont stockees ces cles

| Environnement | Stockage | Acces |
|---------------|----------|-------|
| Developpement local | Fichier `.env` (gitignore) | Tech uniquement |
| Docker (Mac Mini) | `.env` + mount volumes | Tech uniquement |
| Cloud Run (production) | Google Secret Manager | IAM roles GCP |
| Citizens | Cles virtuelles LiteLLM | Via `governor keys create` |
| Services citizens | Vault + `governor env inject` | .env temporaire 24h |
