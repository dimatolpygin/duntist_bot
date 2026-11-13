"""Подготовка второго экземпляра без Telegram и без запуска polling.

Запуск: python -m src.prepare_second (в контейнере bot_second).
Создаёт только схему zarub_second; первый бот продолжает работать.
"""
from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from .config import settings
from .db import close_pool, init_pool
from .cache import close_redis, init_redis
from .logger import setup_logging
from .migrator import apply_migrations


def validate_isolation() -> None:
    if settings.bot_variant != "second" or settings.db_schema != "zarub_second":
        raise ValueError("Подготовка разрешена только для схемы zarub_second и BOT_VARIANT=second")
    if urlparse(settings.redis_url).path != "/1":
        raise ValueError("Второму боту требуется отдельная Redis-база /1")
    if settings.s3_key_prefix.strip("/") != "orders-second":
        raise ValueError("Второму боту требуется отдельный S3-префикс orders-second")


async def main() -> None:
    setup_logging(settings.log_level)
    validate_isolation()
    try:
        pool = await init_pool()
        await apply_migrations(pool)
        redis = await init_redis()
        await redis.ping()
        tables = await pool.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = $1 ORDER BY tablename",
            settings.db_schema,
        )
        expected = {"orders", "order_files", "instruction_video", "schema_migrations"}
        if {row["tablename"] for row in tables} != expected:
            raise RuntimeError("Набор таблиц второго бота не соответствует ожидаемому")
        print("SECOND_READY: схема zarub_second, 4 таблицы, Redis /1; polling не запускался")
        missing = [name for name, value in (
            ("BOT_TOKEN", settings.bot_token), ("GROUP_ID", settings.group_id)
        ) if not value.strip()]
        print("Осталось заполнить: " + (", ".join(missing) or "доступы уже заполнены"))
    finally:
        await close_redis()
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
