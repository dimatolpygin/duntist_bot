"""Авто-досылка незавершённых заказов.

Клиент иногда присылает файлы и уходит, не нажав «Завершить заказ» — тогда файлы
зависают в FSM и не попадают в группу. Здесь это чинится так:

- каждый шаг незавершённого заказа (файл, переход к имени/количеству) «трогает»
  дедлайн в Redis — sorted set с deadline = now + TIMEOUT на пользователя;
- фоновый воркер раз в POLL_INTERVAL берёт всё, что просрочено, атомарно захватывает
  (ZREM) и досылает файлы в группу с пометкой «авто-отправка».

Индекс в Redis переживает перезапуск бота (в отличие от таймера в памяти).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import BaseStorage, StorageKey

from .. import repo, texts
from ..cache import get_redis
from ..logger import logger
from .delivery import send_order_to_group

# Простой клиента, после которого заказ досылается автоматически.
TIMEOUT_SECONDS = 10 * 60
# Как часто воркер проверяет просроченные заказы.
POLL_INTERVAL = 60

_ZSET_KEY = "pending_orders"


def _member(chat_id: int, uid: int) -> str:
    return f"{chat_id}:{uid}"


async def touch(chat_id: int, uid: int) -> None:
    """Продлевает дедлайн авто-досылки для незавершённого заказа пользователя."""
    deadline = time.time() + TIMEOUT_SECONDS
    await get_redis().zadd(_ZSET_KEY, {_member(chat_id, uid): deadline})


async def clear(chat_id: int, uid: int) -> None:
    """Убирает пользователя из индекса (заказ завершён/отменён штатно)."""
    await get_redis().zrem(_ZSET_KEY, _member(chat_id, uid))


async def run_worker(bot: Bot, storage: BaseStorage, pool: Any) -> None:
    """Бесконечный цикл: досылает заказы, простаивающие дольше TIMEOUT_SECONDS."""
    logger.info(f"🕒 Воркер авто-досылки запущен (таймаут {TIMEOUT_SECONDS // 60} мин)")
    redis = get_redis()
    while True:
        try:
            now = time.time()
            due = await redis.zrangebyscore(_ZSET_KEY, 0, now)
            for member in due:
                # Атомарный «захват»: только тот, чей ZREM вернул 1, обрабатывает заказ.
                if not await redis.zrem(_ZSET_KEY, member):
                    continue
                try:
                    chat_id_s, uid_s = member.split(":")
                    await _finalize(bot, storage, pool, int(chat_id_s), int(uid_s))
                except Exception:
                    logger.exception(f"❌ Авто-досылка заказа ({member}) не удалась")
        except Exception:
            logger.exception("❌ Ошибка в цикле воркера авто-досылки")
        await asyncio.sleep(POLL_INTERVAL)


async def _finalize(
    bot: Bot, storage: BaseStorage, pool: Any, chat_id: int, uid: int
) -> None:
    """Создаёт авто-заказ из накопленных в FSM файлов и досылает его в группу."""
    key = StorageKey(bot_id=bot.id, chat_id=chat_id, user_id=uid)
    ctx = FSMContext(storage=storage, key=key)

    # Заказ уже завершён/отменён (FSM очищен) — досылать нечего.
    if await ctx.get_state() is None:
        return
    data = await ctx.get_data()
    files: list[dict[str, Any]] = data.get("files", [])
    if not files:
        await ctx.clear()
        return

    order_id = await repo.create_order(
        pool,
        tg_id=data.get("sender_tg_id", uid),
        username=data.get("sender_username"),
        first_name=data.get("sender_first_name"),
        client_name=data.get("client_name"),  # мог успеть ввести имя
        quantity=None,
        files=files,
        is_auto=True,
    )
    await ctx.clear()
    logger.info(
        f"🕒 Авто-заказ №{order_id} собран по таймауту "
        f"(@{data.get('sender_username') or '—'}, id:{uid}, файлов {len(files)})"
    )

    await send_order_to_group(bot, pool, order_id)

    # Уведомляем клиента, что файлы всё же ушли в работу.
    try:
        await bot.send_message(chat_id, texts.ORDER_AUTO_SENT)
    except Exception:
        logger.exception(f"Не удалось уведомить клиента id:{uid} об авто-отправке")
