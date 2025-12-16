# telegram_bot/renderer.py
"""
Модуль рендеринга контента из Core в Telegram.
Предназначен ТОЛЬКО для отображения: не содержит бизнес-логики, не управляет flow.
Все решения (что показать, как оценить) принимает Core.
"""

from aiogram import Bot
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
import logging

logger = logging.getLogger(__name__)


async def render_content_from_core(
        bot: Bot,
        user_id: int,
        core_payload: dict,
        state: FSMContext
) -> bool:
    """
    Отображает контент, полученный от Core, пользователю в Telegram.

    :param bot: экземпляр aiogram.Bot
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
        # 1. Сохраняем контекст шага в состоянии
        await state.update_data(
            session_id=core_payload["session_id"],
            step_id=core_payload["step_id"],
            metadata=core_payload.get("metadata", {}),
            audio_answer=core_payload.get("audio_answer", False)
        )

        # 2. Отправляем медиа (если есть)
        media_items = core_payload.get("media", [])
        for item in media_items:
            try:
                media_type = item.get("type")
                url = item.get("url")
                caption = item.get("caption", "")

                if not url:
                    logger.warning(f"Media item missing URL: {item}")
                    continue

                if media_type == "audio":
                    await bot.send_audio(chat_id=user_id, audio=url, caption=caption)
                elif media_type == "image":
                    await bot.send_photo(chat_id=user_id, photo=url, caption=caption)
                elif media_type == "video":
                    await bot.send_video(chat_id=user_id, video=url, caption=caption)
                elif media_type == "document":
                    filename = item.get("filename", url.split("/")[-1])
                    await bot.send_document(
                        chat_id=user_id,
                        document=url,
                        caption=caption,
                        # filename=filename
                    )
                else:
                    logger.warning(f"Unsupported media type: {media_type}")
            except TelegramAPIError as e:
                logger.error(f"Failed to send {item.get('type')} media: {str(e)}")
                await bot.send_message(
                    chat_id=user_id,
                    text=f"⚠️ Не удалось загрузить {item.get('type')}-файл. Попробуйте позже."
                )

        # 3. Отправляем текст с клавиатурой
        text = core_payload.get("text", "...")
        keyboards = core_payload.get("keyboards", [])

        if keyboards:
            kb_buttons = [[KeyboardButton(text=opt[0])] for opt in keyboards if opt]
            keyboard = ReplyKeyboardMarkup(
                keyboard=kb_buttons,
                resize_keyboard=True,
                one_time_keyboard=True
            )
            await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=keyboard
            )
        else:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=None  # Убираем предыдущую клавиатуру
            )

        return True

    except Exception as e:
        logger.exception(f"Rendering failed: {str(e)}")
        try:
            await bot.send_message(
                chat_id=user_id,
                text="⚠️ Произошла ошибка при отображении контента. Попробуйте позже."
            )
        except:
            pass
        return False