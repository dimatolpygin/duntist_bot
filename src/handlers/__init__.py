"""Сбор всех роутеров."""
from aiogram import Router

from . import admin, order, start


def get_main_router() -> Router:
    router = Router()
    # start первым: /start сбрасывает FSM и должен срабатывать в любом состоянии.
    router.include_router(start.router)
    # admin раньше order: специфичные команды (/setvideo, /cancel в его состоянии).
    router.include_router(admin.router)
    router.include_router(order.router)
    return router
