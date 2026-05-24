# BrainScan deployment (Phase 2 — dev на TimeWebCloud VPS)

Развёртывание server + worker на TimeWebCloud VPS, привязанному к managed Postgres
и Object Storage в приватной сети, с TLS через Let's Encrypt.

## Предусловия

- TimeWebCloud:
  - Managed PostgreSQL поднят, доступен в приватной сети, креды на руках.
  - Object Storage (S3) поднят, бакеты `brainscan-screenshots`, `brainscan-localize`,
    `brainscan-models` созданы, access/secret keys на руках.
  - VPS (рекоменд. 2 vCPU / 4 GB RAM / 40 GB SSD, Ubuntu 24.04 LTS) арендован
    в той же приватной сети, есть публичный IP.
- Домен: A-запись `dev-api.your-domain.com` → public IP VPS (TTL 5 мин на время
  настройки, потом можно увеличить).
- На рабочей машине: SSH-доступ к VPS (по ключу).

## Шаги

### 1. Подготовка VPS

```bash
ssh root@<VPS_IP>

# Базовый firewall + fail2ban
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
apt-get update && apt-get install -y fail2ban

# Docker (официальный install script)
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# Non-root deploy user
useradd -m -s /bin/bash -G docker brainscan
mkdir -p /home/brainscan/.ssh
cp ~/.ssh/authorized_keys /home/brainscan/.ssh/
chown -R brainscan:brainscan /home/brainscan/.ssh
chmod 700 /home/brainscan/.ssh
```

### 2. Клонирование репо и конфиг

```bash
su - brainscan
git clone git@github.com:IgorMikhailovDsgn/X-RAY.git brainscan
cd brainscan/deploy

cp .env.deploy.example .env
# Открыть в редакторе и заполнить:
#   - DATABASE_URL / ALEMBIC_DATABASE_URL — приватный endpoint TimeWebCloud Postgres
#   - JWT_SECRET — сгенерировать: openssl rand -hex 32
#   - S3_* — приватный endpoint TimeWebCloud Object Storage
#   - API_DOMAIN — поддомен из A-записи
#   - LETSENCRYPT_EMAIL — для уведомлений Let's Encrypt
nano .env
```

### 3. Сборка образов и старт

```bash
docker compose -f docker-compose.deploy.yml build
docker compose -f docker-compose.deploy.yml --env-file .env up -d
```

acme-companion увидит `LETSENCRYPT_HOST` у сервера и за ~30 секунд выпустит
сертификат через Let's Encrypt HTTP-01 challenge.

### 4. Поднять лимит body-size (для multi-monitor screenshot upload)

nginx-proxy по умолчанию режет тело запроса до 1MB → `/api/v1/screenshots` с
несколькими Retina-PNG сразу отдаёт 413. Кладём `client_max_body_size 50m;` в
`vhost.d/<DOMAIN>` (named volume `vhost` сохраняется между перезапусками):

```bash
docker exec brainscan_nginx sh -c \
  'cat > /etc/nginx/vhost.d/'"$API_DOMAIN"' <<EOF
client_max_body_size 50m;
EOF
nginx -s reload'
```
Повторять при добавлении новых доменов.

### 5. Smoke-test

```bash
# С локальной машины:
curl https://${API_DOMAIN}/api/v1/health
# → {"status":"ok","version":"0.1.0","db":"ok","storage":"ok"}
```

Логи на VPS:
```bash
docker compose -f docker-compose.deploy.yml logs -f server worker nginx-proxy
```

### 5. Подключение macOS клиента

В [client-macos/project.yml](../client-macos/project.yml) обновить Staging URL:
```yaml
Staging:
  BRAINSCAN_API_BASE_URL: https://dev-api.your-domain.com/api/v1
```
Пересобрать клиент в Staging-конфигурации, проверить sign-in + Annotate Send.

## CI/CD (Phase 3 — подключён)

Push в `main` → GH Actions:

1. `server-ci.yml` — ruff + mypy + pytest (Postgres service) на каждый PR/push.
2. `build-deploy.yml` — собирает `brainscan-server` и `brainscan-worker` в GHCR
   (`ghcr.io/igormikhailovdsgn/brainscan-{server,worker}:<sha>` + `:latest`),
   затем SSH'ится на VPS, тянет свежий `docker-compose.deploy.yml` с
   raw.githubusercontent.com, прописывает `IMAGE_TAG=<sha>` в `deploy/.env`,
   и делает `docker compose pull && up -d migrate && up -d server worker`.
   Финальный smoke — `curl https://dev-api.cfi-messenger.ru/api/v1/health`.

### Что нужно настроить в GitHub один раз

1. **GHCR-пакеты сделать публичными** (т.к. репа публичная):
   - GitHub → Profile → Packages → `brainscan-server` → Package settings →
     Change visibility → Public. Повторить для `brainscan-worker`. После
     этого `docker compose pull` на VPS не требует `docker login`.

2. **GitHub Secrets** (repo Settings → Secrets and variables → Actions):
   - `VPS_HOST` = `5.42.122.92`
   - `VPS_USER` = `brainscan`
   - `VPS_SSH_KEY` = содержимое приватного ключа из
     `~/.ssh/id_brainscan_gh_actions` (включая `-----BEGIN ... -----` строки).
     Публичная половина уже добавлена в `~brainscan/.ssh/authorized_keys` на VPS.
   - (опц.) `VPS_PORT` если SSH не на 22.

3. **GitHub Environment** `dev` (Settings → Environments → New environment):
   создать просто чтобы видеть deploy-history; protection rules не обязательны.

### Rollback

```bash
ssh brainscan-deploy
cd ~/brainscan/deploy
sed -i 's|^IMAGE_TAG=.*|IMAGE_TAG=<good-sha>|' .env
docker compose -f docker-compose.deploy.yml --env-file .env pull server worker
docker compose -f docker-compose.deploy.yml --env-file .env up -d --no-deps server worker
```

(SHA брать из истории GHCR-пакета — там видны все собранные теги.)

## MLflow tracking server (Phase 4 pre-work)

MLflow поднят на dev VPS под `https://mlflow.cfi-messenger.ru/` за nginx-proxy с
basic-auth. UI для просмотра экспериментов; API для GPU-воркеров (когда будут).

- **Image**: `brainscan/mlflow:2.19.0` — собирается из `mlflow.Dockerfile`
  локально на VPS (`docker compose build mlflow`). В GHCR не пушим — образ
  редко меняется, build занимает ~2 мин.
- **Backend store**: SQLite в named volume `mlflow_data` (`/mlflow/mlflow.db`).
  Single-writer достаточно для нашего сетапа (один-два GPU-воркера). Если
  упрёмся в производительность — мигрируем на managed Postgres.
- **Artifact store**: S3 (тот же бакет `46f4a57c-...`, prefix `mlflow/`).
  MLflow подписывает запросы через `AWS_ACCESS_KEY_ID`/`SECRET` env-vars.
- **Auth**: nginx-proxy basic-auth, файл в named volume `vhost-htpasswd`
  → `/etc/nginx/htpasswd/mlflow.cfi-messenger.ru`. Формат: `igor:$apr1$...`
  (APR1 hash через `openssl passwd -apr1`). Пароль лежит у Igor в Keychain.

### Bootstrap (выполнено один раз 2026-05-25)

```bash
# 1. A-запись mlflow.cfi-messenger.ru → 5.42.122.92 (dev VPS).
# 2. Доливаем env-vars в deploy/.env:
echo "MLFLOW_DOMAIN=mlflow.cfi-messenger.ru" >> ~/brainscan/deploy/.env
echo "MLFLOW_S3_PREFIX=mlflow/" >> ~/brainscan/deploy/.env
# 3. Собираем образ:
docker compose -f docker-compose.deploy.yml --env-file .env build mlflow
# 4. Поднимаем nginx-proxy с новым vhost-htpasswd volume + mlflow:
docker compose -f docker-compose.deploy.yml --env-file .env up -d --no-deps nginx-proxy mlflow
# 5. Кладём htpasswd-файл в volume и перезапускаем nginx, чтобы он подцепил auth:
PASS='<сгенерить openssl rand -base64 24>'
HASH=$(openssl passwd -apr1 "$PASS")
echo "igor:$HASH" | docker cp - brainscan_nginx:/etc/nginx/htpasswd/mlflow.cfi-messenger.ru
docker restart brainscan_nginx
# 6. Smoke:
curl -sS -o /dev/null -w "%{http_code}\n" https://mlflow.cfi-messenger.ru/             # 401
curl -sS -o /dev/null -w "%{http_code}\n" -u "igor:$PASS" https://mlflow.cfi-messenger.ru/  # 200
```

### Смена пароля

```bash
NEW_PASS='<новый>'
HASH=$(openssl passwd -apr1 "$NEW_PASS")
echo "igor:$HASH" | docker cp - brainscan_nginx:/etc/nginx/htpasswd/mlflow.cfi-messenger.ru
docker restart brainscan_nginx
```

## Что дальше

Phase 4 (продолжение) — queue split в `ml/workers/celery_app.py`, аренда GPU-инстанса.
Phase 6 — Prod (отложен).
Phase 7 — observability (structured logs, метрики).

## Troubleshooting

- **`Let's Encrypt rate limit`** — при тестировании удобно сначала использовать
  staging-CA: переменная `ACME_CA_URI=https://acme-staging-v02.api.letsencrypt.org/directory`
  на acme-companion. Сертификаты будут фейковые (untrusted в браузере), зато
  без лимитов. Убрать перед prod.
- **`502 Bad Gateway` от nginx-proxy** — server ещё не поднялся / не прошёл
  миграцию. `docker compose logs migrate server`.
- **`could not connect to server: Connection refused` в server-логах** — приватный
  endpoint Postgres недоступен из этой подсети. Проверить, что VPS в той же
  приватной сети, что и DB.

## Обновление кода вручную (fallback, обычно не нужно — есть CI/CD)

```bash
cd ~/brainscan/deploy
# Если поменялся compose:
curl -fsS -o docker-compose.deploy.yml \
  https://raw.githubusercontent.com/IgorMikhailovDsgn/X-RAY/main/deploy/docker-compose.deploy.yml
# Тянем latest или фиксируем конкретный SHA через IMAGE_TAG в .env.
docker compose -f docker-compose.deploy.yml --env-file .env pull
docker compose -f docker-compose.deploy.yml --env-file .env up -d migrate
docker compose -f docker-compose.deploy.yml --env-file .env up -d server worker
```
