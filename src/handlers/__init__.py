"""Сбор всех роутеров."""
from aiogram import Router

from . import order, start


def get_main_router() -> Router:
    router = Router()
    # start первым: /start сбрасывает FSM и должен срабатывать в любом состоянии.
    router.include_router(start.router)
    router.include_router(order.router)
    return router
