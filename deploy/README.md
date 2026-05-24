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

### 4. Smoke-test

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

## Что дальше

После того как dev-окружение поднято и работает end-to-end → Phase 3 (CI/CD):
автоматическая сборка образов в GHCR, авто-pull + restart на VPS по push в main.

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

## Обновление кода (до подключения CI/CD)

```bash
cd ~/brainscan
git pull
cd deploy
docker compose -f docker-compose.deploy.yml build server worker migrate
docker compose -f docker-compose.deploy.yml --env-file .env up -d
# migrate сам прокатает новые миграции перед стартом server'а
```
