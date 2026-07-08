"""Сценарий приёма заказа (FSM).

Поток:
  «Новый заказ» → предупреждение → сбор файлов → «Завершить заказ»
  → имя клиента → количество/описание → «Заказ принят» (запись в БД).

Состояния и накопленные файлы хранятся в Redis (FSM-хранилище aiogram).
"""
from __future__ import annotations

import asyncio
from html import escape
from typing import Any

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter
from aiogram.types import CallbackQuery, Message
import asyncpg

from .. import keyboards, repo, texts
from ..logger import logger
from ..services import autosend
from ..services.delivery import send_order_to_group

router = Router()

# Пауза перед итоговым подтверждением о файлах. Позволяет «схлопнуть» пачку файлов
# (альбом/несколько выбранных сразу) в одно сообщение вместо спама по каждому файлу.
_CONFIRM_DELAY = 0.8

# Сериализация добавления файлов по пользователю: сообщения альбома aiogram обрабатывает
# параллельно, и без блокировки конкурентные read-modify-write списка файлов в FSM
# затирают друг друга (часть файлов терялась). Лок гарантирует, что все файлы сохранятся.
_file_locks: dict[int, asyncio.Lock] = {}
# Токен последней «пачки» файлов на пользователя — чтобы подтверждение отправил только
# самый поздний файл в серии (дебаунс).
_confirm_tokens: dict[int, int] = {}


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
async def cb_new_order(callback: CallbackQuery, state: FSMContext, pool: asyncpg.Pool) -> None:
    """«Новый заказ»: показать видео-инструкцию (если задана), предупреждение и начать приём файлов."""
    await state.clear()
    await state.set_state(OrderFlow.collecting)
    await state.update_data(files=[])

    # Видео-инструкция «как загружать файлы» — до предупреждения (если админ её задал).
    await _show_instruction_video(callback, pool)

    # Кнопки «Завершить/Отменить» здесь НЕ показываем — они появятся по мере загрузки файлов.
    await callback.message.answer(texts.ORDER_WARNING)
    await callback.answer()
    logger.info(
        f"🤖 Бот → @{callback.from_user.username or '—'}: показано предупреждение, старт приёма файлов"
    )


async def _show_instruction_video(callback: CallbackQuery, pool: asyncpg.Pool) -> None:
    """Показывает видео-инструкцию, если она задана. Ошибки не ломают сценарий заказа."""
    video = await repo.get_instruction_video(pool)
    if video is None:
        return
    caption = video["caption"] or texts.INSTRUCTION_CAPTION_FALLBACK
    try:
        if video["is_video"]:
            await callback.message.answer_video(video["file_id"], caption=caption)
        else:
            await callback.message.answer_document(video["file_id"], caption=caption)
    except Exception:
        logger.exception("Не удалось показать видео-инструкцию технику")


# ─────────────────────────── Приём файлов ───────────────────────────

_FILE_FILTER = (
    F.document | F.photo | F.video | F.audio | F.voice | F.animation | F.video_note
)


@router.message(StateFilter(OrderFlow.collecting), _FILE_FILTER)
async def on_file(message: Message, state: FSMContext, bot: Bot) -> None:
    file = _extract_file(message)
    if file is None:  # на всякий случай
        return

    uid = message.from_user.id
    lock = _file_locks.setdefault(uid, asyncio.Lock())
    # Лок сериализует конкурентные добавления файлов из одной пачки — иначе теряются.
    async with lock:
        data = await state.get_data()
        files: list[dict[str, Any]] = data.get("files", [])
        files.append(file)
        # Данные отправителя нужны воркеру авто-досылки, если клиент уйдёт не завершив.
        await state.update_data(
            files=files,
            sender_tg_id=uid,
            sender_username=message.from_user.username,
            sender_first_name=message.from_user.first_name,
        )
        count = len(files)
        token = _confirm_tokens.get(uid, 0) + 1
        _confirm_tokens[uid] = token

    # Продлеваем дедлайн авто-досылки: файлы уйдут сами, если клиент бросит заказ.
    await autosend.touch(message.chat.id, uid)

    logger.info(
        f"📎 Заказ (сбор) @{message.from_user.username or '—'} (id:{uid}): "
        f"файл #{count} тип={file['file_type']} имя={file.get('file_name')} "
        f"размер={file.get('file_size')}"
    )
    # Подтверждение отправляем с дебаунсом: только последний файл пачки покажет итог.
    asyncio.create_task(_confirm_added_later(bot, message.chat.id, state, uid, token))


async def _confirm_added_later(
    bot: Bot, chat_id: int, state: FSMContext, uid: int, token: int
) -> None:
    """Через паузу обновляет единственное сообщение-счётчик с итоговым числом файлов.

    Держим ровно одно подтверждение: при новой пачке удаляем предыдущее сообщение
    и шлём новое с актуальным числом — кнопка «Завершить» всегда одна и снизу.
    Срабатывает только последняя задача серии (дебаунс по token)."""
    try:
        await asyncio.sleep(_CONFIRM_DELAY)
        if _confirm_tokens.get(uid) != token:
            return  # пришёл ещё файл — подтвердит следующая задача

        lock = _file_locks.setdefault(uid, asyncio.Lock())
        async with lock:
            if _confirm_tokens.get(uid) != token:
                return
            if await state.get_state() != OrderFlow.collecting.state:
                return  # сценарий уже ушёл дальше (завершён/отменён)
            data = await state.get_data()
            count = len(data.get("files", []))
            if count == 0:
                return

            # Удаляем предыдущее сообщение-счётчик, чтобы не плодить кнопки.
            prev_id = data.get("confirm_msg_id")
            if prev_id:
                try:
                    await bot.delete_message(chat_id, prev_id)
                except Exception:
                    pass

            msg = await bot.send_message(
                chat_id,
                texts.FILES_ADDED.format(count=count),
                reply_markup=keyboards.collecting_kb(),
            )
            await state.update_data(confirm_msg_id=msg.message_id)
    except Exception:
        logger.exception("Ошибка при отправке подтверждения о принятых файлах")


# Файл прислан вне сценария заказа (нажал /start и сразу отправил файлы, не нажав
# «Новый заказ»). StateFilter(None) — срабатывает только когда активного FSM нет.
@router.message(StateFilter(None), _FILE_FILTER)
async def on_file_without_order(message: Message) -> None:
    await message.answer(texts.NEED_NEW_ORDER, reply_markup=keyboards.main_kb())
    logger.info(
        f"🤖 Бот → @{message.from_user.username or '—'}: файл вне заказа — "
        f"подсказка нажать «Новый заказ»"
    )


@router.message(StateFilter(OrderFlow.collecting))
async def on_not_file(message: Message, state: FSMContext) -> None:
    """В режиме приёма пришло не-файловое сообщение (текст и т.п.)."""
    # Без кнопок: единственная кнопка «Завершить» живёт на сообщении-счётчике файлов.
    data = await state.get_data()
    if data.get("files"):
        await message.answer(texts.NOT_A_FILE)
    else:
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
    # Клиент ещё в процессе — продлеваем дедлайн авто-досылки.
    await autosend.touch(callback.message.chat.id, callback.from_user.id)
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
    # Клиент активен — продлеваем дедлайн авто-досылки.
    await autosend.touch(message.chat.id, message.from_user.id)
    await message.answer(texts.ASK_QUANTITY.format(client=escape(client_name)))
    logger.info(
        f"🤖 Бот → @{message.from_user.username or '—'}: имя клиента «{client_name}», запрошено количество"
    )


@router.message(StateFilter(OrderFlow.waiting_client_name))
async def on_client_name_not_text(message: Message) -> None:
    await message.answer(texts.NAME_NOT_TEXT)


# ─────────────────────────── Количество/описание ───────────────────────────

@router.message(StateFilter(OrderFlow.waiting_quantity), F.text)
async def on_quantity(
    message: Message, state: FSMContext, pool: asyncpg.Pool, bot: Bot
) -> None:
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
    # Заказ оформлен штатно — снимаем его с авто-досылки.
    await autosend.clear(message.chat.id, message.from_user.id)

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

    # Отправляем карточку и файлы в закрытую группу «Город».
    # Ошибки доставки не ломают клиентский поток — заказ уже принят и сохранён.
    await send_order_to_group(bot, pool, order_id)


@router.message(StateFilter(OrderFlow.waiting_quantity))
async def on_quantity_not_text(message: Message) -> None:
    await message.answer(texts.QUANTITY_NOT_TEXT)


# ─────────────────────────── Отмена ───────────────────────────

@router.callback_query(F.data == keyboards.CANCEL_ORDER_CALLBACK)
async def cb_cancel_order(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await autosend.clear(callback.message.chat.id, callback.from_user.id)
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
    await autosend.clear(message.chat.id, message.from_user.id)
    await message.answer(texts.ORDER_CANCELLED)
    logger.info(f"🤖 Бот → @{message.from_user.username or '—'}: заказ отменён (/cancel)")
