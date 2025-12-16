# telegram_bot/renderer.py
"""
Модуль рендеринга контента из Core в Telegram.
Предназначен ТОЛЬКО для отображения: не содержит бизнес-логики, не управляет flow.
Все решения (что показать, как оценить) принимает Core.
"""
from pprint import pprint

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
import logging

from bots.test_bot.config import bot_logger


async def render_content_from_core(
        bot: Bot,
        assistant_slug: str,
        user_id: int,
        core_payload: dict,
        state: FSMContext
) -> bool:
    """
    Отображает контент, полученный от Core, пользователю в Telegram.

    :param bot: экземпляр aiogram.Bot
    :param assistant_slug: slug к ai_assistant.models.AIAssistant на который будет направлен запрос
    :param user_id: Telegram ID пользователя
    :param core_payload: данные от Core (структура описана ниже)
    :param state: FSMContext для управления состоянием бота
    :return: успешность операции (True/False)

    ОЖИДАЕМАЯ СТРУКТУРА core_payload:
    {
        "session_id": "строка",  # обязательно
        "step_id": "строка",     # обязательно
        "text": "строка",        # опционально
        "keyboards": [           # опционально
            ["Текст кнопки 1"],
            ["Текст кнопки 2"]
        ],
        "audio_answer": false,   # true → ожидать голосовое сообщение
        "media": [               # опционально
            {
                "type": "audio|image|video|document",
                "url": "https://...",
                "caption": "Подпись (опционально)",
                "filename": "имя_файла.pdf"  # только для document
            }
        ],
        "metadata": { ... }      # любые данные для последующей отправки в Core
    }
    """

    try:
        message_data = core_payload.get("data", {})
        core_answer = core_payload.get("core_answer", {})
        await state.update_data(
            message_data=message_data,
            core_answer=core_answer,
            audio_answer=core_payload.get("audio_answer", False)
        )
        data = await state.get_data()
        bot_logger.info(f"RENDER STATE_DATA\n\n{data}")

        # 2. Отправляем медиа (если есть)
        media_items = message_data.get("media", [])
        for item in media_items:
            try:
                media_type = item.get("type")
                url = item.get("url")
                caption = item.get("caption", "")

                if not url:
                    bot_logger.warning(f"Media item missing URL: {item}")
                    continue

                if media_type == "audio":
                    await bot.send_audio(chat_id=user_id, audio=url, caption=caption)
                elif media_type == "image":
                    await bot.send_photo(chat_id=user_id, photo=url, caption=caption)
                elif media_type == "video":
                    await bot.send_video(chat_id=user_id, video=url, caption=caption)
                elif media_type == "document":
                    # filename = item.get("filename", url.split("/")[-1])
                    await bot.send_document(
                        chat_id=user_id,
                        document=url,
                        caption=caption,
                        # filename=filename
                    )
                else:
                    bot_logger.warning(f"Unsupported media type: {media_type}")
            except TelegramAPIError as e:
                bot_logger.error(f"Failed to send {item.get('type')} media: {str(e)}")
                await bot.send_message(
                    chat_id=user_id,
                    text=f"⚠️ Не удалось загрузить {item.get('type')}-файл. Попробуйте позже."
                )

        # 3. Отправляем текст с клавиатурой
        parse_mode_config = message_data.get("parse_mode")
        if parse_mode_config == "Markdown":
            parse_mode = ParseMode.MARKDOWN
        else:
            parse_mode = ParseMode.HTML

        text = message_data.get("text", "...")

        keyboard_config = message_data.get("keyboard")
        keyboard = build_keyboard(keyboard_config)

        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=keyboard,
            parse_mode=parse_mode
        )
        return True

    except Exception as e:
        bot_logger.exception(f"Rendering failed: {str(e)}")
        try:
            await bot.send_message(
                chat_id=user_id,
                text="⚠️ Произошла ошибка при отображении контента. Попробуйте позже."
            )
        except:
            pass
        return False


def build_keyboard(keyboard_config):
    if not keyboard_config:
        return None

    kb_type = keyboard_config.get("type", "reply")
    buttons = keyboard_config.get("buttons", [])
    layout = keyboard_config.get("layout", [1])

    if kb_type == "inline":
        # Создаём плоский список кнопок
        aiogram_buttons = []
        for btn in buttons:
            if "callback_data" in btn:
                aiogram_buttons.append(
                    InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"])
                )
            elif "url" in btn:
                aiogram_buttons.append(
                    InlineKeyboardButton(text=btn["text"], url=btn["url"].strip())
                )
            else:
                # Без действия — не рекомендуется, но можно опустить или использовать пустой callback
                aiogram_buttons.append(
                    InlineKeyboardButton(text=btn["text"], callback_data="")
                )

        # Группируем по layout
        rows = []
        idx = 0
        for row_size in layout:
            rows.append(aiogram_buttons[idx:idx + row_size])
            idx += row_size
        if idx < len(aiogram_buttons):
            rows.append(aiogram_buttons[idx:])

        return InlineKeyboardMarkup(inline_keyboard=rows)

    elif kb_type == "reply":
        # Только текстовые кнопки
        aiogram_buttons = [KeyboardButton(text=btn["text"]) for btn in buttons if "text" in btn]

        rows = []
        idx = 0
        for row_size in layout:
            rows.append(aiogram_buttons[idx:idx + row_size])
            idx += row_size
        if idx < len(aiogram_buttons):
            rows.append(aiogram_buttons[idx:])

        return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)

    return None
