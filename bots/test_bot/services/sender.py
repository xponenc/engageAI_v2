from typing import Optional, Dict
from aiogram.enums import ParseMode
from aiogram.types import Message, InlineKeyboardMarkup

from bots.test_bot.services.api_process import core_post


async def reply_and_update_last_message(
        message: Message,
        state,
        last_message_update_text: str,
        answer_text: str,
        answer_keyboard: Optional[InlineKeyboardMarkup] = None,
        message_effect_id: Optional[str] = None,
) -> None:
    """
    Обновляет прошлое сообщение с отметкой, отправляет новый ответ,
    обновляет last_message в state и отправляет payload в core API.

    Args:
        message: объект aiogram.types.Message
        state: FSMContext
        last_message_update_text: текст для отметки предыдущего сообщения
        answer_text: текст ответа
        answer_keyboard: InlineKeyboardMarkup для ответа
        message_effect_id: необязательный ID эффекта сообщения
    """
    data: Dict = await state.get_data()
    last_message = data.get("last_message")

    # Обновление последнего сообщения
    if last_message:
        await message.bot.edit_message_text(
            text=f"{last_message.get('text')}{last_message_update_text}",
            chat_id=message.chat.id,
            message_id=last_message.get("id"),
            reply_markup=None,
            parse_mode=ParseMode.HTML
        )

    # Отправка нового сообщения
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

    # Обновление FSM state
    await state.update_data(last_message={
        "id": answer_message.message_id,
        "text": answer_text,
        "keyboard": answer_keyboard
    })

    # Подготовка payload для core API
    payload = {
        "telegram_message_id": answer_message.message_id,
        "chat_id": message.chat.id,
        "text": answer_text,
        "keyboard": answer_keyboard.to_python() if answer_keyboard else None
    }

    # Асинхронный вызов core_post
    await core_post(
        url="messages/store",
        payload=payload,
        context={"function": "reply_and_update_last_message"}
    )
