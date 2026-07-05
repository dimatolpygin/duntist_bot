"""Хендлер /start и заглушка кнопки «Новый заказ».

На этом этапе (каркас) кнопка только подтверждает нажатие. Полный сценарий приёма
заказа (предупреждение → файлы → завершение → карточка в группу) добавляется дальше.
"""
from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from .. import keyboards, texts
from ..logger import logger

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    u = message.from_user
    await message.answer(
        texts.START.format(name=escape(u.first_name or "друг")),
        reply_markup=keyboards.main_kb(),
    )
    logger.info(f"🤖 Бот → @{u.username or '—'}: приветствие + кнопка «Новый заказ»")


@router.callback_query(F.data == keyboards.NEW_ORDER_CALLBACK)
async def cb_new_order(callback: CallbackQuery) -> None:
    # Заглушка каркаса: сам сценарий сбора заказа реализуется на следующем этапе.
    await callback.answer("Сценарий приёма заказа появится на следующем этапе.", show_alert=True)
    logger.info(
        f"🤖 Бот → @{callback.from_user.username or '—'}: нажата «Новый заказ» (заглушка)"
    )
