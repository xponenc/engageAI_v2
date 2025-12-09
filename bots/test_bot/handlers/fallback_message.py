import asyncio

from aiogram import Router, F, types
from aiogram.types import Message, CallbackQuery, ContentType, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from typing import Union, Optional
import time
import html
import json
from aiogram.utils.media_group import MediaGroupBuilder
from bots.test_bot.filters.require_auth import AuthFilter
from bots.test_bot.services.api_process import core_post, auto_context
from bots.test_bot.config import bot_logger, BOT_NAME, AUTH_CACHE_TTL_SECONDS, NO_EMOJI, EXCLAMATION_EMOJI
from bots.services.utils import get_assistant_slug
from bots.test_bot.services.sender import reply_and_update_last_message
from bots.test_bot.services.utils import is_user_authorized

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
        # Проверяем, есть ли уже активная группа с таким ID
        state_data = await state.get_data()
        current_group_id = state_data.get("current_media_group_id")

        if current_group_id != message.media_group_id:
            # Новая группа - сбрасываем предыдущие данные
            await state.update_data(
                current_media_group_id=message.media_group_id,
                media_items=[],
                media_group_start_time=time.time()
            )

        # Добавляем текущее сообщение в группу
        media_items = (await state.get_data()).get("media_items", [])
        media_items.append(message)
        await state.update_data(media_items=media_items)

        # Запускаем таймер для обработки группы (только для первой медиа в группе)
        if len(media_items) == 1:
            asyncio.create_task(process_media_group_after_timeout(state))
        return

    # Если мы в состоянии ожидания медиа-группы, но получили не-медиа сообщение
    current_state = await state.get_state()
    if current_state == OrchestratorState.waiting_media_group.state:
        # Обрабатываем накопленную группу
        await process_media_group(message, state)
        # И сбрасываем состояние для обработки текущего сообщения
        await state.set_state(OrchestratorState.waiting_response)

    # Устанавливаем состояние Orchestrator для обычных сообщений
    await state.set_state(OrchestratorState.waiting_response)

    # Обрабатываем запрос
    return await process_ai_request(message, state)


async def process_media_group_after_timeout(message: Message, state: FSMContext):
    """Обрабатывает медиа-группу через короткий таймаут"""
    await asyncio.sleep(1.0)  # даем время на получение всех элементов

    current_state = await state.get_state()
    if current_state != OrchestratorState.waiting_media_group.state:
        return

    state_data = await state.get_data()
    media_items = state_data.get("media_items", [])

    if not media_items:
        return

    # Проверяем, что это последнее сообщение группы (не пришло новых за таймаут)
    if time.time() - state_data.get("media_group_start_time", 0) > 0.8:
        # Используем последнее сообщение в группе как отправную точку
        last_message = media_items[-1]
        await process_media_group(last_message, state)

        # Сбрасываем состояние
        await state.update_data(current_media_group_id=None, media_items=[])
        await state.set_state(OrchestratorState.waiting_response)



# Обработчик для завершения медиа-группы по таймеру или при получении не-медиа сообщения
async def process_media_group(message: Message, state: FSMContext):
    """Обрабатывает накопленную медиа-группу"""
    bot_tag = f"[{BOT_NAME}]"
    state_data = await state.get_data()
    media_items = state_data.get("media_items", [])
    media_group_id = state_data.get("current_media_group_id")

    if not media_items:
        bot_logger.warning(f"{bot_tag} Попытка обработать пустую медиа-группу")
        return

    bot_logger.info(f"{bot_tag} Обработка медиа-группы {media_group_id} с {len(media_items)} элементами")

    # Собираем информацию о всех медиа в группе
    media_info = []
    for item in media_items:
        if item.photo:
            photo = item.photo[-1]  # Самое качественное фото
            media_info.append({
                "type": "photo",
                "file_id": photo.file_id,
                "width": photo.width,
                "height": photo.height,
                "file_size": photo.file_size,
                "caption": item.caption
            })
        elif item.video:
            media_info.append({
                "type": "video",
                "file_id": item.video.file_id,
                "width": item.video.width,
                "height": item.video.height,
                "duration": item.video.duration,
                "caption": item.caption
            })

    # Формируем событие-заглушку для передачи в process_ai_request
    class MediaGroupEvent:
        def __init__(self, message, media_info):
            self.message = message
            self.media_info = media_info
            self.from_user = message.from_user
            self.chat = message.chat

        def __getattr__(self, name):
            # Проксируем все остальные атрибуты к исходному сообщению
            return getattr(self.message, name)

    media_group_event = MediaGroupEvent(message, media_info)

    # Обрабатываем медиа-группу
    await process_ai_request(media_group_event, state)


# Обработчик callback от AI-ответов (кнопки в сообщениях AI)
@fallback_router.callback_query(AuthFilter())
async def handle_orchestrator_callback(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает callback от кнопок в AI-ответах"""
    bot_tag = f"[{BOT_NAME}]"
    bot_logger.info(f"{bot_tag} Получен callback для AI обработки от {callback.from_user.id}: {callback.data}")

    await callback.answer()
    await state.set_state(OrchestratorState.processing_callback)

    # Обрабатываем callback как запрос к AI
    return await process_ai_request(callback, state)


@auto_context()
async def process_ai_request(event: Union[Message, CallbackQuery, 'MediaGroupEvent'], state: FSMContext, **kwargs):
    """Универсальная обработка запросов к AI-оркестратору"""
    bot_tag = f"[{BOT_NAME}]"
    assistant_slug = get_assistant_slug(event.bot)

    # Определяем тип контента
    if hasattr(event, 'content_type'):
        content_type = event.content_type
    elif isinstance(event, CallbackQuery):
        content_type = "callback"
    else:
        content_type = "unknown"

    # Проверяем авторизацию
    authorized = await is_user_authorized(state)

    if not authorized:
        bot_logger.info(f"{bot_tag} Пользователь не авторизован при обработке AI запроса")
        # Сбрасываем состояние
        await state.clear()
        return

    # Получаем данные пользователя из состояния
    data = await state.get_data()
    telegram_auth_cache = data.get("telegram_auth_cache", {})
    core_user_id = telegram_auth_cache.get("core_user_id")

    # Подготавливаем payload для запроса к AI-оркестратору
    payload = {
        "core_user_id": core_user_id,
        "platform": "telegram",
        "message_type": content_type, # TODO посмотреть нужность во view
        "timestamp": int(time.time()),
    }

    # Определяем отправителя и получаем дополнительные данные
    if isinstance(event, CallbackQuery):
        # Обработка callback

        payload["callback_data"] = event.data
        payload["message_id"] = event.id
        payload["chat_id"] = event.message.chat.id if event.message else None
        payload["user_telegram_id"] = event.from_user.id

    elif hasattr(event, 'media_info') and isinstance(event.media_info, list):
        # Обработка медиа-группы
        payload["message_type"] = "media_group"
        payload["media_group_id"] = (await state.get_data()).get("media_group_id")
        payload["media_items"] = event.media_info

        # Берем caption из первого элемента с caption
        caption = next((item.get("caption") for item in event.media_info if item.get("caption")), None)
        if caption:
            payload["message_text"] = caption

        # Определяем chat_id и user_telegram_id из первого сообщения
        payload["chat_id"] = event.chat.id
        payload["user_telegram_id"] = event.from_user.id

    else:  # Message
        payload["chat_id"] = event.chat.id
        payload["message_id"] = event.message_id
        payload["user_telegram_id"] = event.from_user.id

        # Обработка разных типов сообщений
        if event.text:
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

    # Логируем payload для отладки
    bot_logger.debug(
        f"{bot_tag} Payload для AI-оркестратора: {json.dumps(payload, indent=2, ensure_ascii=False)[:500]}...")


    bot_logger.debug(f"{bot_tag} Отправка запроса к AI-оркестратору для user_id={core_user_id}")
    ok, response = await core_post("/api/v1/ai/orchestrator/process/", payload)

    if not ok:
        error_msg = response if isinstance(response, str) else "Ошибка обработки запроса"
        bot_logger.error(f"{bot_tag} Ошибка AI-оркестратора: {error_msg}")

        answer_text = "Извините, сейчас я не могу обработать ваш запрос. Попробуйте позже."
        last_message_update_text = f"\n\n{EXCLAMATION_EMOJI}\tОшибка запроса\n"

        await reply_and_update_last_message(
            event=event,
            state=state,
            last_message_update_text=last_message_update_text,
            answer_text=answer_text,
            answer_keyboard=None,
            current_ai_response=None,
            assistant_slug=assistant_slug,
        )
        return

    if not isinstance(response, dict):
        bot_logger.error(f"{bot_tag} Некорректный формат ответа от AI-оркестратора: {response}")

        answer_text = "Извините, я получил некорректный ответ от системы. Попробуйте позже."
        last_message_update_text = f"\n\n{EXCLAMATION_EMOJI}\tОшибка запроса\n"

        await reply_and_update_last_message(
            event=event,
            state=state,
            last_message_update_text=last_message_update_text,
            answer_text=answer_text,
            answer_keyboard=None,
            current_ai_response=None,
            assistant_slug=assistant_slug,
        )
        return

    # Обрабатываем ответ от AI
    return await processing_ai_response(event, response, state)


async def processing_ai_response(event: Union[Message, CallbackQuery], response: dict, state: FSMContext):
    """Универсальный обработчик ответа от Core API"""
    bot_tag = f"[{BOT_NAME}]"

    # Извлекаем данные из ответа
    metadata = response.get("metadata", {})
    content = response.get("content", {})
    effects = response.get("effects", {})
    core_message_id = metadata.get("message_id")

    # Получаем целевой объект для ответа
    reply_target = event.message if isinstance(event, CallbackQuery) else event

    try:
        # Обработка разных типов контента
        if content.get("type") == "media_group":
            sent_messages = await send_media_group(reply_target, content, effects)
            sent_message = sent_messages[0] if sent_messages else None

        elif content.get("type") == "text":
            sent_message = await send_text_message(reply_target, content, effects)

        elif content.get("type") in ["photo", "document", "audio", "voice", "video"]:
            sent_message = await send_single_media(reply_target, content, effects)

        else:
            # Обработка неизвестного типа или ошибка
            fallback_text = content.get("text",
                                        "Я получил ваше сообщение, но пока не могу обработать этот тип контента.")
            sent_message = await reply_target.answer(
                fallback_text,
                parse_mode=ParseMode.HTML,
                reply_markup=generate_keyboard(content.get("keyboard"))
            )

        # Обновляем состояние
        if sent_message:
            await update_state_after_response(state, sent_message, response)
            bot_logger.info(f"{bot_tag} Отправлен ответ типа {content.get('type')} на сообщение")

    except Exception as e:
        await handle_response_error(event, e, bot_tag)


async def send_media_group(reply_target, content: dict, effects: dict):
    """Отправка медиа-группы"""
    media_builder = MediaGroupBuilder(caption=content.get("text", ""))

    for media_item in content.get("media", []):
        if media_item.get("type") == "photo":
            media_builder.add_photo(media_item["url"])
        elif media_item.get("type") == "video":
            media_builder.add_video(media_item["url"])

    return await reply_target.answer_media_group(media_builder.build())


async def send_text_message(reply_target, content: dict, effects: dict):
    """Отправка текстового сообщения"""
    return await reply_target.answer(
        content.get("text", ""),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=generate_keyboard(content.get("keyboard")),
        message_effect_id=effects.get("message_effect_id")
    )


async def send_single_media(reply_target, content: dict, effects: dict):
    """Отправка одиночного медиа-файла"""
    media_type = content.get("type")
    media_item = content.get("media", [{}])[0]
    caption = content.get("text", "")

    if media_type == "photo":
        return await reply_target.answer_photo(
            photo=media_item.get("url"),
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_keyboard(content.get("keyboard")),
            message_effect_id=effects.get("message_effect_id")
        )

    elif media_type == "voice":
        return await reply_target.answer_voice(
            voice=media_item.get("url"),
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_keyboard(content.get("keyboard")),
            message_effect_id=effects.get("message_effect_id")
        )

    # Другие типы медиа...
    return await reply_target.answer(
        caption or "Медиа-контент недоступен",
        parse_mode=ParseMode.HTML,
        reply_markup=generate_keyboard(content.get("keyboard")),
        message_effect_id=effects.get("message_effect_id")
    )


def generate_keyboard(keyboard_config: Optional[dict]) -> Optional[InlineKeyboardMarkup]:
    """Генерация клавиатуры из конфигурации"""
    if not keyboard_config:
        return None

    buttons = []
    layout = keyboard_config.get("layout", [1])
    current_row = []
    button_index = 0

    for button in keyboard_config.get("buttons", []):
        current_row.append(InlineKeyboardButton(
            text=button.get("text", ""),
            callback_data=button.get("callback_data"),
            url=button.get("url")
        ))
        button_index += 1

        if button_index >= layout[0]:
            buttons.append(current_row)
            current_row = []
            button_index = 0

    if current_row:
        buttons.append(current_row)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def update_state_after_response(state: FSMContext, sent_message, response: dict):
    """Обновление состояния после отправки ответа"""
    metadata = response.get("metadata", {})
    content = response.get("content", {})

    await state.update_data(last_ai_message={
        "id": sent_message.message_id,
        "text": content.get("text", "")[:100],  # Первые 100 символов для логов
        "type": content.get("type", "text"),
        "core_message_id": metadata.get("message_id"),
        "conversation_id": metadata.get("conversation_id")
    })

    # Если нужно сохранить в базу
    if response.get("actions", {}).get("save_to_history", True):
        from bots.test_bot.tasks import process_save_message
        process_save_message.delay(
            payload={
                "core_message_id": metadata.get("message_id"),
                "message_id": sent_message.message_id,
                "text": content.get("text", ""),
                "assistant_slug": metadata.get("assistant_slug"),
                "metadata": sent_message.model_dump()
            }
        )


async def handle_response_error(event, error, bot_tag):
    """Обработка ошибок при отправке ответа"""
    bot_logger.error(f"{bot_tag} Ошибка при отправке ответа: {str(error)}")
    error_text = "Произошла ошибка при отправке ответа. Пожалуйста, попробуйте еще раз."

    if isinstance(event, CallbackQuery):
        await event.answer(error_text, show_alert=True)
        reply_target = event.message
    else:
        reply_target = event

    await reply_target.answer(
        error_text,
        parse_mode=ParseMode.HTML
    )