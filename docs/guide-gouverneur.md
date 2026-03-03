# Guide Gouverneur — AI Governor

> Documentation d'administration de l'AI Governor pour les gouverneurs humains de YourArtOfficial.

---

## Table des matieres

1. [Vue d'ensemble](#1-vue-densemble)
2. [Demarrage rapide](#2-demarrage-rapide)
3. [Commandes disponibles](#3-commandes-disponibles)
4. [Configuration](#4-configuration)
5. [Gestion des citizens](#5-gestion-des-citizens)
6. [Gestion des budgets](#6-gestion-des-budgets)
7. [Surveillance](#7-surveillance)
8. [Depannage](#8-depannage)

---

## 1. Vue d'ensemble

### A quoi sert l'AI Governor ?

L'AI Governor est un agent qui tourne en continu (24/7) et assure quatre missions :

| Module | Role |
|--------|------|
| **Budget Controller** | Gere les budgets API (LLM) par citizen, attribue les cles virtuelles, alerte quand un seuil est atteint |
| **Credential Vault** | Centralise les secrets (tokens, cles API) dans Google Secret Manager, injecte les `.env` de facon securisee, detecte les credentials en clair dans le code |
| **Watcher** | Surveille les repos GitHub et GitLab en temps reel, capture les commits, PRs, issues, et alimente le journal d'audit |
| **Advisor** | Analyse les commits des citizens, detecte les duplications avec la production GitLab et le catalogue MCP, notifie les citizens concernes |

### Architecture simplifiee

```
                    ┌────────────────────────┐
                    │     AI Governor         │
                    │   (agent Koan unifie)   │
                    └────────┬───────────────┘
                             │
            ┌────────────────┼────────────────┐
            │                │                │
     ┌──────▼──────┐  ┌─────▼──────┐  ┌──────▼──────┐
     │   Watcher    │  │  Advisor   │  │   Budget    │
     │  (GitHub +   │──│ (detection │  │ Controller  │
     │   GitLab)    │  │ duplicat.) │  │  (LiteLLM)  │
     └──────────────┘  └────────────┘  └─────────────┘
            │                                 │
            │          ┌─────────────┐        │
            └──────────│ Credential  │────────┘
                       │   Vault     │
                       │   (GSM)     │
                       └─────────────┘
```

**Principe fondateur** : l'agent propose, l'humain decide. Aucune action critique n'est executee sans validation d'un gouverneur.

### Niveaux d'autonomie

Chaque module a un niveau d'autonomie configurable :

| Niveau | Comportement |
|--------|-------------|
| **watch** | L'agent log les evenements et ne notifie que les gouverneurs. Les citizens ne recoivent rien. |
| **notify** | L'agent notifie directement les citizens concernes ET les gouverneurs. |
| **supervise** | L'agent notifie le gouverneur et attend sa validation avant de contacter le citizen. |

---

## 2. Demarrage rapide

### Prerequis

- Docker et Docker Compose installes
- Acces Google Cloud (Secret Manager configure)
- Tokens GitHub et GitLab configures
- Webhook Google Chat configure

### Demarrer l'agent

```bash
# Se placer dans le repertoire du projet
cd /opt/ai-governor   # Mac Mini
# ou
cd ~/Projets/koan-fork   # Dev local

# Lancer la stack (LiteLLM + Postgres + Agent)
docker compose up -d
```

### Verifier que tout fonctionne

```bash
# 1. Health check HTTP
curl http://localhost:5001/health
```

Reponse attendue :

```json
{
  "status": "ok",
  "modules": {
    "watcher": "ok",
    "advisor": "ok",
    "budget_controller": "ok",
    "credential_vault": "ok"
  },
  "uptime": "3h 12m"
}
```

```bash
# 2. Status complet via la skill (dans le chat Koan)
/governor.status status
```

Si un module affiche `degraded` ou `error`, consultez la section [Depannage](#8-depannage).

---

## 3. Commandes disponibles

Toutes les commandes s'executent dans le chat Koan (Telegram, Google Chat, ou terminal).

### governor.status — Etat de l'agent

| Commande | Description | Exemple |
|----------|-------------|---------|
| `/governor.status status` | Affiche l'etat de sante de tous les modules, les metriques cles et l'uptime | `/governor.status status` |
| `/governor.status report [period]` | Genere un rapport periodique (semaine courante par defaut) | `/governor.status report` ou `/governor.status report 2026-W11` |

Exemple de sortie de `/governor.status status` :

```
AI Governor — Operationnel
Uptime: 3j 14h 22m

Modules:
  Budget Controller: OK — 8 cles actives, 187EUR/300EUR consommes
  Credential Vault: OK — 12 secrets, dernier acces il y a 2h
  Watcher: OK — 47 evenements aujourd'hui, 12 repos surveilles
  Advisor: OK — 3 detections cette semaine, 1 faux positif
```

### governor.autonomy — Niveaux d'autonomie

| Commande | Description | Exemple |
|----------|-------------|---------|
| `/governor.autonomy get` | Affiche les niveaux d'autonomie de tous les modules | `/governor.autonomy get` |
| `/governor.autonomy get <module>` | Affiche le niveau d'un module specifique | `/governor.autonomy get advisor` |
| `/governor.autonomy set <module> <level>` | Change le niveau d'autonomie (watch, notify, supervise) | `/governor.autonomy set advisor notify` |

Le changement prend effet immediatement, sans redemarrage.

Modules valides : `budget_controller`, `credential_vault`, `watcher`, `advisor`

### governor.rollout — Deploiement progressif

| Commande | Description | Exemple |
|----------|-------------|---------|
| `/governor.rollout list` | Affiche les groupes de rollout et leurs membres | `/governor.rollout list` |
| `/governor.rollout activate <group>` | Active la surveillance pour un groupe | `/governor.rollout activate pilots` |
| `/governor.rollout add <group> <login>` | Ajoute un citizen a un groupe | `/governor.rollout add pilots vbLBB` |
| `/governor.rollout remove <group> <login>` | Retire un citizen d'un groupe | `/governor.rollout remove pilots vbLBB` |

Groupes predefinis : `governors`, `pilots`, `all`

### governor.offboard — Depart d'un citizen

| Commande | Description | Exemple |
|----------|-------------|---------|
| `/governor.offboard remove <login>` | Lance la procedure de depart (revocation credentials, suppression budget, archivage donnees) | `/governor.offboard remove alexandredebats-yourart` |

Cette commande demande une confirmation avant d'executer. Les donnees historiques sont archivees, pas supprimees.

### governor.watcher — Surveillance repos

| Commande | Description | Exemple |
|----------|-------------|---------|
| `/governor.watcher status` | Etat du module watcher | `/governor.watcher status` |
| `/governor.watcher log` | Derniers evenements du journal | `/governor.watcher log` |
| `/governor.watcher repos` | Liste des repos surveilles | `/governor.watcher repos` |
| `/governor.watcher scan` | Force un scan immediat (GitHub + GitLab) | `/governor.watcher scan` |
| `/governor.watcher catch-up` | Rattrape les evenements manques depuis le dernier arret | `/governor.watcher catch-up` |
| `/governor.watcher alerts` | Affiche les alertes recentes | `/governor.watcher alerts` |
| `/governor.watcher register` | Enregistre/met a jour un repo dans la surveillance | `/governor.watcher register` |

### governor.advisor — Detection de duplications

| Commande | Description | Exemple |
|----------|-------------|---------|
| `/governor.advisor status` | Etat du module advisor | `/governor.advisor status` |
| `/governor.advisor scan` | Force un scan d'indexation des repos | `/governor.advisor scan` |
| `/governor.advisor analyze` | Lance une analyse de duplication | `/governor.advisor analyze` |
| `/governor.advisor report` | Affiche les detections recentes | `/governor.advisor report` |
| `/governor.advisor catalog` | Affiche le catalogue MCP (ressources disponibles) | `/governor.advisor catalog` |
| `/governor.advisor repos` | Liste des repos indexes | `/governor.advisor repos` |
| `/governor.advisor feedback` | Enregistre un retour sur une detection | `/governor.advisor feedback` |

### governor.vault — Gestion des credentials

Se referer a la spec 004 pour le detail des commandes. Principales operations :

| Commande | Description |
|----------|-------------|
| `/governor.vault status` | Etat du vault et nombre de secrets |
| `/governor.env inject` | Injecte les variables d'environnement pour un projet |
| `/governor.scan run` | Lance un scan detect-secrets sur un repo |

### governor.budget — Gestion budgetaire

Se referer a la spec 003 pour le detail des commandes. Principales operations :

| Commande | Description |
|----------|-------------|
| `/governor.budget status` | Etat du budget global et par citizen |
| `/governor.keys list` | Liste des cles virtuelles LiteLLM actives |
| `/governor.keys create` | Cree une nouvelle cle virtuelle pour un citizen |

---

## 4. Configuration

Toute la configuration se trouve dans `instance/config.yaml`. Voici les sections pertinentes pour l'administration.

### governor.autonomy

Definit le niveau d'autonomie de chaque module.

```yaml
governor:
  autonomy:
    budget_controller: notify    # notify les citizens directement
    credential_vault: supervise  # attend validation du gouverneur
    watcher: notify              # notify les citizens directement
    advisor: watch               # log seulement, pas de notification citizen
```

Valeurs possibles : `watch`, `notify`, `supervise`

Pour le POC, on recommande de commencer en `watch` pour l'advisor et d'augmenter progressivement.

### governor.rollout

Definit les groupes de deploiement progressif.

```yaml
governor:
  rollout:
    groups:
      governors:
        active: true
        members:
          - stephaneyourart
      pilots:
        active: false       # Activer quand pret pour le pilote
        members:
          - dany-yourart
          - art236
      all:
        active: false       # Activer apres validation du pilote
        members: []          # Rempli dynamiquement
```

Seuls les membres des groupes **actifs** recoivent des notifications.

### governor.report

Configure les rapports periodiques envoyes aux gouverneurs.

```yaml
governor:
  report:
    enabled: true
    frequency: weekly       # daily, weekly, monthly
    day: monday             # Jour d'envoi (pour weekly)
    hour: 9                 # Heure d'envoi (UTC)
    recipients: governors   # Groupe de rollout destinataire
```

### governor.health

Configure les health checks automatiques.

```yaml
governor:
  health:
    check_interval_seconds: 30   # Frequence des verifications
    modules:
      watcher:
        critical: false          # Panne ne bloque pas l'agent
      advisor:
        critical: false
      budget_controller:
        critical: true           # Panne = statut global "error"
      credential_vault:
        critical: true
```

Un module marque `critical: true` fait passer le statut global en `error` s'il tombe. Les modules non critiques passent en `degraded` sans bloquer les autres.

### governor.circuit_breakers

Protegent l'agent contre les pannes des services externes. Quand un service echoue N fois de suite, le circuit s'ouvre et l'agent arrete d'appeler ce service pendant un temps defini.

```yaml
governor:
  circuit_breakers:
    google_secret_manager:
      fail_max: 3                    # 3 echecs consecutifs ouvrent le circuit
      reset_timeout_seconds: 120     # Reessaye apres 2 minutes
    github_api:
      fail_max: 5
      reset_timeout_seconds: 60
    gitlab_api:
      fail_max: 5
      reset_timeout_seconds: 60
    google_chat:
      fail_max: 3
      reset_timeout_seconds: 30
    litellm:
      fail_max: 3
      reset_timeout_seconds: 300     # 5 minutes (le plus critique)
```

### watcher

Configure la surveillance des repos GitHub et GitLab.

```yaml
watcher:
  enabled: true
  github:
    org: YourArtOfficial
    webhook_secret_gsm: "governor-github-webhook-secret"
    events:
      - push
      - pull_request
      - issues
      - create
      - member
      - repository
      - organization
    catch_up_on_start: true
  gitlab:
    group: yourart
    token_env: GITLAB_TOKEN
    scan_interval_minutes: 15
    branches:
      - main
      - master
  notifications:
    google_chat_webhook_gsm: "governor-gchat-webhook-url"
    grouping_window_minutes: 5
    alert_events:
      - credential_detected
      - unknown_author
      - force_push
      - new_repo
      - watcher_error
```

### advisor

Configure la detection de duplications.

```yaml
advisor:
  enabled: true
  summary_model: "claude-haiku-4-5-20251001"
  judge_model: "claude-sonnet-4-6"
  embedding_model: "voyage-code-3"
  similarity_threshold: 0.60
  notification_threshold: 0.60
  dedup_window_days: 7
  scan_on_event: true
  file_min_lines: 50
```

Les seuils `similarity_threshold` et `notification_threshold` controlent la sensibilite de la detection. Plus bas = plus de detections (mais plus de faux positifs). Valeur recommandee pour le POC : `0.60`.

### vault

Configure le Credential Vault (Google Secret Manager).

```yaml
vault:
  gcp_project_id: "yourart-governor"
  default_ttl_hours: 24
  alert_stale_days: 90
  label_prefix: "ai-governor"
  governors:
    - stephane@yourart.art
    - daniel@yourart.art
```

### budget_controller

Configure le Budget Controller (LiteLLM).

```yaml
budget_controller:
  litellm_url: "http://litellm-proxy:4000"
  litellm_master_key_env: "LITELLM_MASTER_KEY"
  eur_usd_rate: 1.08
  global_budget_eur: 300
  alert_threshold_percent: 80
  governors:
    - stephane@yourart.art
    - daniel@yourart.art
```

---

## 5. Gestion des citizens

### Registre des utilisateurs

Le fichier `instance/watcher/user_registry.yaml` contient la liste de tous les utilisateurs connus. Chaque entree definit :

```yaml
- login: dany-yourart
  type: citizen          # citizen, tech, governor, unknown
  platform: github
  aliases:               # Pour les utilisateurs multi-plateformes
    - platform: gitlab
      login: dany.yourart
  rollout_group: pilots
  active: true
```

### Ajouter un nouveau citizen

1. Ajouter son entree dans `user_registry.yaml`
2. L'ajouter a un groupe de rollout :
   ```
   /governor.rollout add pilots nouveau-login
   ```
3. Verifier qu'il apparait :
   ```
   /governor.rollout list
   ```

### Retirer un citizen (depart)

```
/governor.offboard remove login-du-citizen
```

Cette commande effectue automatiquement :
- Revocation de toutes les cles virtuelles LiteLLM
- Invalidation des injections `.env` actives
- Archivage des donnees historiques (elles restent consultables)
- Retrait de tous les groupes de rollout
- Log de l'action dans le journal d'audit

### Classification des utilisateurs

| Type | Description | Exemples |
|------|-------------|----------|
| `governor` | Administrateur avec acces complet | stephaneyourart |
| `tech` | Developpeur technique de l'equipe | Developpeurs internes |
| `citizen` | Citizen dev / vibe coder | dany-yourart, art236, vbLBB |
| `unknown` | Utilisateur non identifie (declenche une alerte) | Nouveau compte non enregistre |

### Identites cross-plateforme

Certains utilisateurs sont actifs sur GitHub ET GitLab sous des logins differents. Le champ `aliases` permet de les correler pour eviter les fausses detections de duplication intra-personne.

Exemple pour Theo Vassal (GitLab: `theo.vassal`, GitHub: `theo-yourart`) :

```yaml
- login: theo.vassal
  type: citizen
  platform: gitlab
  aliases:
    - platform: github
      login: theo-yourart
  rollout_group: pilots
  active: true
```

---

## 6. Gestion des budgets

### Fonctionnement general

Le Budget Controller gere le budget API LLM mensuel (300 EUR par defaut) via LiteLLM Proxy. Chaque citizen recoit une cle virtuelle avec un plafond individuel.

### Consulter le budget

```
/governor.budget status
```

Affiche : budget global, consommation par citizen, alertes en cours.

### Creer une cle pour un citizen

```
/governor.keys create
```

Suit un processus interactif : nom du citizen, budget mensuel alloue, modeles autorises.

### Alertes automatiques

| Seuil | Action |
|-------|--------|
| 80% du budget individuel | Notification au citizen + gouverneur |
| 85% du budget global | L'agent arrete les nouveaux appels API |
| 100% du budget individuel | Cle virtuelle desactivee, notification au citizen |

### Ajuster un budget

Modifier `global_budget_eur` dans `config.yaml` pour le budget global. Pour les budgets individuels, utiliser les commandes `/governor.keys` ou l'interface LiteLLM directement.

---

## 7. Surveillance

### Journal d'evenements

Le Watcher maintient un journal JSONL dans `instance/watcher/events/`. Un fichier par jour :

```
instance/watcher/events/2026-03-03.jsonl
instance/watcher/events/2026-03-04.jsonl
```

Consulter les derniers evenements :

```
/governor.watcher log
```

### Rapports periodiques

Un rapport est envoye automatiquement chaque lundi a 9h (configurable). Il contient :

- Nombre d'evenements traites (GitHub + GitLab)
- Detections de duplication et leur statut
- Budget consomme par citizen
- Alertes credentials
- Top citizens actifs

Generer un rapport a la demande :

```
/governor.status report
```

### Detections de l'Advisor

Les detections sont stockees dans `instance/advisor/detections.yaml`. Chaque detection contient :

- Le commit source et le code similaire detecte
- Le score de similarite
- Le statut (en attente, confirme, faux positif)

Consulter les detections :

```
/governor.advisor report
```

Enregistrer un feedback sur une detection :

```
/governor.advisor feedback
```

Le feedback ameliore les futures detections en ajustant les seuils internes.

### Alertes critiques

Les evenements suivants declenchent une alerte immediate aux gouverneurs via Google Chat :

| Evenement | Description |
|-----------|-------------|
| `credential_detected` | Un secret (cle API, token) a ete pousse en clair dans le code |
| `unknown_author` | Un commit provient d'un utilisateur non enregistre |
| `force_push` | Un force push a ete detecte sur un repo surveille |
| `new_repo` | Un nouveau repo a ete cree dans l'organisation |
| `watcher_error` | Le module watcher a rencontre une erreur |

---

## 8. Depannage

### Un module affiche "error" ou "degraded"

**Diagnostic** :

```
/governor.status status
```

**Causes possibles** :

| Module | Cause frequente | Solution |
|--------|----------------|----------|
| Budget Controller | LiteLLM Proxy injoignable | Verifier que Docker tourne : `docker compose ps`. Redemarrer si necessaire : `docker compose restart litellm-proxy` |
| Credential Vault | Google Secret Manager inaccessible | Verifier les credentials GCP : `gcloud auth application-default print-access-token`. Le circuit breaker se rearme automatiquement apres 2 min. |
| Watcher | Webhook GitHub non recu | Verifier la configuration du webhook dans les settings GitHub de l'org. Lancer un catch-up : `/governor.watcher catch-up` |
| Advisor | Base SQLite corrompue | Relancer l'indexation : `/governor.advisor scan`. Si le probleme persiste, supprimer `instance/advisor/advisor.db` et relancer le scan. |

### Les notifications Google Chat ne sont pas recues

1. **Verifier le webhook** : le secret `governor-gchat-webhook-url` dans Google Secret Manager est-il correct ?
2. **Verifier le circuit breaker** : si Google Chat a ete indisponible, le circuit breaker peut etre ouvert. Il se rearme automatiquement apres 30 secondes.
3. **Verifier la file d'attente** : les notifications non envoyees sont stockees dans `instance/watcher/notification_queue.yaml`. Elles seront envoyees automatiquement quand le service revient.
4. **Verifier le rollout** : seuls les membres des groupes actifs recoivent des notifications. Verifier avec `/governor.rollout list`.

### Google Chat est completement down

L'agent continue de fonctionner normalement. Les notifications sont mises en file d'attente dans `instance/watcher/notification_queue.yaml` et seront envoyees automatiquement au retour du service. Aucune action requise de votre part.

### Le Mac Mini a redemarre (coupure courant, mise a jour OS)

L'agent est configure comme LaunchDaemon macOS et redemarre automatiquement. Pour verifier :

```bash
# Verifier que l'agent tourne
sudo launchctl list | grep ai-governor

# Verifier les logs de demarrage
tail -50 /opt/ai-governor/logs/agent.log

# Si l'agent ne s'est pas relance
sudo launchctl load /Library/LaunchDaemons/com.yourart.ai-governor.plist
```

L'agent rattrape automatiquement les evenements manques au redemarrage grace au mecanisme de catch-up (`catch_up_on_start: true`).

### Un circuit breaker est ouvert

Les circuit breakers protegent l'agent contre les pannes des services externes. Quand un service echoue plusieurs fois de suite, l'agent arrete temporairement de l'appeler.

**Diagnostic** :

```
/governor.status status
```

Le statut affiche les circuit breakers ouverts.

**Comportement** :

- Le circuit breaker se rearme automatiquement apres le delai configure (`reset_timeout_seconds`)
- L'agent fonctionne en mode degrade en attendant
- Les actions en attente sont mises en file d'attente et executees au retour du service

**Delais de rearmement par service** :

| Service | Echecs avant ouverture | Delai de rearmement |
|---------|----------------------|---------------------|
| Google Secret Manager | 3 | 2 minutes |
| GitHub API | 5 | 1 minute |
| GitLab API | 5 | 1 minute |
| Google Chat | 3 | 30 secondes |
| LiteLLM | 3 | 5 minutes |

### L'agent ne detecte pas les commits d'un citizen

1. **Le citizen est-il dans un groupe actif ?** Verifier avec `/governor.rollout list`
2. **Le citizen est-il enregistre ?** Verifier dans `instance/watcher/user_registry.yaml`
3. **Le webhook GitHub fonctionne-t-il ?** Verifier dans Settings > Webhooks de l'org GitHub. La colonne "Recent Deliveries" montre les erreurs.
4. **Le repo est-il surveille ?** Verifier avec `/governor.watcher repos`

### Trop de faux positifs dans les detections

1. Augmenter les seuils dans `config.yaml` :
   ```yaml
   advisor:
     similarity_threshold: 0.70    # Etait 0.60
     notification_threshold: 0.70
   ```
2. Utiliser le feedback pour entrainer le systeme : `/governor.advisor feedback`
3. Reduire la fenetre de deduplication si les detections sont repetitives :
   ```yaml
   advisor:
     dedup_window_days: 14    # Etait 7
   ```
