"""Админские хендлеры: установка видео-инструкции (/setvideo)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from aiogram.utils.text_decorations import html_decoration
import asyncpg

from .. import repo, texts
from ..config import settings
from ..logger import logger

router = Router()


class AdminFilter(BaseFilter):
    """Пропускает только пользователей из ADMIN_IDS."""

    async def __call__(self, message: Message) -> bool:
        return (
            message.from_user is not None
            and message.from_user.id in settings.admin_id_list
        )


class SetVideo(StatesGroup):
    waiting_for_video = State()


@router.message(Command("setvideo"), AdminFilter())
async def cmd_setvideo(message: Message, state: FSMContext) -> None:
    await state.set_state(SetVideo.waiting_for_video)
    await message.answer(texts.ADMIN_SETVIDEO_PROMPT)
    logger.info(f"🛠 Админ id={message.from_user.id} начал установку видео-инструкции")


# Не-админ — мягкий отказ.
@router.message(Command("setvideo"))
async def cmd_setvideo_denied(message: Message) -> None:
    await message.answer(texts.ADMIN_ONLY)


@router.message(Command("cancel"), StateFilter(SetVideo.waiting_for_video))
async def cmd_cancel_setvideo(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.ADMIN_CANCELLED)


@router.message(StateFilter(SetVideo.waiting_for_video), F.video | F.document | F.animation)
async def receive_video(message: Message, state: FSMContext, pool: asyncpg.Pool) -> None:
    # Принимаем видео; допускаем и документ (вдруг админ пришлёт видео файлом).
    if message.video is not None:
        file_id, is_video = message.video.file_id, True
    elif message.animation is not None:
        file_id, is_video = message.animation.file_id, True
    else:  # document
        file_id, is_video = message.document.file_id, False

    caption_html = (
        html_decoration.unparse(message.caption, message.caption_entities or [])
        if message.caption
        else None
    )

    await repo.set_instruction_video(
        pool,
        file_id=file_id,
        is_video=is_video,
        caption=caption_html,
        updated_by=message.from_user.id,
    )
    await state.clear()
    await message.answer(texts.ADMIN_SETVIDEO_OK)
    logger.info(
        f"🛠 Видео-инструкция обновлена (file_id={file_id}, is_video={is_video}) "
        f"админом id={message.from_user.id}"
    )


# В состоянии ожидания пришло что-то не то.
@router.message(StateFilter(SetVideo.waiting_for_video))
async def receive_not_video(message: Message) -> None:
    await message.answer(texts.ADMIN_SETVIDEO_NOT_VIDEO)
