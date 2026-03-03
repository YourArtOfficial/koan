# Déploiement AI Governor — Mac Mini

## Prérequis

- macOS (Apple Silicon ou Intel)
- Docker Desktop ou OrbStack installé
- `cloudflared` (`brew install cloudflared`)
- Accès admin sur la machine (pour LaunchDaemon)

## Installation

### 1. Copier le projet

```bash
git clone git@github.com:YourArtOfficial/koan.git /opt/ai-governor
cd /opt/ai-governor
git checkout 007-integration-poc
```

### 2. Configurer les variables d'environnement

```bash
cp env.example .env
# Éditer .env avec les vraies valeurs :
# ANTHROPIC_API_KEY, LITELLM_MASTER_KEY, LITELLM_DB_PASSWORD, etc.
```

### 3. Configurer le tunnel Cloudflare

```bash
cloudflared tunnel create ai-governor
cloudflared tunnel route dns ai-governor governor.yourart.art

# Copier l'UUID du tunnel dans deploy/cloudflare-config.yml
# Remplacer <TUNNEL-UUID> par l'UUID réel
```

### 4. Installer le LaunchDaemon (démarrage automatique)

```bash
# Créer le répertoire de logs
sudo mkdir -p /var/log/ai-governor

# Copier le plist
sudo cp deploy/com.yourart.ai-governor.plist /Library/LaunchDaemons/

# Charger le daemon
sudo launchctl load /Library/LaunchDaemons/com.yourart.ai-governor.plist
```

### 5. Installer cloudflared comme service

```bash
sudo cloudflared service install
```

### 6. Vérifier

```bash
# Santé locale
curl http://localhost:5001/health

# Santé publique
curl https://governor.yourart.art/health
```

## Gestion

### Démarrer / Arrêter

```bash
# Démarrer manuellement
cd /opt/ai-governor && docker compose up -d

# Arrêter
cd /opt/ai-governor && docker compose down

# Voir les logs
docker compose logs -f koan

# Redémarrer un service
docker compose restart koan
```

### Mise à jour

```bash
cd /opt/ai-governor
git pull
docker compose up -d --build
```

### Logs

```bash
# Logs Docker
docker compose logs -f

# Logs launchd
tail -f /var/log/ai-governor/launchd.log
tail -f /var/log/ai-governor/launchd.err

# Logs agent
tail -f /opt/ai-governor/logs/awake.log
```

### Dépannage

| Problème | Diagnostic | Solution |
|----------|-----------|----------|
| Agent ne démarre pas | `docker compose ps` | Vérifier `.env`, `docker compose logs` |
| `/health` ne répond pas | `curl localhost:5001/health` | Vérifier que le port 5001 est exposé |
| Notifications non reçues | `/governor.status` | Vérifier Google Chat webhook dans GSM |
| Module en erreur | `/governor.status` | Consulter les logs du module |
| Mac Mini redémarré | `launchctl list com.yourart.ai-governor` | Le daemon relance automatiquement |
| Tunnel down | `cloudflared tunnel info ai-governor` | `sudo launchctl kickstart system/com.cloudflare.cloudflared` |
