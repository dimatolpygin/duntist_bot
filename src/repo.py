"""Доступ к данным (repository). Тонкая обёртка над SQL-запросами."""
from __future__ import annotations

from typing import Any

import asyncpg


async def create_order(
    pool: asyncpg.Pool,
    *,
    tg_id: int,
    username: str | None,
    first_name: str | None,
    client_name: str,
    quantity: str,
    files: list[dict[str, Any]],
) -> int:
    """Создаёт завершённый заказ и привязанные к нему файлы одной транзакцией.

    Возвращает номер заказа (orders.id).
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            order_id: int = await conn.fetchval(
                """
                INSERT INTO orders
                    (tg_id, username, first_name, client_name, quantity, status, completed_at)
                VALUES ($1, $2, $3, $4, $5, 'completed', now())
                RETURNING id
                """,
                tg_id, username, first_name, client_name, quantity,
            )
            for f in files:
                await conn.execute(
                    """
                    INSERT INTO order_files
                        (order_id, file_id, file_unique_id, file_type,
                         file_name, mime_type, file_size)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    order_id,
                    f["file_id"],
                    f.get("file_unique_id"),
                    f["file_type"],
                    f.get("file_name"),
                    f.get("mime_type"),
                    f.get("file_size"),
                )
    return order_id


async def get_order(pool: asyncpg.Pool, order_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow("SELECT * FROM orders WHERE id = $1", order_id)


async def get_order_files(pool: asyncpg.Pool, order_id: int) -> list[asyncpg.Record]:
    return await pool.fetch(
        "SELECT * FROM order_files WHERE order_id = $1 ORDER BY id", order_id
    )


# ─────────────────────────── Видео-инструкция ───────────────────────────

async def get_instruction_video(pool: asyncpg.Pool) -> asyncpg.Record | None:
    return await pool.fetchrow("SELECT * FROM instruction_video WHERE id = 1")


async def set_instruction_video(
    pool: asyncpg.Pool,
    *,
    file_id: str,
    is_video: bool,
    caption: str | None,
    updated_by: int,
) -> None:
    """Задаёт/заменяет видео-инструкцию (singleton, id = 1)."""
    await pool.execute(
        """
        INSERT INTO instruction_video (id, file_id, is_video, caption, updated_at, updated_by)
        VALUES (1, $1, $2, $3, now(), $4)
        ON CONFLICT (id) DO UPDATE
            SET file_id = EXCLUDED.file_id,
                is_video = EXCLUDED.is_video,
                caption = EXCLUDED.caption,
                updated_at = now(),
                updated_by = EXCLUDED.updated_by
        """,
        file_id, is_video, caption, updated_by,
    )
