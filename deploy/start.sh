#!/bin/bash
# AI Governor — Docker Compose startup script
# Used by launchd (LaunchDaemon) on Mac Mini for auto-start.
# Waits for Docker to be ready, then starts all services.

set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_PREFIX="[ai-governor]"

log() { echo "$LOG_PREFIX $(date '+%Y-%m-%d %H:%M:%S') $*"; }

log "Starting AI Governor from $PROJECT_DIR"

# Wait for Docker daemon
MAX_WAIT=120
WAITED=0
until docker info >/dev/null 2>&1; do
    if [ "$WAITED" -ge "$MAX_WAIT" ]; then
        log "ERROR: Docker not available after ${MAX_WAIT}s"
        exit 1
    fi
    log "Waiting for Docker... (${WAITED}s)"
    sleep 5
    WAITED=$((WAITED + 5))
done

log "Docker is ready"

cd "$PROJECT_DIR"
docker compose up -d

log "All services started"
