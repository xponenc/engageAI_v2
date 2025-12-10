import asyncio
import time
import json
from typing import Union, Optional, Dict, Any
from aiogram import Router, F, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.media_group import MediaGroupBuilder

from bots.test_bot.filters.require_auth import AuthFilter
from bots.test_bot.services.api_process import core_post, auto_context
from bots.test_bot.config import bot_logger, BOT_NAME, AUTH_CACHE_TTL_SECONDS, NO_EMOJI, EXCLAMATION_EMOJI, YES_EMOJI
from bots.services.utils import get_assistant_slug
from bots.test_bot.services.sender import reply_and_update_last_message
from bots.test_bot.services.utils import is_user_authorized
from bots.test_bot.tasks import process_save_message  # Импорт в начале файла

fallback_router = Router()


class OrchestratorState(StatesGroup):
    waiting_response = State()  # Основное состояние для обработки запросов к AI
    processing_callback = State()  # Для обработки callback в контексте диалога с AI
    waiting_media_group = State()  # Для обработки медиа-групп


# Обработчик всех сообщений для авторизованных пользователей
@fallback_router.message(AuthFilter())
async def handle_orchestrator_request(message: Message, state: FSMContext):
    """Обрабатывает все типы сообщений для авторизованных пользователей"""
    bot_tag = f"[{BOT_NAME}]"
    bot_logger.info(
        f"{bot_tag} Получено сообщение для AI обработки от {message.from_user.id}, тип: {message.content_type}")

    # Проверяем, является ли сообщение частью медиа-группы
    if message.media_group_id:
        return await handle_media_group(message, state, message.bot)

    # Обработка callback и других сообщений
    current_state = await state.get_state()
    if current_state == OrchestratorState.waiting_media_group.state:
        # Это НЕ медиа-группа, но FSM всё ещё в состоянии ожидания группы
        # → Это означает, что предыдущая группа завершилась, обрабатываем её
        await process_media_group(message, state)
        await state.update_data(current_media_group_id=None, media_items=[])
        await state.set_state(OrchestratorState.waiting_response)
        # И ОБРАБАТЫВАЕМ ТЕКУЩЕЕ СООБЩЕНИЕ
        return await process_ai_request(message, state)

    # Устанавливаем состояние Orchestrator для обычных сообщений
    await state.set_state(OrchestratorState.waiting_response)

    # Обрабатываем запрос
    return await process_ai_request(message, state)


@fallback_router.callback_query(AuthFilter())
async def handle_orchestrator_callback(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает callback от кнопок в AI-ответах"""
    bot_tag = f"[{BOT_NAME}]"
    bot_logger.info(f"{bot_tag} Получен callback для AI обработки от {callback.from_user.id}: {callback.data}")

    await callback.answer()
    await state.set_state(OrchestratorState.processing_callback)

    # Обрабатываем callback как запрос к AI
    return await process_ai_request(callback, state)

#
# async def handle_media_group(message: Message, state: FSMContext):
#     """Обработка медиа-групп"""
#     state_data = await state.get_data()
#     current_group_id = state_data.get("current_media_group_id")
#
#     if current_group_id != message.media_group_id:
#         await state.update_data(
#             current_media_group_id=message.media_group_id,
#             media_items=[],
#             media_group_start_time=time.time()
#         )
#         await state.set_state(OrchestratorState.waiting_media_group)
#
#     media_items = (await state.get_data()).get("media_items", [])
#
#     # Извлекаем только необходимые данные вместо сохранения всего объекта
#     media_data = {
#         "message_id": message.message_id,
#         "chat_id": message.chat.id,
#         "from_user_id": message.from_user.id,
#         "date": int(message.date.timestamp()),
#         "caption": message.caption
#     }
#
#     if message.photo:
#         photo = message.photo[-1]  # Самое качественное фото
#         media_data.update({
#             "type": "photo",
#             "file_id": photo.file_id,
#             "width": photo.width,
#             "height": photo.height,
#             "file_size": photo.file_size
#         })
#     elif message.video:
#         media_data.update({
#             "type": "video",
#             "file_id": message.video.file_id,
#             "width": message.video.width,
#             "height": message.video.height,
#             "duration": message.video.duration,
#             "file_name": message.video.file_name,
#             "mime_type": message.video.mime_type,
#             "file_size": message.video.file_size
#         })
#
#     media_items.append(media_data)
#     await state.update_data(media_items=media_items)
#
#     if len(media_items) == 1:
#         _ = asyncio.create_task(process_media_group_after_timeout(state))
#     return
#
#
# async def process_media_group_after_timeout(state: FSMContext):
#     """Обрабатывает медиа-группу через короткий таймаут"""
#     await asyncio.sleep(1.2)  # даем время на получение всех элементов
#
#     current_state = await state.get_state()
#     if current_state != OrchestratorState.waiting_media_group.state:
#         return
#
#     state_data = await state.get_data()
#     media_items = state_data.get("media_items", [])
#
#     if not media_items:
#         return
#
#     # ВСЕГДА обрабатываем группу по таймауту, без дополнительных проверок времени
#     last_message = media_items[-1]
#     await process_media_group(last_message, state)
#
#     # Сбрасываем состояние
#     await state.update_data(current_media_group_id=None, media_items=[])
#     await state.set_state(OrchestratorState.waiting_response)
#
#
# async def process_media_group(message: Message, state: FSMContext):
#     """Обрабатывает накопленную медиа-группу"""
#     bot_tag = f"[{BOT_NAME}]"
#     state_data = await state.get_data()
#     media_items = state_data.get("media_items", [])
#     media_group_id = state_data.get("current_media_group_id")
#
#     if not media_items:
#         bot_logger.warning(f"{bot_tag} Попытка обработать пустую медиа-группу")
#         return
#
#     bot_logger.info(f"{bot_tag} Обработка медиа-группы {media_group_id} с {len(media_items)} элементами")
#
#     media_info = media_items
#
#     class MediaGroupEvent:
#         def __init__(self, message, media_info):
#             self.message = message
#             self.media_info = media_info
#             self.from_user = message.from_user
#             self.chat = message.chat
#             self.message_id = message.message_id
#             self.content_type = "media_group"
#             self.text = next((item.get("caption") for item in media_info if item.get("caption")), "")
#
#         def __getattr__(self, name):
#             return getattr(self.message, name)
#
#     media_group_event = MediaGroupEvent(message, media_info)
#     return await process_ai_request(media_group_event, state)

from aiogram import Bot
from aiogram.types import Message
import asyncio

media_group_timers: dict[int, asyncio.Task] = {}

# --------------------------
#   ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ
# --------------------------

async def resolve_message_from_state(state: FSMContext, bot: Bot) -> Message | None:
    """Берёт последний message_id из real_messages и загружает настоящее сообщение через Bot API."""
    data = await state.get_data()
    real_messages = data.get("real_messages", [])
    if not real_messages:
        return None

    last = real_messages[-1]   # {"chat_id": ..., "message_id": ...}

    try:
        return await bot.get_message(
            chat_id=last["chat_id"],
            message_id=last["message_id"]
        )
    except Exception:
        return None


# --------------------------
#   ОСНОВНОЙ ХЕНДЛЕР
# --------------------------

async def handle_media_group(message: Message, state: FSMContext, bot: Bot):
    """Обработка медиа-групп"""
    state_data = await state.get_data()
    current_group_id = state_data.get("current_media_group_id")

    # новая группа — сбрасываем
    if current_group_id != message.media_group_id:
        await state.update_data(
            current_media_group_id=message.media_group_id,
            media_items=[],
            real_messages=[],   # теперь тут только {"chat_id","message_id"}
            media_group_task=None
        )
        await state.set_state(OrchestratorState.waiting_media_group)

    data = await state.get_data()
    media_items = data.get("media_items", [])
    real_messages = data.get("real_messages", [])

    # Добавляем безопасно сериализуемую мета-информацию вместо Message
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
        photo = message.photo[-1]
        media_data.update({
            "type": "photo",
            "file_id": photo.file_id,
            "width": photo.width,
            "height": photo.height,
            "file_size": photo.file_size
        })
    elif message.video:
        media_data.update({
            "type": "video",
            "file_id": message.video.file_id,
            "width": message.video.width,
            "height": message.video.height,
            "duration": message.video.duration,
            "file_name": message.video.file_name,
            "mime_type": message.video.mime_type,
            "file_size": message.video.file_size
        })

    media_items.append(media_data)

    # сохраняем обновления
    await state.update_data(
        media_items=media_items,
        real_messages=real_messages
    )

    chat_id = message.chat.id

    # отменяем старый таймер, если есть
    old_task = media_group_timers.get(chat_id)
    if old_task and not old_task.done():
        old_task.cancel()

    # создаём новый таймер
    new_task = asyncio.create_task(process_media_group_after_timeout(state, bot))

    # сохраняем только в памяти, НЕ в state
    media_group_timers[chat_id] = new_task

    return


# --------------------------
#   ТАЙМЕР
# --------------------------

async def process_media_group_after_timeout(state: FSMContext, bot: Bot):
    """Обрабатывает медиа-группу через короткий таймаут"""
    try:
        await asyncio.sleep(1.2)
    except asyncio.CancelledError:
        return

    current_state = await state.get_state()
    if current_state != OrchestratorState.waiting_media_group.state:
        return

    state_data = await state.get_data()
    media_items = state_data.get("media_items", [])
    real_messages = state_data.get("real_messages", [])

    if not media_items or not real_messages:
        return

    # Восстанавливаем настоящее последнее сообщение
    last_real_message = await resolve_message_from_state(state, bot)
    if not last_real_message:
        return

    # Отправляем в обработку
    await process_media_group(last_real_message, state)

    # Сбрасываем состояние
    await state.update_data(
        current_media_group_id=None,
        media_items=[],
        real_messages=[],
        media_group_task=None
    )

    data = await state.get_data()
    real_messages = data.get("real_messages", [])
    if real_messages:
        chat_id = real_messages[-1]["chat_id"]
        media_group_timers.pop(chat_id, None)
        
    await state.set_state(OrchestratorState.waiting_response)




# --------------------------
#   ОБРАБОТЧИК МЕДИАГРУППЫ
# --------------------------

async def process_media_group(message: Message, state: FSMContext):
    bot_tag = f"[{BOT_NAME}]"
    state_data = await state.get_data()
    media_items = state_data.get("media_items", [])
    media_group_id = state_data.get("current_media_group_id")

    if not media_items:
        bot_logger.warning(f"{bot_tag} Попытка обработать пустую медиа-группу")
        return

    bot_logger.info(f"{bot_tag} Обработка медиа-группы {media_group_id} с {len(media_items)} элементами")

    class MediaGroupEvent:
        def __init__(self, message, media_info):
            self.message = message
            self.media_info = media_info
            self.from_user = message.from_user
            self.chat = message.chat
            self.message_id = message.message_id
            self.content_type = "media_group"
            self.text = next((item.get("caption") for item in media_info if item.get("caption")), "")

        def __getattr__(self, name):
            return getattr(self.message, name)

    media_group_event = MediaGroupEvent(message, media_items)
    return await process_ai_request(media_group_event, state)



@auto_context()
async def process_ai_request(event: Union[Message, CallbackQuery, 'MediaGroupEvent'], state: FSMContext, **kwargs):
    """Универсальная обработка запросов к AI-оркестратору"""
    bot_tag = f"[{BOT_NAME}]"
    content_type = "media_group" if hasattr(event, 'media_info') else (
        "callback" if isinstance(event, CallbackQuery) else event.content_type
    )

    # Проверяем авторизацию (дублируем здесь для безопасности, хотя AuthFilter уже отработал)
    authorized = await is_user_authorized(state)

    if not authorized:
        bot_logger.info(f"{bot_tag} Пользователь не авторизован при обработке AI запроса")
        if isinstance(event, CallbackQuery):
            await event.answer("Сессия устарела. Пожалуйста, перезапустите бота командой /start", show_alert=True)
            message = event.message
        else:
            message = event

        await message.answer(
            "🔒 Для работы с AI-репетитором нужно привязать Telegram.\n"
            "Используйте команду /registration, чтобы ввести код из личного кабинета."
        )

        # Сбрасываем состояние
        await state.clear()
        return

    # Получаем данные пользователя из состояния
    state_data = await state.get_data()
    profile = state_data.get("profile", {})
    core_user_id = profile.get("core_user_id")

    if not core_user_id:
        bot_logger.warning(f"{bot_tag} Профиль пользователя отсутствует в состоянии")
        if isinstance(event, CallbackQuery):
            await event.answer("Ошибка загрузки вашего профиля. Попробуйте перезапустить бота командой /start",
                               show_alert=True)
            message = event.message
        else:
            message = event

        await message.answer("Ошибка загрузки вашего профиля. Попробуйте перезапустить бота командой /start")
        await state.clear()
        return

    # Подготовка payload
    payload = {
        "user_id": core_user_id,
        "platform": "telegram",
        "user_context": profile,
        "message_type": content_type,
        "user_telegram_id": event.from_user.id,
        "timestamp": int(time.time())
    }

    # Заполнение payload в зависимости от типа события
    await fill_payload_for_event(event, payload, state)

    # Отправка запроса в core
    ok, response = await core_post("/api/v1/ai/orchestrator/process/", payload)

    # Обработка ответа
    if ok:
        return await send_ai_response(event, response, state)
    else:
        return await handle_ai_error(event, response, state)


async def fill_payload_for_event(event, payload, state):
    """Заполнение payload данными из события"""
    if isinstance(event, CallbackQuery):
        payload.update({
            "callback_data": event.data,
            "message_id": event.message.message_id if event.message else None,
            "chat_id": event.message.chat.id if event.message else None
        })
    else:  # Message или MediaGroupEvent
        payload["chat_id"] = event.chat.id
        payload["message_id"] = event.message_id
        payload["user_telegram_id"] = event.from_user.id

        # Обработка разных типов сообщений
        if hasattr(event, 'media_info'):  # MediaGroupEvent
            payload.update({
                "media_group": event.media_info,
                "message_text": next((item.get("caption") for item in event.media_info if item.get("caption")), "")
            })
        elif event.text:
            payload["message_text"] = event.text

        elif event.photo:
            # Берем фото самого высокого качества
            photo = event.photo[-1]
            payload["photo"] = {
                "file_id": photo.file_id,
                "width": photo.width,
                "height": photo.height,
                "file_size": photo.file_size,
            }

            if event.caption:
                payload["message_text"] = event.caption

        elif event.document:
            payload["document"] = {
                "file_id": event.document.file_id,
                "file_name": event.document.file_name,
                "mime_type": event.document.mime_type,
                "file_size": event.document.file_size,
            }

            if event.caption:
                payload["message_text"] = event.caption

        elif event.audio:
            payload["audio"] = {
                "file_id": event.audio.file_id,
                "duration": event.audio.duration,
                "file_name": event.audio.file_name,
                "mime_type": event.audio.mime_type,
                "file_size": event.audio.file_size,
            }

            if event.caption:
                payload["message_text"] = event.caption

        elif event.voice:
            payload["voice"] = {
                "file_id": event.voice.file_id,
                "duration": event.voice.duration,
                "mime_type": event.voice.mime_type,
                "file_size": event.voice.file_size,
            }

        elif event.video:
            payload["video"] = {
                "file_id": event.video.file_id,
                "width": event.video.width,
                "height": event.video.height,
                "duration": event.video.duration,
                "file_name": event.video.file_name,
                "mime_type": event.video.mime_type,
                "file_size": event.video.file_size,
            }

            if event.caption:
                payload["message_text"] = event.caption


async def send_ai_response(event: Union[Message, CallbackQuery], response: dict, state: FSMContext):
    """Отправляет ответ от AI пользователю с поддержкой всех типов контента"""
    bot_tag = f"[{BOT_NAME}]"
    assistant_slug = get_assistant_slug(event.bot)
    last_message_update_text = get_update_text_for_response(response)

    # Определяем ID исходного сообщения, на которое отвечаем (для reply_to_message_id)
    if isinstance(event, CallbackQuery):
        reply_to_message_id = event.message.message_id if event.message else None
    else:  # Message
        reply_to_message_id = event.message_id

    # Формируем current_ai_response в правильном формате для сохранения
    current_ai_response = {
        "core_message_id": response.get("core_message_id"),
        "reply_to_message_id": reply_to_message_id
    }

    # Обработка медиа-групп в ответе
    if response.get("media_group"):
        return await send_media_group_response(
            event, response, state, assistant_slug,
            last_message_update_text, current_ai_response
        )

    # Обработка одиночного медиа
    if response.get("response_type") in ["photo", "voice", "video", "document", "audio", "sticker", "location",
                                         "contact", "poll"]:
        return await send_single_media_response(
            event, response, state, assistant_slug,
            last_message_update_text, current_ai_response
        )

    # Обработка текста - используем оригинальную функцию для сохранения совместимости
    return await reply_and_update_last_message(
        event=event,
        state=state,
        last_message_update_text=last_message_update_text,
        answer_text=response.get("response_message", ""),
        answer_keyboard=get_keyboard_from_response(response),
        current_ai_response=current_ai_response,
        assistant_slug=assistant_slug
    )


async def send_media_group_response(
        event: Union[Message, CallbackQuery],
        response: dict,
        state: FSMContext,
        assistant_slug: str,
        last_message_update_text: str,
        current_ai_response: dict
):
    """
    Отправляет медиа-группу (альбом) из ответа Core API.

    Особенности реализации:
    1. Поддерживает смешанные альбомы (фото + видео)
    2. Обрабатывает ошибки отправки
    3. Сохраняет информацию о всех сообщениях в альбоме
    4. Обновляет состояние FSM
    5. Использует Celery для асинхронного сохранения в базу
    """
    bot_tag = f"[{BOT_NAME}]"

    # Определяем целевой объект для отправки
    reply_target = event.message if isinstance(event, CallbackQuery) else event

    try:
        # Формируем альбом из медиа-элементов
        media_group = response.get("media_group", [])
        caption = response.get("response_message", "")
        keyboard_data = response.get("keyboard", {})

        if not media_group:
            bot_logger.error(f"{bot_tag} Пустая медиа-группа в ответе")
            # Отправляем текстовый fallback
            return await reply_and_update_last_message(
                event=event,
                state=state,
                last_message_update_text=f"{last_message_update_text}\n{NO_EMOJI}\tПустая медиа-группа",
                answer_text="Не удалось загрузить медиа-контент. Попробуйте еще раз.",
                answer_keyboard=None,
                current_ai_response=response,
                assistant_slug=assistant_slug
            )

        # Создаем медиа-группу
        media_builder = types.MediaGroupBuilder(caption=caption if caption else None)

        for media_item in media_group:
            media_type = media_item.get("type", "photo")
            media_url = media_item.get("url")

            if not media_url:
                continue

            if media_type == "photo":
                media_builder.add_photo(media=media_url)
            elif media_type == "video":
                media_builder.add_video(media=media_url)

        # Отправляем медиа-группу
        media_messages = await reply_target.answer_media_group(media=media_builder.build())

        # Берем первое сообщение для отображения клавиатуры и обновления состояния
        first_message = media_messages[0]

        # Отправляем клавиатуру отдельным сообщением, если она есть
        answer_keyboard = None
        if keyboard_data:
            try:
                # Конвертируем данные клавиатуры в InlineKeyboardMarkup
                buttons = []
                for button_data in keyboard_data.get("buttons", []):
                    buttons.append(types.InlineKeyboardButton(
                        text=button_data.get("text", ""),
                        callback_data=button_data.get("callback_data"),
                        url=button_data.get("url")
                    ))

                layout = keyboard_data.get("layout", [1])
                keyboard_rows = [buttons[i:i + layout[0]] for i in range(0, len(buttons), layout[0])]
                answer_keyboard = types.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

                # Отправляем клавиатуру отдельным сообщением
                keyboard_message = await reply_target.answer(
                    text="Выберите действие:",
                    reply_markup=answer_keyboard
                )

                # Обновляем состояние с информацией о сообщении с клавиатурой
                await state.update_data(keyboard_message_id=keyboard_message.message_id)

            except Exception as e:
                bot_logger.error(f"{bot_tag} Ошибка создания клавиатуры для медиа-группы: {str(e)}")

        # Обновляем предыдущее сообщение с отметкой
        data = await state.get_data()
        last_message = data.get("last_message")

        if last_message:
            try:
                await reply_target.bot.edit_message_text(
                    text=f"{last_message.get('text')}{last_message_update_text}",
                    chat_id=reply_target.chat.id,
                    message_id=last_message.get("id"),
                    reply_markup=None,
                    parse_mode=ParseMode.HTML
                )
            except TelegramBadRequest as e:
                bot_logger.warning(f"{bot_tag} Ошибка обновления предыдущего сообщения: {str(e)}")

        # Подготавливаем данные для сохранения в базу
        core_message_id = response.get("core_message_id")
        media_message_ids = [msg.message_id for msg in media_messages]

        payload = {
            "core_message_id": current_ai_response.get("core_message_id"),
            "reply_to_message_id": current_ai_response.get("reply_to_message_id"),
            # Сохраняем привязку к исходному сообщению
            "message_ids": media_message_ids,
            "type": "media_group",
            "text": caption,
            "assistant_slug": assistant_slug,
            "user_telegram_id": event.from_user.id,
            "metadata": {
                "media_count": len(media_messages),
                "photo_count": sum(1 for m in media_group if m.get("type") == "photo"),
                "video_count": sum(1 for m in media_group if m.get("type") == "video"),
                "response_type": "media_group",
                # Сохраняем данные о сообщениях для обратной связи
                "telegram_messages": [msg.model_dump() for msg in media_messages]
            }
        }

        # Асинхронное сохранение в базу через Celery
        process_save_message.delay(payload=payload)

        # Обновление FSM state
        await state.update_data(
            last_ai_message={
                "id": first_message.message_id,
                "text": caption[:100] + "..." if caption and len(caption) > 100 else caption,
                "type": "media_group",
                "media_ids": media_message_ids,
                "core_message_id": current_ai_response.get("core_message_id")
            },
            last_message={
                "id": first_message.message_id,
                "text": caption,
                "keyboard": answer_keyboard.model_dump_json() if answer_keyboard else None
            }
        )

        # Обновление предыдущего сообщения с отметкой
        data = await state.get_data()
        last_message = data.get("last_message")
        if last_message:
            try:
                await reply_target.bot.edit_message_text(
                    text=f"{last_message.get('text')}{last_message_update_text}",
                    chat_id=reply_target.chat.id,
                    message_id=last_message.get("id"),
                    reply_markup=None,
                    parse_mode=ParseMode.HTML
                )
            except TelegramBadRequest as e:
                bot_logger.warning(f"{bot_tag} Ошибка обновления предыдущего сообщения: {str(e)}")

        bot_logger.info(f"{bot_tag} Успешно отправлена медиа-группа из {len(media_messages)} элементов")
        return True

    except Exception as e:
        bot_logger.exception(f"{bot_tag} Ошибка при отправке медиа-группы: {str(e)}")
        # При ошибке используем fallback через оригинальную функцию
        return await reply_and_update_last_message(
            event=event,
            state=state,
            last_message_update_text=f"{last_message_update_text}\n{NO_EMOJI}\tОшибка отправки медиа",
            answer_text="Произошла ошибка при отправке медиа-контента. Пожалуйста, попробуйте еще раз.",
            answer_keyboard=None,
            current_ai_response=current_ai_response,  # Используем правильный current_ai_response
            assistant_slug=assistant_slug
        )


async def send_single_media_response(
        event: Union[Message, CallbackQuery],
        response: dict,
        state: FSMContext,
        assistant_slug: str,
        last_message_update_text: str,
        current_ai_response: dict
):
    """
    Отправляет одиночное медиа-сообщение из ответа Core API.

    Поддерживаемые типы:
    - photo: Изображения
    - document: Документы
    - audio: Аудиофайлы
    - voice: Голосовые сообщения
    - video: Видеофайлы
    - sticker: Стикер
    - location: Геолокация
    - contact: Контакт
    - poll: Опрос

    Особенности реализации:
    1. Единая точка обработки всех типов медиа
    2. Автоматическое определение типа медиа
    3. Поддержка caption и клавиатуры
    4. Асинхронное сохранение в базу через Celery
    5. Обновление состояния FSM
    """
    bot_tag = f"[{BOT_NAME}]"

    # Определяем целевой объект для отправки
    reply_target = event.message if isinstance(event, CallbackQuery) else event

    try:
        # Извлекаем данные из ответа
        response_type = response.get("response_type", "text")
        caption = response.get("response_message", "")
        keyboard_data = response.get("keyboard", {})
        core_message_id = response.get("core_message_id")

        # Конвертируем данные клавиатуры в InlineKeyboardMarkup
        answer_keyboard = get_keyboard_from_response(response)

        # Отправляем медиа в зависимости от типа
        sent_message = None

        if response_type == "photo":
            photo_url = response.get("photo_url")
            if photo_url:
                sent_message = await reply_target.answer_photo(
                    photo=photo_url,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=answer_keyboard
                )
            else:
                # Если нет URL фото, отправляем как текст
                sent_message = await reply_target.answer(
                    caption or "Изображение недоступно",
                    parse_mode=ParseMode.HTML,
                    reply_markup=answer_keyboard
                )

        elif response_type == "document":
            document_url = response.get("document_url")
            document_name = response.get("document_name", "document")
            if document_url:
                sent_message = await reply_target.answer_document(
                    document=document_url,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=answer_keyboard,
                    filename=document_name
                )
            else:
                sent_message = await reply_target.answer(
                    caption or "Документ недоступен",
                    parse_mode=ParseMode.HTML,
                    reply_markup=answer_keyboard
                )

        elif response_type == "audio":
            audio_url = response.get("audio_url")
            audio_title = response.get("audio_title", "Аудио")
            audio_performer = response.get("audio_performer", "Исполнитель")
            if audio_url:
                sent_message = await reply_target.answer_audio(
                    audio=audio_url,
                    caption=caption,
                    title=audio_title,
                    performer=audio_performer,
                    parse_mode=ParseMode.HTML,
                    reply_markup=answer_keyboard
                )
            else:
                sent_message = await reply_target.answer(
                    caption or "Аудио недоступно",
                    parse_mode=ParseMode.HTML,
                    reply_markup=answer_keyboard
                )

        elif response_type == "voice":
            voice_url = response.get("voice_url")
            if voice_url:
                sent_message = await reply_target.answer_voice(
                    voice=voice_url,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=answer_keyboard
                )
            else:
                sent_message = await reply_target.answer(
                    caption or "Голосовое сообщение недоступно",
                    parse_mode=ParseMode.HTML,
                    reply_markup=answer_keyboard
                )

        elif response_type == "video":
            video_url = response.get("video_url")
            if video_url:
                sent_message = await reply_target.answer_video(
                    video=video_url,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=answer_keyboard
                )
            else:
                sent_message = await reply_target.answer(
                    caption or "Видео недоступно",
                    parse_mode=ParseMode.HTML,
                    reply_markup=answer_keyboard
                )

        elif response_type == "sticker":
            sticker_id = response.get("sticker_id")
            if sticker_id:
                sent_message = await reply_target.answer_sticker(
                    sticker=sticker_id,
                    reply_markup=answer_keyboard
                )
                # Если есть текст, отправляем его отдельно
                if caption:
                    await reply_target.answer(
                        caption,
                        parse_mode=ParseMode.HTML,
                        reply_markup=answer_keyboard
                    )
            else:
                sent_message = await reply_target.answer(
                    caption or "Стикер недоступен",
                    parse_mode=ParseMode.HTML,
                    reply_markup=answer_keyboard
                )

        elif response_type == "location":
            latitude = response.get("latitude")
            longitude = response.get("longitude")
            if latitude and longitude:
                sent_message = await reply_target.answer_location(
                    latitude=float(latitude),
                    longitude=float(longitude),
                    reply_markup=answer_keyboard
                )
                # Если есть текст, отправляем его отдельно
                if caption:
                    await reply_target.answer(
                        caption,
                        parse_mode=ParseMode.HTML,
                        reply_markup=answer_keyboard
                    )
            else:
                sent_message = await reply_target.answer(
                    caption or "Локация недоступна",
                    parse_mode=ParseMode.HTML,
                    reply_markup=answer_keyboard
                )

        elif response_type == "contact":
            phone_number = response.get("phone_number")
            first_name = response.get("first_name", "Контакт")
            last_name = response.get("last_name", "")
            if phone_number:
                sent_message = await reply_target.answer_contact(
                    phone_number=phone_number,
                    first_name=first_name,
                    last_name=last_name,
                    reply_markup=answer_keyboard
                )
                # Если есть текст, отправляем его отдельно
                if caption:
                    await reply_target.answer(
                        caption,
                        parse_mode=ParseMode.HTML,
                        reply_markup=answer_keyboard
                    )
            else:
                sent_message = await reply_target.answer(
                    caption or "Контакт недоступен",
                    parse_mode=ParseMode.HTML,
                    reply_markup=answer_keyboard
                )

        elif response_type == "poll":
            question = response.get("question", "Опрос")
            options = response.get("options", ["Вариант 1", "Вариант 2"])
            is_anonymous = response.get("is_anonymous", True)

            if options and len(options) >= 2:
                sent_message = await reply_target.answer_poll(
                    question=question,
                    options=options,
                    is_anonymous=is_anonymous,
                    reply_markup=answer_keyboard
                )
                # Если есть текст, отправляем его отдельно
                if caption:
                    await reply_target.answer(
                        caption,
                        parse_mode=ParseMode.HTML,
                        reply_markup=answer_keyboard
                    )
            else:
                sent_message = await reply_target.answer(
                    caption or "Опрос недоступен",
                    parse_mode=ParseMode.HTML,
                    reply_markup=answer_keyboard
                )

        # Если медиа не удалось отправить или его нет
        if not sent_message:
            return await reply_and_update_last_message(
                event=event,
                state=state,
                last_message_update_text=f"{last_message_update_text}\n{NO_EMOJI}\tМедиа недоступно",
                answer_text=caption or "Запрошенный медиа-контент недоступен.",
                answer_keyboard=answer_keyboard,
                current_ai_response=response,
                assistant_slug=assistant_slug
            )

        # Обновляем предыдущее сообщение с отметкой
        data = await state.get_data()
        last_message = data.get("last_message")

        if last_message:
            try:
                await reply_target.bot.edit_message_text(
                    text=f"{last_message.get('text')}{last_message_update_text}",
                    chat_id=reply_target.chat.id,
                    message_id=last_message.get("id"),
                    reply_markup=None,
                    parse_mode=ParseMode.HTML
                )
            except TelegramBadRequest as e:
                bot_logger.warning(f"{bot_tag} Ошибка обновления предыдущего сообщения: {str(e)}")

        # Формируем payload для сохранения
        payload = {
            "core_message_id": current_ai_response.get("core_message_id"),
            "reply_to_message_id": current_ai_response.get("reply_to_message_id"),
            # Сохраняем привязку к исходному сообщению
            "message_id": sent_message.message_id,
            "telegram_message_id": sent_message.message_id,
            "type": response_type,
            "text": caption,
            "assistant_slug": assistant_slug,
            "user_telegram_id": event.from_user.id,
            "metadata": {
                **response,
                "response_type": response_type,
                "telegram_message": sent_message.model_dump()  # Сохраняем полные данные сообщения
            }
        }

        # Асинхронное сохранение в базу через Celery
        process_save_message.delay(payload=payload)

        # Обновление предыдущего сообщения с отметкой (как в оригинальной функции)
        data = await state.get_data()
        last_message = data.get("last_message")
        if last_message:
            try:
                await reply_target.bot.edit_message_text(
                    text=f"{last_message.get('text')}{last_message_update_text}",
                    chat_id=reply_target.chat.id,
                    message_id=last_message.get("id"),
                    reply_markup=None,
                    parse_mode=ParseMode.HTML
                )
            except TelegramBadRequest as e:
                bot_logger.warning(f"{bot_tag} Ошибка обновления предыдущего сообщения: {str(e)}")

        # Обновление FSM state
        await state.update_data(
            last_ai_message={
                "id": sent_message.message_id,
                "text": caption[:100] + "..." if caption and len(caption) > 100 else caption,
                "type": response_type,
                "core_message_id": current_ai_response.get("core_message_id")
            },
            last_message={
                "id": sent_message.message_id,
                "text": caption,
                "keyboard": answer_keyboard.model_dump_json() if answer_keyboard else None
            }
        )

        bot_logger.info(f"{bot_tag} Успешно отправлено медиа типа {response_type}")
        return True

    except Exception as e:
        bot_logger.exception(f"{bot_tag} Ошибка при отправке медиа {response}: {str(e)}")
        # При ошибке используем fallback через оригинальную функцию
        return await reply_and_update_last_message(
            event=event,
            state=state,
            last_message_update_text=f"{last_message_update_text}\n{NO_EMOJI}\tОшибка отправки медиа",
            answer_text="Произошла ошибка при отправке медиа-контента. Пожалуйста, попробуйте еще раз.",
            answer_keyboard=None,
            current_ai_response=current_ai_response,
            assistant_slug=assistant_slug
        )


def get_update_text_for_response(response):
    """Получение текста для обновления последнего сообщения"""
    response_type = response.get("response_type", "text")
    update_texts = {
        "media_group": f"\n{YES_EMOJI}\tМедиа-группа",
        "photo": f"\n{YES_EMOJI}\tИзображение",
        "document": f"\n{YES_EMOJI}\tДокумент",
        "audio": f"\n{YES_EMOJI}\tАудио",
        "voice": f"\n{YES_EMOJI}\tГолосовое сообщение",
        "video": f"\n{YES_EMOJI}\tВидео",
        "sticker": f"\n{YES_EMOJI}\tСтикер",
        "location": f"\n{YES_EMOJI}\tЛокация",
        "contact": f"\n{YES_EMOJI}\tКонтакт",
        "poll": f"\n{YES_EMOJI}\tОпрос",
    }
    return update_texts.get(response_type, f"\n{YES_EMOJI}\tОтвет получен")


def get_keyboard_from_response(response: dict) -> Optional[InlineKeyboardMarkup]:
    """
    Преобразует формат клавиатуры из ответа Core API в InlineKeyboardMarkup

    Ожидаемый формат в response:
    {
        "keyboard": {
            "type": "inline",  # или "reply"
            "buttons": [
                {"text": "Кнопка 1", "callback_data": "btn1"},
                {"text": "Кнопка 2", "url": "https://example.com"}
            ],
            "layout": [2]  # 2 кнопки в ряду
        }
    }

    Args:
        response: Ответ от Core API, содержащий данные о клавиатуре

    Returns:
        InlineKeyboardMarkup или None, если клавиатура отсутствует или неверного формата
    """
    keyboard_data = response.get("keyboard")
    if not keyboard_data or not isinstance(keyboard_data, dict):
        return None

    try:
        buttons_config = keyboard_data.get("buttons", [])
        layout = keyboard_data.get("layout", [1])

        if not buttons_config:
            return None

        # Формируем кнопки согласно layout
        keyboard_buttons = []
        current_row = []
        button_index = 0

        for button in buttons_config:
            button_text = button.get("text", "")
            callback_data = button.get("callback_data")
            url = button.get("url")

            if callback_data is not None:
                inline_button = InlineKeyboardButton(text=button_text, callback_data=callback_data)
            elif url is not None:
                inline_button = InlineKeyboardButton(text=button_text, url=url)
            else:
                # Пропускаем кнопки без callback_data и url
                continue

            current_row.append(inline_button)
            button_index += 1

            # Проверяем, нужно ли перейти на следующую строку согласно layout
            if button_index >= layout[0]:
                keyboard_buttons.append(current_row)
                current_row = []
                button_index = 0

        # Добавляем последнюю строку, если она не пустая
        if current_row:
            keyboard_buttons.append(current_row)

        if not keyboard_buttons:
            return None

        return InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    except Exception as e:
        bot_logger.error(f"[{BOT_NAME}] Ошибка создания клавиатуры из ответа: {str(e)}")
        return None


async def handle_ai_error(event: Union[Message, CallbackQuery], error_response: Union[str, dict], state: FSMContext):
    """Обрабатывает ошибки от AI-оркестратора"""
    bot_tag = f"[{BOT_NAME}]"

    # Формируем сообщение об ошибке
    if isinstance(error_response, dict):
        error_message = error_response.get("error", "Неизвестная ошибка")
        details = error_response.get("details", "")
        if details:
            error_message += f"\n\nДетали: {details}"
    else:
        error_message = str(error_response) or "Неизвестная ошибка при обработке запроса"

    # Логируем ошибку
    bot_logger.error(f"{bot_tag} Ошибка AI-оркестратора: {error_message}")

    # Форматируем сообщение для пользователя
    user_message = (
        "❌ <b>Ошибка обработки запроса</b>\n\n"
        "Извините, произошла ошибка при обработке вашего запроса.\n"
        "Попробуйте повторить запрос позже или обратитесь к поддержке."
    )

    # Отправляем сообщение об ошибке
    try:
        if isinstance(event, CallbackQuery):
            await event.answer("Произошла ошибка при обработке запроса", show_alert=True)
            reply_target = event.message
        else:
            reply_target = event

        # Если есть клавиатура в ответе об ошибке - используем ее
        keyboard = None
        if isinstance(error_response, dict) and error_response.get("keyboard"):
            try:
                # Используем функцию преобразования для создания клавиатуры
                keyboard = get_keyboard_from_response(error_response)
            except Exception as e:
                bot_logger.error(f"{bot_tag} Ошибка создания клавиатуры для сообщения об ошибке: {str(e)}")

        await reply_target.answer(
            user_message,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )

        # Обновляем состояние
        await state.update_data(last_error={
            "timestamp": time.time(),
            "message": error_message,
            "response": error_response
        })

    except Exception as e:
        bot_logger.exception(f"{bot_tag} Ошибка при отправке сообщения об ошибке: {str(e)}")