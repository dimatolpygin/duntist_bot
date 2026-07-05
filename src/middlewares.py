"""Middleware сквозного логирования действий пользователей (для отладки в терминале)."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from .logger import logger


class LoggingMiddleware(BaseMiddleware):
    """Логирует каждое входящее сообщение и нажатие inline-кнопки."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        update: Update = event  # type: ignore[assignment]

        if update.message is not None:
            self._log_message(update.message)
        elif update.callback_query is not None:
            self._log_callback(update.callback_query)

        return await handler(event, data)

    @staticmethod
    def _describe(msg: Message) -> str:
        """Короткое человекочитаемое описание содержимого сообщения."""
        if msg.document is not None:
            return f"(документ: {msg.document.file_name})"
        if msg.photo:
            return "(фото)"
        if msg.video is not None:
            return f"(видео: {msg.video.file_name or ''})"
        if msg.audio is not None:
            return f"(аудио: {msg.audio.file_name or ''})"
        if msg.voice is not None:
            return "(голосовое)"
        if msg.video_note is not None:
            return "(видео-кружок)"
        if msg.animation is not None:
            return "(gif)"
        return msg.text or "(медиа)"

    @classmethod
    def _log_message(cls, msg: Message) -> None:
        u = msg.from_user
        if u is None:
            return
        logger.info(
            f"👤 @{u.username or '—'} (id:{u.id}, {u.first_name}) → {cls._describe(msg)}"
        )

    @staticmethod
    def _log_callback(cb: CallbackQuery) -> None:
        u = cb.from_user
        logger.info(
            f"👤 @{u.username or '—'} (id:{u.id}, {u.first_name}) → [кнопка] {cb.data}"
        )
