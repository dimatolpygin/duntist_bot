"""Простейший мигратор: автоматически применяет .sql-файлы из папки migrations/ при старте."""
from __future__ import annotations

from pathlib import Path

import asyncpg

from .config import settings
from .logger import logger

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


async def apply_migrations(pool: asyncpg.Pool) -> None:
    """Создаёт схему (если нет), таблицу учёта миграций и применяет новые .sql-файлы по порядку."""
    schema = settings.db_schema

    async with pool.acquire() as conn:
        # Схема под этот бот. IF NOT EXISTS — существующие данные не затрагиваются.
        await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        await conn.execute(
            f'''
            CREATE TABLE IF NOT EXISTS "{schema}".schema_migrations (
                name        TEXT PRIMARY KEY,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            '''
        )

        applied = {
            row["name"]
            for row in await conn.fetch(f'SELECT name FROM "{schema}".schema_migrations')
        }

        files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        if not files:
            logger.warning("Папка migrations пуста — нечего применять")
            return

        new_count = 0
        for path in files:
            if path.name in applied:
                continue
            sql = path.read_text(encoding="utf-8")
            logger.info(f"⏳ Применяю миграцию: {path.name}")
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    f'INSERT INTO "{schema}".schema_migrations(name) VALUES($1)',
                    path.name,
                )
            new_count += 1

        if new_count:
            logger.info(f"✅ Применено новых миграций: {new_count}")
        else:
            logger.info("✅ Миграции в актуальном состоянии")
