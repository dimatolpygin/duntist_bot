"""Доставка заказа в закрытую группу «Город»: карточка + все файлы.

Файлы пересылаются по сохранённому Telegram file_id (без повторной загрузки),
поэтому копия уходит в группу мгновенно. Обработка файлов сверх лимита 50 МБ —
отдельный этап; здесь используется прямая отправка по file_id.
"""
from __future__ import annotations

from html import escape

import asyncpg
from aiogram import Bot

from . import s3
from .. import repo, texts
from ..config import settings
from ..logger import logger

# Bot API отдаёт файлы для скачивания ботом только до ~20 МБ (getFile).
# Больше — скачать для заливки в S3 нельзя (нужен локальный Bot API сервер, вне базовой версии).
_BOT_DOWNLOAD_LIMIT = 20 * 1024 * 1024


def _human_size(size: int | None) -> str:
    if not size:
        return "неизвестно"
    val = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if val < 1024 or unit == "ГБ":
            return f"{val:.0f} {unit}" if unit == "Б" else f"{val:.1f} {unit}"
        val /= 1024
    return f"{size} Б"


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
        if order["is_auto"]:
            card = texts.GROUP_ORDER_CARD_AUTO_NOTE + card
        await bot.send_message(chat_id, card)
    except Exception:
        logger.exception(f"❌ Не удалось отправить карточку заказа №{order_id} в группу {chat_id}")
        return False

    sent = 0
    for f in files:
        if await _deliver_file(bot, chat_id, order_id, f):
            sent += 1

    logger.info(
        f"📨 Заказ №{order_id} отправлен в группу «Город» ({chat_id}): "
        f"карточка + {sent}/{len(files)} файлов"
    )
    return sent == len(files)


async def _deliver_file(bot: Bot, chat_id: int, order_id: int, f: asyncpg.Record) -> bool:
    """Отправляет файл в группу. Сначала прямая пересылка по file_id (обходит лимит
    50 МБ). Если не прошла — пробует S3-fallback, иначе кладёт заметку для оператора."""
    try:
        await _send_file(bot, chat_id, f)
        return True
    except Exception:
        logger.exception(
            f"⚠️ Прямая отправка файла заказа №{order_id} не прошла, пробую fallback "
            f"(тип={f['file_type']}, имя={f['file_name']}, размер={f['file_size']})"
        )
        return await _fallback_file(bot, chat_id, order_id, f)


async def _fallback_file(bot: Bot, chat_id: int, order_id: int, f: asyncpg.Record) -> bool:
    """Fallback для файла, который не удалось переслать напрямую.

    Работает только для файлов ≤20 МБ (ограничение getFile у Bot API): скачивает файл,
    заливает в S3 и шлёт ссылку. Иначе — заметка оператору связаться с отправителем.
    """
    name = f["file_name"] or f["file_type"]
    size = f["file_size"] or 0

    can_download = s3.is_configured() and (0 < size <= _BOT_DOWNLOAD_LIMIT)
    if can_download:
        try:
            tg_file = await bot.get_file(f["file_id"])
            buf = await bot.download_file(tg_file.file_path)
            data = buf.read()
            key = f"orders/{order_id}/{f['file_unique_id'] or f['file_id']}_{name}"
            url = await s3.upload_bytes(key, data, f["mime_type"])
            await bot.send_message(
                chat_id,
                texts.GROUP_FILE_S3_LINK.format(
                    id=order_id, name=escape(name), size=_human_size(size), url=url
                ),
            )
            return True
        except Exception:
            logger.exception(f"❌ S3-fallback файла заказа №{order_id} не удался")

    # Ни переслать, ни залить не вышло — оставляем заметку оператору.
    await bot.send_message(
        chat_id,
        texts.GROUP_FILE_FAILED.format(
            id=order_id, name=escape(name), size=_human_size(size)
        ),
    )
    return False
