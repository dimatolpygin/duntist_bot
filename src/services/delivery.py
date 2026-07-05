"""Доставка заказа в закрытую группу «Город»: карточка + все файлы.

Файлы пересылаются по сохранённому Telegram file_id (без повторной загрузки),
поэтому копия уходит в группу мгновенно. Обработка файлов сверх лимита 50 МБ —
отдельный этап; здесь используется прямая отправка по file_id.
"""
from __future__ import annotations

from html import escape

import asyncpg
from aiogram import Bot

from .. import repo, texts
from ..config import settings
from ..logger import logger


def _author(order: asyncpg.Record) -> str:
    """Читаемая подпись отправителя (техника) для карточки: ник + имя + user_id."""
    uid = order["tg_id"]
    username = f"@{escape(order['username'])}" if order["username"] else None
    name = escape(order["first_name"]) if order["first_name"] else None

    if username and name:
        return f"{username} ({name}, id {uid})"
    if username:
        return f"{username} (id {uid})"
    if name:
        return f"{name} (id {uid})"
    return f"id {uid}"


async def _send_file(bot: Bot, chat_id: int, f: asyncpg.Record) -> None:
    """Отправляет один файл в группу по его типу и file_id."""
    ftype = f["file_type"]
    fid = f["file_id"]
    if ftype == "photo":
        await bot.send_photo(chat_id, fid)
    elif ftype == "video":
        await bot.send_video(chat_id, fid)
    elif ftype == "audio":
        await bot.send_audio(chat_id, fid)
    elif ftype == "voice":
        await bot.send_voice(chat_id, fid)
    elif ftype == "animation":
        await bot.send_animation(chat_id, fid)
    elif ftype == "video_note":
        await bot.send_video_note(chat_id, fid)
    else:  # document и всё прочее — как документ
        await bot.send_document(chat_id, fid)


async def send_order_to_group(bot: Bot, pool: asyncpg.Pool, order_id: int) -> bool:
    """Отправляет карточку заказа и все его файлы в группу «Город».

    Возвращает True при успехе. Ошибки не пробрасываются наружу (заказ уже сохранён
    и принят у клиента) — они логируются, чтобы не ломать пользовательский поток.
    """
    chat_id = settings.group_chat_id
    order = await repo.get_order(pool, order_id)
    if order is None:
        logger.error(f"Доставка заказа №{order_id}: заказ не найден в БД")
        return False
    files = await repo.get_order_files(pool, order_id)

    try:
        card = texts.GROUP_ORDER_CARD.format(
            id=order_id,
            client=escape(order["client_name"] or "—"),
            quantity=escape(order["quantity"] or "—"),
            count=len(files),
            author=_author(order),
        )
        await bot.send_message(chat_id, card)
    except Exception:
        logger.exception(f"❌ Не удалось отправить карточку заказа №{order_id} в группу {chat_id}")
        return False

    sent = 0
    for f in files:
        try:
            await _send_file(bot, chat_id, f)
            sent += 1
        except Exception:
            logger.exception(
                f"❌ Файл заказа №{order_id} не отправлен в группу "
                f"(тип={f['file_type']}, имя={f['file_name']})"
            )

    logger.info(
        f"📨 Заказ №{order_id} отправлен в группу «Город» ({chat_id}): "
        f"карточка + {sent}/{len(files)} файлов"
    )
    return sent == len(files)
