# Деплой и эксплуатация

Бот развёрнут в Docker на Ubuntu-сервере. Автодеплой — через GitHub Actions по пушу в `master`.

## Инфраструктура

- **Сервер**: `45.88.14.4`, SSH-порт **`39066`**, пользователь `root`.
- **Каталог**: `/opt/zarub_bot`.
- **Репозиторий**: `github.com/dimatolpygin/duntist_bot` (публичный).
- **Стек** (docker-compose): `bot` + `postgres:16` + `redis:7`, все с `restart: unless-stopped`.
  Данные БД и Redis — в именованных томах, переживают перезапуск.

## Автодеплой (CI/CD)

Workflow `.github/workflows/deploy.yml`: пуш в `master` → GitHub Actions заходит по SSH →
`git reset --hard origin/master` → `docker compose up -d --build`.

### GitHub Secrets (репозиторий → Settings → Secrets and variables → Actions)

| Secret | Значение |
|--------|----------|
| `SERVER_HOST` | `45.88.14.4` |
| `SERVER_USER` | `root` |
| `SERVER_PORT` | `39066` |
| `SSH_PRIVATE_KEY` | приватный deploy-ключ целиком (`.secrets/deploy_key`, с BEGIN/END) |
| `INSTALL_DIR` | `/opt/zarub_bot` |

Deploy-ключ (ed25519) сгенерирован в `.secrets/deploy_key(.pub)` (gitignored). Публичная часть
добавлена в `~/.ssh/authorized_keys` на сервере.

## Установка с нуля (ручная, на чистом сервере)

Скрипт `scripts/install.sh` ставит Docker/git (если нет), клонирует репо, спрашивает переменные,
создаёт `.env` и поднимает стек. Пароль Postgres генерируется автоматически (при повторном запуске
сохраняется из существующего `.env`).

```bash
ssh -p 39066 root@45.88.14.4
curl -fsSL https://raw.githubusercontent.com/dimatolpygin/duntist_bot/master/scripts/install.sh -o install.sh
bash install.sh
```

Скрипт спросит: репозиторий (Enter — по умолчанию), ветку (`master`), каталог (`/opt/zarub_bot`),
`BOT_TOKEN`, `GROUP_ID`, `ADMIN_IDS`, S3-доступы.

## Переменные окружения (`.env` на сервере)

| Переменная | Назначение |
|------------|-----------|
| `BOT_TOKEN` | токен бота от @BotFather |
| `GROUP_ID` | id закрытой группы «Город» (бот должен быть в ней) |
| `ADMIN_IDS` | id админов через запятую (кому доступна `/setvideo`) |
| `POSTGRES_PASSWORD` | пароль встроенного Postgres (генерируется install.sh) |
| `DB_SCHEMA` | `zarub` (отдельная схема) |
| `S3_*` | доступы Beget S3 (для больших файлов) |
| `LOG_LEVEL` | `INFO` |

`DATABASE_URL` и `REDIS_URL` подставляет сам docker-compose — в `.env` их не задают.

## Переключение на боевого бота

Сейчас на сервере — тестовый бот. Для перехода на боевой `@LSP_dantist_bot`:

```bash
ssh -p 39066 root@45.88.14.4
cd /opt/zarub_bot
nano .env          # заменить BOT_TOKEN и GROUP_ID на боевые
docker compose up -d   # перезапустить бота с новым .env
```

После этого:
1. Добавить боевого бота в группу «Город».
2. Владельцу один раз выполнить `/setvideo` и прислать видео-инструкцию (file_id привязан к боту).

## Эксплуатация

```bash
cd /opt/zarub_bot
docker compose logs -f bot        # логи бота
docker compose ps                 # статус контейнеров
docker compose restart bot        # перезапуск
docker compose up -d --build      # пересобрать и поднять (после ручных правок)
docker compose down               # остановить всё (данные в томах сохранятся)
```

## Локальная разработка

```bash
docker compose -p zarub_bot -f docker-compose.dev.yml up --build
```

Явный `-p zarub_bot` нужен на Windows из-за кириллического имени папки. Локально используется
**тестовый** токен — на сервере крутится другой инстанс; нельзя держать два поллера на одном токене.
