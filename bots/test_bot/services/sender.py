import json
import time
from typing import Optional, Dict, Union

import yaml
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, InlineKeyboardMarkup, CallbackQuery

from ..config import bot_logger
from ..tasks import process_save_message


async def reply_and_update_last_message(
        event: Union[Message, CallbackQuery],
        state,
        last_message_update_text: str,
        answer_text: str,
        answer_keyboard: Optional[InlineKeyboardMarkup] = None,
        message_effect_id: Optional[str] = None,
        current_ai_response: Optional[dict] = None,
        assistant_slug: Optional[str] = None
):
    """
    1) Обновляет прошлое сообщение с отметкой.
    2) Отправляет новый ответ пользователю через Telegram.
    3) Сохраняет ai_message_id в FSM state.
    4) Отправляет core_post для обновления сообщения в базе core.

    Args:
        event: объект aiogram Message или CallbackQuery
        state: FSMContext
        last_message_update_text: текст для добавления к прошлому сообщению
        answer_text: текст нового ответа
        current_ai_response: {
                        "core_message_id": ID сообщения engageai_core.chat.models.Message, которое нужно обновить,
                        "reply_to_core_message_id": telegram,
                    }

        answer_keyboard: клавиатура
        message_effect_id: id для эффекта при отправке (необязательно)
        assistant_slug: slug ассистента engageai_core.ai_assistant.models.AIAssistant для определения чата в core
    """

    bot_logger.debug(f"Структура event при получении: {type(event)}")
    bot_logger.debug(f"event: {yaml.dump(event.model_dump(), default_flow_style=False)}")

    # Определяем тип события и получаем необходимые данные
    if isinstance(event, CallbackQuery):
        reply_target = event.message
        message_id = event.id
        chat_id = event.message.chat.id
    else:  # Message
        reply_target = event
        message_id = event.message_id
        chat_id = event.chat.id

    data = await state.get_data()
    last_message = data.get("last_message")
    cache = data.get("telegram_auth_cache", {})
    core_user_id = cache.get("core_user_id")
    bot_tag = "[TelegramBot]"

    # Обновление прошлого сообщения с отметкой
    if last_message:
        try:
            await reply_target.bot.edit_message_text(
                text=f"{last_message.get('text')}{last_message_update_text}",
                chat_id=chat_id,
                message_id=last_message.get("id"),
                reply_markup=None,
                parse_mode=ParseMode.HTML
            )
        except TelegramBadRequest:
            pass

    # Отправка нового сообщения
    try:
        if message_effect_id:
            answer_message = await reply_target.answer(
                text=answer_text,
                parse_mode=ParseMode.HTML,
                reply_markup=answer_keyboard,
                message_effect_id=message_effect_id
            )
        else:
            answer_message = await reply_target.answer(
                text=answer_text,
                parse_mode=ParseMode.HTML,
                reply_markup=answer_keyboard
            )
    except TelegramBadRequest:
        answer_message = await reply_target.answer(
            text=answer_text,
            parse_mode=ParseMode.HTML,
            reply_markup=answer_keyboard,
        )

    # Сохранение ai_message_id
    # await TelegramBotMessageService.set_ai_message_id(state, answer_message.message_id)

    # 4) Отправка core_post для ОБНОВЛЕНИЯ существующего сообщения

    # print(f"reply_and_update EVENT\n", answer_message.model_dump_json(indent=4))

    if core_user_id:
        core_message_id = current_ai_response.get("core_message_id") if current_ai_response else None

        # Определяем тип ответа
        if isinstance(answer_message, CallbackQuery):
            answer_reply_target = answer_message.message
            telegram_user_id = answer_message.from_user.id

            if answer_message.message:
                chat_id = answer_message.message.chat.id
                answer_message_id = answer_message.message.message_id
            #
            else:
                chat_id = None
                answer_message_id = None
        else:  # Message
            answer_reply_target = answer_message
            telegram_user_id = answer_message.chat.id
            chat_id = answer_message.chat.id
            answer_message_id = answer_message.message_id

        payload = {
            "core_message_id": core_message_id,  # если не передано, то создастся новое engageai_core.chat.models.Message
            "reply_to_message_id": message_id,
            "message_id": answer_message_id,
            "telegram_message_id": answer_message_id,
            "text": answer_text,
            "assistant_slug": assistant_slug,
            "user_telegram_id": telegram_user_id,
            "metadata": answer_message.model_dump(),  # полный дамп сообщения telegram с клавиатурой
        }

        process_save_message.delay(payload=payload)

    # 5) Обновление FSM state для нового последнего сообщения
    await state.update_data(last_message={
        "id": answer_message.message_id,
        "text": answer_text,
        "keyboard": answer_keyboard.model_dump_json() if answer_keyboard else None,
        "parse_mode": ParseMode.HTML,
    })
