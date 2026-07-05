#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# Установщик Telegram-бота приёма заказов «Город» на Ubuntu (Docker).
# Поднимает бот + свои Postgres и Redis в одном docker-compose.
# Использование:  bash install.sh
# ─────────────────────────────────────────────────────────────────────────────

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
prompt()  { read -rp "$(echo -e "${YELLOW}>>> $1: ${NC}")" "$2"; }
promptp() { read -rsp "$(echo -e "${YELLOW}>>> $1: ${NC}")" "$2"; echo; }

echo ""
echo "=========================================================="
echo "   Zarub Bot (приём заказов «Город») — установщик Ubuntu"
echo "=========================================================="
echo ""

# ── Сбор переменных ──────────────────────────────────────────────────────────
prompt  "Git репозиторий (https://github.com/...)" GIT_REPO
GIT_REPO=${GIT_REPO:-https://github.com/dimatolpygin/duntist_bot.git}

prompt  "Ветка для деплоя [master]" BRANCH
BRANCH=${BRANCH:-master}

prompt  "Каталог установки [/opt/zarub_bot]" INSTALL_DIR
INSTALL_DIR=${INSTALL_DIR:-/opt/zarub_bot}

promptp "BOT_TOKEN (от @BotFather)" BOT_TOKEN
prompt  "GROUP_ID (id закрытой группы «Город», напр. -1001234567890)" GROUP_ID
prompt  "ADMIN_IDS (id админов через запятую; можно оставить пустым)" ADMIN_IDS

echo ""
echo "S3 (Beget) — для больших файлов. Можно оставить пустыми на старте."
prompt  "S3_ENDPOINT" S3_ENDPOINT
prompt  "S3_REGION" S3_REGION
prompt  "S3_BUCKET" S3_BUCKET
prompt  "S3_ACCESS_KEY" S3_ACCESS_KEY
promptp "S3_SECRET_KEY" S3_SECRET_KEY
prompt  "S3_PUBLIC_BASE_URL" S3_PUBLIC_BASE_URL

# Пароль для встроенного Postgres генерируется автоматически.
POSTGRES_PASSWORD=$(openssl rand -hex 24)

echo ""
info "Начинаю установку..."

# ── Docker ───────────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  info "Устанавливаю Docker..."
  curl -fsSL https://get.docker.com | sh
fi
if ! docker compose version &>/dev/null; then
  error "Не найден плагин 'docker compose'. Установите docker-compose-plugin и повторите."
fi
info "Docker: $(docker --version)"

# ── git ──────────────────────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
  info "Устанавливаю git..."
  apt-get update -qq && apt-get install -y -qq git
fi

# ── Клонирование / обновление ────────────────────────────────────────────────
if [[ -d "$INSTALL_DIR/.git" ]]; then
  warn "Каталог уже существует — обновляю..."
  cd "$INSTALL_DIR"
  git fetch --all
  git checkout "$BRANCH"
  git reset --hard "origin/$BRANCH"
else
  info "Клонирую репозиторий ($BRANCH)..."
  git clone --branch "$BRANCH" "$GIT_REPO" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi

# ── .env ─────────────────────────────────────────────────────────────────────
# Если .env уже есть — сохраняем прежний пароль БД, чтобы не потерять доступ к данным.
if [[ -f .env ]] && grep -q '^POSTGRES_PASSWORD=' .env; then
  POSTGRES_PASSWORD=$(grep '^POSTGRES_PASSWORD=' .env | head -1 | cut -d= -f2-)
  warn "Использую существующий POSTGRES_PASSWORD из .env"
fi

info "Создаю .env..."
cat > .env <<ENVEOF
BOT_TOKEN=${BOT_TOKEN}
GROUP_ID=${GROUP_ID}
ADMIN_IDS=${ADMIN_IDS}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
DB_SCHEMA=zarub
S3_ENDPOINT=${S3_ENDPOINT}
S3_REGION=${S3_REGION}
S3_BUCKET=${S3_BUCKET}
S3_ACCESS_KEY=${S3_ACCESS_KEY}
S3_SECRET_KEY=${S3_SECRET_KEY}
S3_PUBLIC_BASE_URL=${S3_PUBLIC_BASE_URL}
LOG_LEVEL=INFO
ENVEOF
chmod 600 .env

# ── Запуск ───────────────────────────────────────────────────────────────────
info "Собираю и запускаю стек (бот + Postgres + Redis)..."
docker compose up -d --build

echo ""
echo "=========================================================="
info "Установка завершена!"
echo ""
echo "  Каталог:   ${INSTALL_DIR}"
echo "  Логи:      docker compose -f ${INSTALL_DIR}/docker-compose.yml logs -f bot"
echo "  Рестарт:   docker compose -f ${INSTALL_DIR}/docker-compose.yml restart"
echo "  Стоп:      docker compose -f ${INSTALL_DIR}/docker-compose.yml down"
echo ""
warn "Не забудьте добавить бота в группу «Город» (GROUP_ID=${GROUP_ID})!"
echo "=========================================================="
