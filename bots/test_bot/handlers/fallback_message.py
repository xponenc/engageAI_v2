import asyncio
import html
import json
import time
from typing import Union, Optional
from aiogram import Router, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, ReplyKeyboardRemove
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from bots.services.utils import get_assistant_slug
from bots.test_bot.filters.require_auth import AuthFilter
from bots.test_bot.config import bot_logger, BOT_NAME
from bots.test_bot.services.api_service import CoreAPIClient
from bots.test_bot.services.utils import is_user_authorized
from bots.test_bot.services.renderer import render_content_from_core

from bots.test_bot.tasks import process_save_message

fallback_router = Router()


class MediaGroupState(StatesGroup):
    waiting_media_group = State()  # Состояние только для сбора медиа-групп


media_group_timers: dict[int, asyncio.Task] = {}


async def resolve_message_from_state(state: FSMContext, bot: Bot) -> Optional[Message]:
    """Восстанавливает последнее сообщение из состояния"""
    data = await state.get_data()
    real_messages = data.get("real_messages", [])
    if not real_messages:
        return None

    last = real_messages[-1]
    try:
        return await bot.get_message(
            chat_id=last["chat_id"],
            message_id=last["message_id"]
        )
    except Exception as e:
        bot_logger.warning(f"[{BOT_NAME}] Не удалось загрузить сообщение из состояния: {str(e)}")
        return None


# --------------------------
#   ОСНОВНОЙ ХЕНДЛЕР
# --------------------------
@fallback_router.message(AuthFilter())
async def handle_orchestrator_request(message: Message, state: FSMContext, bot: Bot):
    """Обрабатывает все типы сообщений для авторизованных пользователей"""
    bot_tag = f"[{BOT_NAME}]"
    bot_logger.info(f"{bot_tag} Получено сообщение от {message.from_user.id}, тип: {message.content_type}")

    # Проверка на медиа-группу
    if message.media_group_id:
        return await handle_media_group(message, state, bot)

    # Если мы в состоянии ожидания медиа-группы, но пришло обычное сообщение
    current_state = await state.get_state()
    if current_state == MediaGroupState.waiting_media_group.state:
        # Сначала обрабатываем накопленную медиа-группу
        await process_media_group_after_timeout(state, bot)
        # Сбрасываем состояние
        await state.set_state(None)

    # Обрабатываем сообщение напрямую через Core
    return await process_ai_request(message, state, bot)


@fallback_router.callback_query(AuthFilter())
async def handle_callback_query(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Обрабатывает callback запросы от кнопок"""
    bot_tag = f"[{BOT_NAME}]"
    bot_logger.info(f"{bot_tag} Получен callback от {callback.from_user.id}: {callback.data}")

    await callback.answer()
    return await process_ai_request(callback, state, bot)


async def handle_media_group(message: Message, state: FSMContext, bot: Bot):
    """Обработка медиа-групп с исправлением проблемы 'пинания'"""
    state_data = await state.get_data()
    current_group_id = state_data.get("current_media_group_id")

    # Если это новая группа — сбрасываем состояние
    if current_group_id != message.media_group_id:
        # Отменяем старый таймер, если есть
        chat_id = message.chat.id
        old_task = media_group_timers.get(chat_id)
        if old_task and not old_task.done():
            old_task.cancel()

        # Сбрасываем данные
        await state.update_data(
            current_media_group_id=message.media_group_id,
            media_items=[],
            real_messages=[],
        )
        await state.set_state(MediaGroupState.waiting_media_group)

    # Сохраняем сообщение
    data = await state.get_data()
    media_items = data.get("media_items", [])
    real_messages = data.get("real_messages", [])

    # Добавляем безопасно сериализуемую мета-информацию
    real_messages.append({
        "chat_id": message.chat.id,
        "message_id": message.message_id
    })

    # Сохраняем метаданные для медиагруппы
    media_data = {
        "message_id": message.message_id,
        "chat_id": message.chat.id,
        "from_user_id": message.from_user.id,
        "date": int(message.date.timestamp()),
        "caption": message.caption
    }

    if message.photo:
        photo = message.photo[-1]  # Самое качественное фото
        media_data.update({
            "type": "photo",
            "file_id": photo.file_id,
            "width": photo.width,
            "height": photo.height
            # size НЕ указываем — его получит Core при загрузке
        })
    elif message.video:
        media_data.update({
            "type": "video",
            "file_id": message.video.file_id,
            "width": message.video.width,
            "height": message.video.height,
            "duration": message.video.duration,
            "file_name": message.video.file_name,
            "mime_type": message.video.mime_type
            # size НЕ указываем — его получит Core при загрузке
        })

    media_items.append(media_data)
    await state.update_data(
        media_items=media_items,
        real_messages=real_messages
    )

    chat_id = message.chat.id

    # Отменяем старый таймер, если есть
    old_task = media_group_timers.get(chat_id)
    if old_task and not old_task.done():
        old_task.cancel()

    # Создаём новый таймер
    new_task = asyncio.create_task(process_media_group_after_timeout(state, bot))
    media_group_timers[chat_id] = new_task

    # Подтверждаем получение первого элемента группы
    if len(media_items) == 1:
        await message.answer("⏳ Получаю медиа-файлы...", reply_to_message_id=message.message_id)

    return


async def process_media_group_after_timeout(state: FSMContext, bot: Bot):
    """Обрабатывает медиа-группу через короткий таймаут с гарантией выполнения"""
    try:
        await asyncio.sleep(1.5)  # Увеличиваем таймаут для надёжности
    except asyncio.CancelledError:
        return

    # Проверяем актуальное состояние
    current_state = await state.get_state()
    if current_state != MediaGroupState.waiting_media_group.state:
        return

    state_data = await state.get_data()
    media_items = state_data.get("media_items", [])
    real_messages = state_data.get("real_messages", [])

    if not media_items or not real_messages:
        return

    # Получаем последнее реальное сообщение
    last_real_message = await resolve_message_from_state(state, bot)
    if not last_real_message:
        return

    # Проверяем авторизацию
    authorized = await is_user_authorized(state)
    if not authorized:
        await bot.send_message(
            chat_id=last_real_message.chat.id,
            text="🔒 Сессия устарела. Пожалуйста, перезапустите бота командой /start"
        )
        await state.clear()
        return

    # Получаем данные пользователя из состояния
    state_data = await state.get_data()
    profile = state_data.get("profile", {})
    core_user_id = profile.get("core_user_id")

    if not core_user_id:
        await bot.send_message(
            chat_id=last_real_message.chat.id,
            text="Ошибка загрузки вашего профиля. Попробуйте перезапустить бота командой /start"
        )
        await state.clear()
        return

    # Формируем payload для Core - ТОЛЬКО file_id и базовые метаданные
    core_payload = {
        "user_id": core_user_id,
        "source": "telegram",
        "content": next((item.get("caption") for item in media_items if item.get("caption")), ""),
        "message_type": "media_group",
        "media_files": [
            {
                "external_id": item["file_id"],  # Передаём только file_id
                "file_type": item["type"],
                "mime_type": item.get("mime_type", "application/octet-stream"),
                "caption": item.get("caption")
                # size НЕ передаём — его определит Core при загрузке
            } for item in media_items
        ],
        "metadata": {
            "chat_id": last_real_message.chat.id,
            "message_thread_id": getattr(last_real_message, "message_thread_id", None),
            "from_user": {
                "id": last_real_message.from_user.id,
                "username": last_real_message.from_user.username or "",
                "first_name": last_real_message.from_user.first_name or "",
                "last_name": last_real_message.from_user.last_name or ""
            }
        }
    }

    async with CoreAPIClient() as client:
        core_response = await client.receive_response(core_payload)

    if core_response:
        # Рендерим ответ от Core
        await render_content_from_core(
            bot=bot,
            user_id=last_real_message.from_user.id,
            core_payload=core_response,
            state=state
        )
    else:
        await bot.send_message(
            chat_id=last_real_message.chat.id,
            text="⚠️ Не удалось обработать медиа-группу. Попробуйте отправить файлы по одному."
        )

    # Очищаем состояние
    await state.update_data(
        current_media_group_id=None,
        media_items=[],
        real_messages=[]
    )
    await state.set_state(None)

    # Удаляем таймер из памяти
    chat_id = last_real_message.chat.id
    await media_group_timers.pop(chat_id, None)


async def process_ai_request(event: Union[Message, CallbackQuery], state: FSMContext, bot: Bot):
    """Универсальная обработка запросов к Core API"""
    bot_tag = f"[{BOT_NAME}]"
    assistant_slug = get_assistant_slug(event.bot)

    await state.update_data(
        core_answer={},
        core_answer_meta={},
        last_message_update_config={},
    )

    # Получаем данные пользователя из состояния
    state_data = await state.get_data()
    bot_logger.warning(f"{bot_tag} process_ai_request: {state_data}")
    profile = state_data.get("telegram_auth_cache", {})
    core_user_id = profile.get("core_user_id")

    if not core_user_id:
        bot_logger.warning(f"{bot_tag} Профиль пользователя отсутствует")
        # TODO а почему отсутствует?
        await state.clear()
        return
    payload = {
        "assistant_slug": assistant_slug,
        "platform": "telegram",
        "content": "",
        "media_files": [],
    }

    # Заполняем payload в зависимости от типа события
    if isinstance(event, CallbackQuery):
        payload["chat_id"] = str(event.message.chat.id)
        payload["user_telegram_id"] = str(event.from_user.id)
        payload["user_id"] = str(event.from_user.id)
        payload["reply_to_message_id"] = str(event.id)
        payload["message_type"] = "callback"
        payload["user_response"] = event.data

    else:  # Message
        payload["chat_id"] = str(event.chat.id)
        payload["user_telegram_id"] = str(event.from_user.id)
        payload["user_id"] = str(event.from_user.id)
        payload["reply_to_message_id"] = str(event.message_id)
        payload["message_type"] = "text"
        payload["user_response"] = event.text

        # Обработка медиа-группы
        if hasattr(event, 'media_info'):
            payload["message_type"] = "media_group"
            payload["content"] = next((item.get("caption") for item in event.media_info if item.get("caption")), "")

            payload["media_files"] = [
                {
                    "external_id": item["file_id"],
                    "file_type": item["type"],
                    "mime_type": item.get("mime_type", "application/octet-stream"),
                    "caption": item.get("caption")
                    # size НЕ передаём — его определит Core
                } for item in event.media_info
            ]

        # Обработка обычных сообщений
        else:
            if event.text:
                payload["content"] = event.text

            if event.photo:
                photo = event.photo[-1]
                payload["message_type"] = "image"
                payload["content"] = event.caption or ""

                payload["media_files"].append({
                    "external_id": photo.file_id,
                    "file_type": "image",
                    "caption": event.caption or ""
                })

            elif event.document:
                payload["message_type"] = "document"
                payload["content"] = event.caption or ""

                payload["media_files"].append({
                    "external_id": event.document.file_id,
                    "file_type": "document",
                    "caption": event.caption or "",
                    "file_name": event.document.file_name  # передаём имя файла
                })

    async with CoreAPIClient() as client:
        core_response = await client.receive_response(payload)

    if core_response:
        await state.update_data(
            core_answer=core_response.get("core_answer", {}),
            core_answer_meta=core_response.get("core_answer_meta", {}),
            last_message_update_config=core_response.get("last_message_update_config", {}),
        )
        await process_core_response(
            event=event,
            assistant_slug=assistant_slug,
            state=state
        )
    else:
        if isinstance(event, CallbackQuery):
            await event.message.answer("⚠️ Сервер временно недоступен. Попробуйте позже.")
        else:
            await event.answer("⚠️ Сервер временно недоступен. Попробуйте позже.")

    return


async def process_core_response(
        event: Union[Message, CallbackQuery],
        assistant_slug: str,
        state: FSMContext
):
    bot_tag = f"[{BOT_NAME}]"

    if isinstance(event, CallbackQuery):
        bot = event.bot
        user_id = event.from_user.id
        reply_target = event.message
        message_id = event.id
        chat_id = event.message.chat.id
        answer_text = event.data
    else:  # Message
        bot = event.bot
        user_id = event.from_user.id
        reply_target = event
        message_id = event.message_id
        chat_id = event.chat.id
        answer_text = event.text

    state_data = await state.get_data()
    last_message = state_data.get("last_message")

    # 1. Изменение last_message от бота, т.е того сообщения на которое ответил пользователь
    core_answer_meta = state_data.get("core_answer_meta", {})
    # Пример
    # last_message_update_config = {
    #     "change_last_message": True, # Флаг изменять/не изменять last_message
    #     "text": {
    #         "method": "append", # append добавить текст к сообщению, rewrite - изменить полностью
    #         "last_message_update_text": "текст для добавления к сообщению или новый текст",
    #         "fix_user_answer": True, # Зафиксировать в изменяемом сообщении цитатой ответ пользователя - протоколирование
    #     },
    #     "keyboard": {
    #         "reset": True, # Удалить клавиатуру у редактируемого сообщения
    #     }
    # }
    last_message_update_config = core_answer_meta.get("last_message_update_config", {})

    change_last_message = last_message_update_config.get("change_last_message", False)

    if last_message and change_last_message:
        text_config = last_message_update_config.get("text", {})
        text_method = text_config.get("method", "append")
        fix_user_answer = text_config.get("fix_user_answer", False)
        last_message_update_text = text_config.get("last_message_update_text", "")

        original_message_text = last_message.get('text')
        if fix_user_answer and answer_text:
            escaped_answer_text = html.escape(answer_text)
            last_message_update_text = f"<blockquote>{escaped_answer_text}</blockquote>\n" + last_message_update_text

        if text_method == "rewrite":
            new_message_text = last_message_update_text
        else:
            new_message_text = (original_message_text +
                                f"\n\n{last_message_update_text}") if last_message_update_text else ""

        keyboard_config = last_message_update_config.get("keyboard", {})
        keyboard_reset = keyboard_config.get("reset", True)
        keyboard = None
        if not keyboard_reset:
            original_message_keyboard_json = last_message.get("keyboard")

            if original_message_keyboard_json:
                try:
                    keyboard_dict = json.loads(original_message_keyboard_json)
                    keyboard = InlineKeyboardMarkup.model_validate(keyboard_dict)
                except Exception:
                    keyboard = None

        original_message_parse_mode = last_message.get("parse_mode", ParseMode.HTML)
        try:
            await reply_target.bot.edit_message_text(
                text=new_message_text,
                chat_id=chat_id,
                message_id=last_message.get("id"),
                reply_markup=keyboard,
                parse_mode=original_message_parse_mode
            )
        except TelegramBadRequest:
            pass

    # 2. Отправка core_answer пользователю

    answer_message = await render_content_from_core(
        reply_target=reply_target,
        state=state
    )
    # 3. Отправка в core обновления по core_answer (обновление метаданных, привязка reply_to, отметка - отправлено)
    cache = state_data.get("telegram_auth_cache", {})
    core_user_id = cache.get("core_user_id")

    if core_user_id and answer_message:
        core_message_id = core_answer_meta.get("core_message_id") if core_answer_meta else None

        # Определяем тип ответа
        if isinstance(answer_message, CallbackQuery):
            telegram_user_id = answer_message.from_user.id

            if answer_message.message:
                answer_message_id = answer_message.message.message_id
            #
            else:
                answer_message_id = None
        else:  # Message
            telegram_user_id = answer_message.chat.id
            answer_message_id = answer_message.message_id

        payload = {
            "core_message_id": core_message_id,
            # если не передано, то создастся новое engageai_core.chat.models.Message
            "reply_to_message_id": message_id,
            "message_id": answer_message_id,
            "telegram_message_id": answer_message_id,
            "text": answer_text,
            "assistant_slug": assistant_slug,
            "user_telegram_id": telegram_user_id,
            "metadata": answer_message.model_dump(),  # полный дамп сообщения telegram с клавиатурой
        }

        bot_logger.info(f"{bot_tag} PLAYLOAD отправка обновления ответа CORE после ответа пользователю")

        process_save_message.delay(payload=payload)
