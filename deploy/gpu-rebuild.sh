#!/usr/bin/env bash
# Локальная пересборка/перезапуск brainscan-worker-gpu на самом GPU-боксе.
#
# Запускается:
#   * руками, после SSH'а на бокс (`bash deploy/gpu-rebuild.sh`);
#   * автоматически из `.github/workflows/gpu-deploy.yml` (workflow_dispatch).
#
# Скрипт идемпотентен: повторный запуск перетягивает свежий main, чистит
# dangling-layers с прошлых сборок (главная причина "no space left on device"),
# пересобирает образ и перезапускает worker.
#
# Использование:
#   bash deploy/gpu-rebuild.sh [git_ref]
#
# Переменные окружения:
#   REPO_DIR    — путь к клону репо (default: /home/brainscan/brainscan).
#   ENV_FILE    — путь к .env.gpu (default: <REPO_DIR>/deploy/.env.gpu).
#   MIN_FREE_GB — минимум свободного диска до сборки (default: 10).

set -euo pipefail

GIT_REF="${1:-main}"
REPO_DIR="${REPO_DIR:-/home/brainscan/brainscan}"
COMPOSE_FILE="$REPO_DIR/deploy/docker-compose.gpu.yml"
ENV_FILE="${ENV_FILE:-$REPO_DIR/deploy/.env.gpu}"
MIN_FREE_GB="${MIN_FREE_GB:-10}"

log() { printf '[%(%H:%M:%S)T] %s\n' -1 "$*"; }

require() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required binary: $1" >&2
    exit 1
  fi
}

require docker
require git

[ -d "$REPO_DIR" ] || { echo "REPO_DIR not found: $REPO_DIR" >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "ENV_FILE not found: $ENV_FILE" >&2; exit 1; }

log "fetching $GIT_REF"
cd "$REPO_DIR"
git fetch --quiet origin
git checkout --quiet "$GIT_REF"
git pull --quiet origin "$GIT_REF"
log "checked out $(git rev-parse --short HEAD): $(git log -1 --pretty=%s)"

# Главный источник "no space left on device" — накопленные builder-копии после
# предыдущих сборок (каждая брайнсканная сборка ~6-7 GB dangling-слоёв).
log "pruning dangling images"
docker image prune -f >/dev/null

FREE_GB=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
log "free disk: ${FREE_GB}G"
if [ "$FREE_GB" -lt "$MIN_FREE_GB" ]; then
  echo "free disk ${FREE_GB}G < ${MIN_FREE_GB}G — abort." >&2
  echo "free more with: docker image prune -af && docker builder prune -af" >&2
  exit 2
fi

cd "$REPO_DIR/deploy"

log "building worker-gpu"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" build worker-gpu

log "restarting worker-gpu"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d worker-gpu

# Дать Celery 8 сек чтобы успеть подписаться на gpu-очередь.
sleep 8

log "smoke: worker consuming 'gpu' queue?"
if docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T worker-gpu \
    celery -A workers.celery_app inspect active_queues 2>&1 | grep -q "'name': 'gpu'"; then
  log "OK — worker is up and consuming gpu queue"
else
  echo "worker not consuming gpu queue, recent logs:" >&2
  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" logs --tail=40 worker-gpu >&2
  exit 3
fi

# Финальная сводка размеров — Igor любит видеть прирост/убыль.
log "image inventory:"
docker images --format '  {{.Repository}}:{{.Tag}} {{.Size}}' \
  | grep -E "brainscan-worker-gpu|python:3.12-slim"
log "disk: $(df -h / | tail -1 | awk '{print $3"/"$2" used"}')"
