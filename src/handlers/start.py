"""Хендлер /start."""
from __future__ import annotations

from html import escape

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from .. import keyboards, texts
from ..config import settings
from ..logger import logger

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    # /start сбрасывает незавершённый сценарий — пользователь всегда может начать заново.
    await state.clear()
    u = message.from_user
    await message.answer(
        texts.start_message(settings.bot_variant).format(name=escape(u.first_name or "друг")),
        reply_markup=keyboards.main_kb(),
    )
    logger.info(f"🤖 Бот → @{u.username or '—'}: приветствие + кнопка «Новый заказ»")
