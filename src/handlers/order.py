"""Сценарий приёма заказа (FSM).

Поток:
  «Новый заказ» → предупреждение → сбор файлов → «Завершить заказ»
  → имя клиента → количество/описание → «Заказ принят» (запись в БД).

Состояния и накопленные файлы хранятся в Redis (FSM-хранилище aiogram).
"""
from __future__ import annotations

from html import escape
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter
from aiogram.types import CallbackQuery, Message
import asyncpg

from .. import keyboards, repo, texts
from ..logger import logger

router = Router()


class OrderFlow(StatesGroup):
    collecting = State()          # приём файлов
    waiting_client_name = State() # ждём имя клиента
    waiting_quantity = State()    # ждём количество/описание


def _extract_file(message: Message) -> dict[str, Any] | None:
    """Достаёт из сообщения информацию о файле любого поддерживаемого типа.

    Возвращает dict с полями для order_files либо None, если файла нет.
    """
    if message.document is not None:
        d = message.document
        return {
            "file_id": d.file_id, "file_unique_id": d.file_unique_id,
            "file_type": "document", "file_name": d.file_name,
            "mime_type": d.mime_type, "file_size": d.file_size,
        }
    if message.photo:
        p = message.photo[-1]  # самое большое разрешение
        return {
            "file_id": p.file_id, "file_unique_id": p.file_unique_id,
            "file_type": "photo", "file_name": None,
            "mime_type": None, "file_size": p.file_size,
        }
    if message.video is not None:
        v = message.video
        return {
            "file_id": v.file_id, "file_unique_id": v.file_unique_id,
            "file_type": "video", "file_name": v.file_name,
            "mime_type": v.mime_type, "file_size": v.file_size,
        }
    if message.audio is not None:
        a = message.audio
        return {
            "file_id": a.file_id, "file_unique_id": a.file_unique_id,
            "file_type": "audio", "file_name": a.file_name,
            "mime_type": a.mime_type, "file_size": a.file_size,
        }
    if message.voice is not None:
        v = message.voice
        return {
            "file_id": v.file_id, "file_unique_id": v.file_unique_id,
            "file_type": "voice", "file_name": None,
            "mime_type": v.mime_type, "file_size": v.file_size,
        }
    if message.animation is not None:
        a = message.animation
        return {
            "file_id": a.file_id, "file_unique_id": a.file_unique_id,
            "file_type": "animation", "file_name": a.file_name,
            "mime_type": a.mime_type, "file_size": a.file_size,
        }
    if message.video_note is not None:
        v = message.video_note
        return {
            "file_id": v.file_id, "file_unique_id": v.file_unique_id,
            "file_type": "video_note", "file_name": None,
            "mime_type": None, "file_size": v.file_size,
        }
    return None


# ─────────────────────────── Старт сценария ───────────────────────────

@router.callback_query(F.data == keyboards.NEW_ORDER_CALLBACK)
async def cb_new_order(callback: CallbackQuery, state: FSMContext) -> None:
    """«Новый заказ»: показать предупреждение и начать приём файлов."""
    await state.clear()
    await state.set_state(OrderFlow.collecting)
    await state.update_data(files=[])

    # Кнопки «Завершить/Отменить» здесь НЕ показываем — они появятся по мере загрузки файлов.
    await callback.message.answer(texts.ORDER_WARNING)
    await callback.answer()
    logger.info(
        f"🤖 Бот → @{callback.from_user.username or '—'}: показано предупреждение, старт приёма файлов"
    )


# ─────────────────────────── Приём файлов ───────────────────────────

_FILE_FILTER = (
    F.document | F.photo | F.video | F.audio | F.voice | F.animation | F.video_note
)


@router.message(StateFilter(OrderFlow.collecting), _FILE_FILTER)
async def on_file(message: Message, state: FSMContext) -> None:
    file = _extract_file(message)
    if file is None:  # на всякий случай
        await message.answer(texts.NOT_A_FILE, reply_markup=keyboards.collecting_kb())
        return

    data = await state.get_data()
    files: list[dict[str, Any]] = data.get("files", [])
    files.append(file)
    await state.update_data(files=files)

    await message.answer(
        texts.FILE_ADDED.format(count=len(files)),
        reply_markup=keyboards.collecting_kb(),
    )
    logger.info(
        f"📎 Заказ (сбор) @{message.from_user.username or '—'} (id:{message.from_user.id}): "
        f"файл #{len(files)} тип={file['file_type']} имя={file.get('file_name')} "
        f"размер={file.get('file_size')}"
    )


@router.message(StateFilter(OrderFlow.collecting))
async def on_not_file(message: Message, state: FSMContext) -> None:
    """В режиме приёма пришло не-файловое сообщение (текст и т.п.)."""
    data = await state.get_data()
    if data.get("files"):
        # Уже есть файлы — показываем кнопки, чтобы можно было завершить/отменить.
        await message.answer(texts.NOT_A_FILE, reply_markup=keyboards.collecting_kb())
    else:
        # Ни одного файла ещё нет — без кнопок, просто просим прислать файл.
        await message.answer(texts.NOT_A_FILE_YET)


# ─────────────────────────── Завершение приёма ───────────────────────────

@router.callback_query(F.data == keyboards.FINISH_ORDER_CALLBACK, StateFilter(OrderFlow.collecting))
async def cb_finish_order(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    files: list[dict[str, Any]] = data.get("files", [])

    if not files:
        # Практически недостижимо: кнопка «Завершить» появляется только после первого файла.
        await callback.answer()
        await callback.message.answer(texts.NO_FILES_YET)
        return

    await state.set_state(OrderFlow.waiting_client_name)
    # Убираем кнопки у предыдущего сообщения, чтобы не завершали повторно.
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(texts.ASK_CLIENT_NAME.format(count=len(files)))
    await callback.answer()
    logger.info(
        f"🤖 Бот → @{callback.from_user.username or '—'}: приём завершён ({len(files)} файлов), запрошено имя клиента"
    )


# ─────────────────────────── Имя клиента ───────────────────────────

@router.message(StateFilter(OrderFlow.waiting_client_name), F.text)
async def on_client_name(message: Message, state: FSMContext) -> None:
    client_name = message.text.strip()
    await state.update_data(client_name=client_name)
    await state.set_state(OrderFlow.waiting_quantity)
    await message.answer(texts.ASK_QUANTITY.format(client=escape(client_name)))
    logger.info(
        f"🤖 Бот → @{message.from_user.username or '—'}: имя клиента «{client_name}», запрошено количество"
    )


@router.message(StateFilter(OrderFlow.waiting_client_name))
async def on_client_name_not_text(message: Message) -> None:
    await message.answer(texts.NAME_NOT_TEXT)


# ─────────────────────────── Количество/описание ───────────────────────────

@router.message(StateFilter(OrderFlow.waiting_quantity), F.text)
async def on_quantity(message: Message, state: FSMContext, pool: asyncpg.Pool) -> None:
    quantity = message.text.strip()
    data = await state.get_data()
    files: list[dict[str, Any]] = data.get("files", [])
    client_name: str = data.get("client_name", "")

    order_id = await repo.create_order(
        pool,
        tg_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        client_name=client_name,
        quantity=quantity,
        files=files,
    )
    await state.clear()

    await message.answer(
        texts.ORDER_ACCEPTED.format(
            id=order_id,
            client=escape(client_name),
            quantity=escape(quantity),
            count=len(files),
        ),
        reply_markup=keyboards.main_kb(),
    )
    logger.info(
        f"✅ Заказ №{order_id} создан @{message.from_user.username or '—'} (id:{message.from_user.id}): "
        f"клиент «{client_name}», кол-во «{quantity}», файлов {len(files)}"
    )


@router.message(StateFilter(OrderFlow.waiting_quantity))
async def on_quantity_not_text(message: Message) -> None:
    await message.answer(texts.QUANTITY_NOT_TEXT)


# ─────────────────────────── Отмена ───────────────────────────

@router.callback_query(F.data == keyboards.CANCEL_ORDER_CALLBACK)
async def cb_cancel_order(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(texts.ORDER_CANCELLED)
    await callback.answer()
    logger.info(f"🤖 Бот → @{callback.from_user.username or '—'}: заказ отменён")


@router.message(Command("cancel"), StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        return
    await state.clear()
    await message.answer(texts.ORDER_CANCELLED)
    logger.info(f"🤖 Бот → @{message.from_user.username or '—'}: заказ отменён (/cancel)")
