"""Точка входа: инициализация БД/Redis, миграции, запуск бота (polling)."""
from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand

from . import __version__
from .cache import close_redis, init_redis
from .config import settings
from .db import close_pool, init_pool
from .handlers import get_main_router
from .logger import setup_logging
from .middlewares import LoggingMiddleware
from .migrator import apply_migrations


async def main() -> None:
    log = setup_logging(settings.log_level)
    log.info(f"⏳ Запуск бота приёма заказов (v{__version__})...")

    # Инфраструктура.
    pool = await init_pool()
    await apply_migrations(pool)
    redis = await init_redis()

    # Бот и диспетчер. FSM-состояния сценария заказа храним в Redis.
    # parse_mode=HTML включён глобально; динамические значения (имена, описания)
    # экранируются в HTML перед подстановкой.
    storage = RedisStorage.from_url(settings.redis_url)
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=storage)

    # Зависимости, доступные во всех хендлерах как аргументы pool / redis.
    dp["pool"] = pool
    dp["redis"] = redis

    dp.update.middleware(LoggingMiddleware())
    dp.include_router(get_main_router())

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        # Команды в меню слева (кнопка «Меню» рядом с полем ввода).
        await bot.set_my_commands([
            BotCommand(command="start", description="начать"),
        ])
        me = await bot.get_me()
        log.info(f"✅ Бот @{me.username} запущен (режим: polling)")
        log.info(f"📨 Группа «Город» для карточек заказов: {settings.group_id}")
        await dp.start_polling(bot)
    finally:
        log.info("Останавливаю бота...")
        await close_redis()
        await close_pool()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
