from typing import Optional, Dict

from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, InlineKeyboardMarkup


async def reply_and_update_last_message(
        message: Message,
        state: FSMContext,
        last_message_update_text: str,
        answer_text: str,
        answer_keyboard: Optional[InlineKeyboardMarkup] = None,
        message_effect_id: Optional[str] = None,
) -> None:
    """
    Обновляет прошлое сообщение с отметкой, отправляет новый ответ и обновляет last_message в state.
    """
    data: Dict = await state.get_data()
    last_message = data.get("last_message")

    # Обновление последнего сообщения
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

    # Отправка нового сообщения
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

    # Обновление FSM state
    await state.update_data(last_message={
        "id": answer_message.message_id,
        "text": answer_text,
        "keyboard": answer_keyboard
    })