from typing import Optional, Dict
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, InlineKeyboardMarkup
from bots.test_bot.services.api_process import core_post
from bots.test_bot.services.telegram_message_service import TelegramBotMessageService


async def reply_and_update_last_message(
        message: Message,
        state,
        last_message_update_text: str,
        answer_text: str,
        core_message_id: int,
        answer_keyboard: Optional[InlineKeyboardMarkup] = None,
        message_effect_id: Optional[str] = None,
        assistant_slug: Optional[str] = None
):
    """
    1) Обновляет прошлое сообщение с отметкой.
    2) Отправляет новый ответ пользователю через Telegram.
    3) Сохраняет ai_message_id в FSM state.
    4) Отправляет core_post для обновления сообщения в базе core.

    Args:
        message: объект aiogram Message
        state: FSMContext
        last_message_update_text: текст для добавления к прошлому сообщению
        answer_text: текст нового ответа
        core_message_id: ID сообщения engageai_core.chat.models.Message, которое нужно обновить
        answer_keyboard: клавиатура
        message_effect_id: id для эффекта при отправке (необязательно)
        assistant_slug: slug ассистента engageai_core.ai_assistant.models.AIAssistant для определения чата в core
    """
    data: Dict = await state.get_data()
    last_message = data.get("last_message")
    bot_tag = "[TelegramBot]"

    # 1) Обновление прошлого сообщения с отметкой
    if last_message:
        try:
            await message.bot.edit_message_text(
                text=f"{last_message.get('text')}{last_message_update_text}",
                chat_id=message.chat.id,
                message_id=last_message.get("id"),
                reply_markup=None,
                parse_mode=ParseMode.HTML
            )
        except TelegramBadRequest:
            pass

    # 2) Отправка нового сообщения
    try:
        if message_effect_id:
            answer_message = await message.answer(
                text=answer_text,
                parse_mode=ParseMode.HTML,
                reply_markup=answer_keyboard,
                message_effect_id=message_effect_id
            )
        else:
            answer_message = await message.answer(
                text=answer_text,
                parse_mode=ParseMode.HTML,
                reply_markup=answer_keyboard
            )
    except TelegramBadRequest:
        answer_message = await message.answer(
            text=answer_text,
            parse_mode=ParseMode.HTML,
            reply_markup=answer_keyboard
        )

    # 3) Сохранение ai_message_id
    await TelegramBotMessageService.set_ai_message_id(state, answer_message.message_id)

    # 4) Отправка core_post для ОБНОВЛЕНИЯ существующего сообщения
    payload = {
        "core_message_id": core_message_id,  # Используем для обновления
        "telegram_message_id": answer_message.message_id,
        "chat_id": message.chat.id,
        "text": answer_text,
        "assistant_slug": assistant_slug,  # Передаем для поиска чата
        "user_telegram_id": message.from_user.id,  # Передаем для поиска пользователя
        "metadata": {
            "raw_message": answer_message.model_dump(),  # Полные данные отправленного сообщения
            "keyboard": answer_keyboard.model_dump() if answer_keyboard else None,
            "message_effect_id": message_effect_id
        }
    }
    await core_post(url="/chat/api/v1/telegram/message/update/", payload=payload,
                    context={"message_id": answer_message.message_id})

    # 5) Обновление FSM state для нового последнего сообщения
    await state.update_data(last_message={
        "id": answer_message.message_id,
        "text": answer_text,
        "keyboard": answer_keyboard.model_dump_json() if answer_keyboard else None
    })