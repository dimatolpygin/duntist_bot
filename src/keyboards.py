"""Inline-клавиатуры."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# callback_data кнопок сценария заказа.
NEW_ORDER_CALLBACK = "new_order"
FINISH_ORDER_CALLBACK = "finish_order"


def main_kb() -> InlineKeyboardMarkup:
    """Стартовая клавиатура: кнопка «Новый заказ»."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📦 Новый заказ", callback_data=NEW_ORDER_CALLBACK)
    return builder.as_markup()
