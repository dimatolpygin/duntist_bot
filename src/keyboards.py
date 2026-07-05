"""Inline-клавиатуры."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# callback_data кнопок сценария заказа.
NEW_ORDER_CALLBACK = "new_order"
FINISH_ORDER_CALLBACK = "finish_order"
CANCEL_ORDER_CALLBACK = "cancel_order"


def main_kb() -> InlineKeyboardMarkup:
    """Стартовая клавиатура: кнопка «Новый заказ»."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📦 Новый заказ", callback_data=NEW_ORDER_CALLBACK)
    return builder.as_markup()


def collecting_kb() -> InlineKeyboardMarkup:
    """Клавиатура во время приёма файлов: завершить или отменить."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Завершить заказ", callback_data=FINISH_ORDER_CALLBACK)
    builder.button(text="✖️ Отменить", callback_data=CANCEL_ORDER_CALLBACK)
    builder.adjust(1)
    return builder.as_markup()
