"""
Модуль рендеринга контента из Core в Telegram.
Предназначен ТОЛЬКО для отображения: не содержит бизнес-логики, не управляет flow.
Все решения (что показать, как оценить) принимает Core.
"""

from aiogram.enums import ParseMode
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, Message, \
    ReplyKeyboardRemove
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext

from bots.test_bot.config import bot_logger, BOT_NAME


#
# async def render_content_from_core(
#         reply_target: Message,
#         core_payload: dict,
#         state: FSMContext
# ) -> Message:
#     """
#     Отображает контент, полученный от Core, пользователю в Telegram.
#
#     :param reply_target: экземпляр Message
#     :param core_payload: данные от Core (структура описана ниже)
#     :param state: FSMContext для управления состоянием бота
#     :return: отправленное Message
#
#     ОЖИДАЕМАЯ СТРУКТУРА core_payload:
#     {
#         "session_id": "строка",  # обязательно
#         "step_id": "строка",     # обязательно
#         "text": "строка",        # опционально
#         "keyboards": [           # опционально
#             ["Текст кнопки 1"],
#             ["Текст кнопки 2"]
#         ],
#         "audio_answer": false,   # true → ожидать голосовое сообщение
#         "media": [               # опционально
#             {
#                 "type": "audio|image|video|document",
#                 "url": "https://...",
#                 "caption": "Подпись (опционально)",
#                 "filename": "имя_файла.pdf"  # только для document
#             }
#         ],
#         "metadata": { ... }      # любые данные для последующей отправки в Core
#     }
#     """
#     bot_tag = f"[{BOT_NAME}]"
#
#     bot_logger.debug(f"{bot_tag} CORE PAYLOAD\n{core_payload}")
#
#     answer_message = None
#     try:
#         message_data = core_payload.get("data", {})
#         core_answer = core_payload.get("core_answer", {})
#         await state.update_data(
#             message_data=message_data,
#             core_answer=core_answer,
#             audio_answer=core_payload.get("audio_answer", False)
#         )
#         data = await state.get_data()
#         bot_logger.info(f"{bot_tag} RENDER STATE_DATA\n\n{data}")
#
#         # 2. Отправляем медиа (если есть)
#         media_items = message_data.get("media", [])
#         for item in media_items:
#             try:
#                 media_type = item.get("type")
#                 url = item.get("url")
#                 caption = item.get("caption", "")
#
#                 if not url:
#                     bot_logger.warning(f"{bot_tag} Media item missing URL: {item}")
#                     continue
#
#                 if media_type == "audio":
#                     answer_message = await reply_target.answer_audio(audio=url, caption=caption)
#
#                 elif media_type == "image":
#                     answer_message = await reply_target.answer_photo(photo=url, caption=caption)
#
#                 elif media_type == "video":
#                     answer_message = await reply_target.answer_video(video=url, caption=caption)
#
#                 elif media_type == "document":
#                     answer_message = await reply_target.answer_document(document=url, caption=caption)
#
#                 else:
#                     bot_logger.warning(f"{bot_tag} Unsupported media type: {media_type} | item={item}")
#
#             except TelegramAPIError as e:
#                 bot_logger.error(
#                     f"{bot_tag} Failed to send media | "
#                     f"type={media_type} url={url} payload={item} error={e}",
#                     exc_info=True,
#                 )
#                 answer_message = await reply_target.answer(
#                     text=f"⚠️ Не удалось загрузить {media_type}-файл."
#                 )
#
#         # 3. Отправляем текст с клавиатурой
#         parse_mode_config = message_data.get("parse_mode")
#         message_effect_id = message_data.get("message_effect_id")
#
#         parse_mode_map = {
#             "Markdown": ParseMode.MARKDOWN,
#             "HTML": ParseMode.HTML,
#         }
#
#         parse_mode = parse_mode_map.get(parse_mode_config, ParseMode.HTML)
#
#         answer_text = message_data.get("text", "...")
#
#         keyboard_config = message_data.get("keyboard")
#         answer_keyboard = build_keyboard(keyboard_config)
#
#         try:
#             if message_effect_id:
#                 answer_message = await reply_target.answer(
#                     text=answer_text,
#                     parse_mode=ParseMode.HTML,
#                     reply_markup=answer_keyboard,
#                     message_effect_id=message_effect_id
#                 )
#             else:
#                 answer_message = await reply_target.answer(
#                     text=answer_text,
#                     parse_mode=parse_mode,
#                     reply_markup=answer_keyboard
#                 )
#         except TelegramBadRequest:
#             answer_message = await reply_target.answer(
#                 text=answer_text,
#                 parse_mode=ParseMode.HTML,
#                 reply_markup=answer_keyboard,
#             )
#         return answer_message
#
#     except Exception as e:
#         bot_logger.exception(f"{bot_tag} Rendering failed for {core_payload=}:\n {str(e)}")
#         try:
#             answer_message = await reply_target.answer(
#                 text="⚠️ Произошла ошибка при отображении контента. Попробуйте позже."
#             )
#         except:
#             pass
#         return answer_message


async def render_content_from_core(
        reply_target: Message,
        state: FSMContext
) -> Message:
    """
    Отображает контент от Core пользователю и сохраняет snapshot сообщения.
    Возвращает последнее отправленное сообщение (Message).

    Snapshot last_message хранится в state в формате:
    {
        "id": message_id,
        "text": "...",
        "keyboard": JSON или None,
        "parse_mode": ParseMode.HTML/ParseMode.MARKDOWN
    }
    """
    bot_tag = f"[{BOT_NAME}]"
    state_data = await state.get_data()
    bot_logger.debug(f"{bot_tag} STATE_DATA\n{state_data}")

    core_answer = state_data.get("core_answer", {})

    answer_message: Message | None = None
    answer_text = "..."  # default
    answer_keyboard = None
    parse_mode = ParseMode.HTML

    try:

        # -----------------------------
        # 1. Отправка медиа (best-effort)
        # -----------------------------
        media_items = core_answer.get("media", [])
        for item in media_items:
            media_type = item.get("type")
            url = item.get("url")
            caption = item.get("caption", "...")

            if not url:
                bot_logger.warning(f"{bot_tag} Media item missing URL: {item}")
                continue

            try:
                if media_type == "audio":
                    answer_message = await reply_target.answer_audio(audio=url, caption=caption)
                elif media_type == "image":
                    answer_message = await reply_target.answer_photo(photo=url, caption=caption)
                elif media_type == "video":
                    answer_message = await reply_target.answer_video(video=url, caption=caption)
                elif media_type == "document":
                    answer_message = await reply_target.answer_document(document=url, caption=caption)
                else:
                    bot_logger.warning(f"{bot_tag} Unsupported media type: {media_type} | item={item}")

            except TelegramAPIError as e:
                bot_logger.error(
                    f"{bot_tag} Failed to send media | type={media_type} url={url} payload={item} error={e}",
                    exc_info=True,
                )
                # Сообщение пользователю о неудаче
                try:
                    answer_message = await reply_target.answer(
                        text=f"⚠️ Не удалось загрузить {media_type}-файл."
                    )
                except Exception:
                    bot_logger.exception(f"{bot_tag} Failed fallback message for media error")

        # -----------------------------
        # 2. Отправка текста + клавиатура
        # -----------------------------
        parse_mode_map = {"Markdown": ParseMode.MARKDOWN, "HTML": ParseMode.HTML}
        parse_mode = parse_mode_map.get(core_answer.get("parse_mode"), ParseMode.HTML)

        message_effect_id = core_answer.get("message_effect_id")
        answer_text = core_answer.get("text", "...")
        answer_keyboard = build_keyboard(core_answer.get("keyboard"))

        try:
            if message_effect_id:
                answer_message = await reply_target.answer(
                    text=answer_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=answer_keyboard if answer_keyboard else ReplyKeyboardRemove(),
                    message_effect_id=message_effect_id
                )
            else:
                answer_message = await reply_target.answer(
                    text=answer_text,
                    parse_mode=parse_mode,
                    reply_markup=answer_keyboard
                )
        except TelegramBadRequest:
            # fallback
            answer_message = await reply_target.answer(
                text=answer_text,
                parse_mode=ParseMode.HTML,
                reply_markup=answer_keyboard,
            )

    except Exception as e:
        bot_logger.exception(f"{bot_tag} Rendering failed for core_payload={core_answer=} | {e}")
        try:
            answer_text = "⚠️ Произошла ошибка при отображении контента. Попробуйте позже."
            answer_message = await reply_target.answer(text=answer_text)
            parse_mode = ParseMode.HTML
        except Exception:
            bot_logger.exception(f"{bot_tag} Failed to send fallback error message")

    finally:
        # Сохраняем snapshot
        await save_last_message(state, answer_message, answer_text, answer_keyboard, parse_mode)

    return answer_message


def build_keyboard(keyboard_config: dict | None):
    """
    Строит Telegram-клавиатуру (inline или reply) на основе конфигурации,
    полученной от Core.

    Функция работает в режиме best-effort rendering:
    - не выбрасывает исключений
    - не прерывает рендеринг при неконсистентных данных
    - логирует все аномалии с уровнем WARNING
    - всегда пытается отрендерить максимум возможного

    :param keyboard_config: конфигурация клавиатуры от Core или None
        Ожидаемый формат:
        {
            "type": "inline" | "reply",          # опционально, default="reply"
            "buttons": [                          # опционально
                {
                    "text": "Кнопка",
                    "callback_data": "DATA" | None,
                    "url": "https://..." | None
                }
            ],
            "layout": [1, 2, 2]                   # опционально, default=[1]
        }

    :return:
        InlineKeyboardMarkup | ReplyKeyboardMarkup | None
    """

    bot_tag = f"[{BOT_NAME}]"

    if not keyboard_config:
        return None

    kb_type = keyboard_config.get("type", "reply")
    buttons = keyboard_config.get("buttons", [])
    layout = keyboard_config.get("layout", [1])

    # Защита от мусорного layout
    if not isinstance(layout, list) or not all(isinstance(x, int) and x > 0 for x in layout):
        bot_logger.warning(
            f"{bot_tag} Invalid keyboard layout, fallback to [1] | layout={layout}"
        )
        layout = [1]

    # INLINE KEYBOARD
    if kb_type == "inline":
        aiogram_buttons: list[InlineKeyboardButton] = []

        for index, btn in enumerate(buttons):
            text = btn.get("text")

            if not text:
                bot_logger.warning(
                    f"{bot_tag} Inline button without text skipped | btn={btn}"
                )
                continue

            if btn.get("callback_data"):
                aiogram_buttons.append(
                    InlineKeyboardButton(
                        text=text,
                        callback_data=btn["callback_data"]
                    )
                )
            elif btn.get("url"):
                aiogram_buttons.append(
                    InlineKeyboardButton(
                        text=text,
                        url=str(btn["url"]).strip()
                    )
                )
            else:
                bot_logger.warning(
                    f"{bot_tag} Inline button without action rendered as noop | btn={btn}"
                )
                aiogram_buttons.append(
                    InlineKeyboardButton(
                        text=text,
                        callback_data=text
                    )
                )

        if not aiogram_buttons:
            bot_logger.warning(f"{bot_tag} Inline keyboard has no valid buttons")
            return None

        total_capacity = sum(layout)
        if total_capacity < len(aiogram_buttons):
            bot_logger.warning(
                f"{bot_tag} Inline keyboard layout smaller than buttons count | "
                f"layout={layout} capacity={total_capacity} buttons={len(aiogram_buttons)}"
            )

        rows: list[list[InlineKeyboardButton]] = []
        idx = 0

        for row_size in layout:
            rows.append(aiogram_buttons[idx:idx + row_size])
            idx += row_size

        # best-effort: остаток кнопок добавляем последней строкой
        if idx < len(aiogram_buttons):
            rows.append(aiogram_buttons[idx:])

        return InlineKeyboardMarkup(inline_keyboard=rows)

    # REPLY KEYBOARD
    if kb_type == "reply":
        aiogram_buttons: list[KeyboardButton] = []

        for btn in buttons:
            text = btn.get("text")
            if not text:
                bot_logger.warning(
                    f"{bot_tag} Reply button without text skipped | btn={btn}"
                )
                continue
            aiogram_buttons.append(KeyboardButton(text=text))

        if not aiogram_buttons:
            bot_logger.warning(f"{bot_tag} Reply keyboard has no valid buttons")
            return None

        total_capacity = sum(layout)
        if total_capacity < len(aiogram_buttons):
            bot_logger.warning(
                f"{bot_tag} Reply keyboard layout smaller than buttons count | "
                f"layout={layout} capacity={total_capacity} buttons={len(aiogram_buttons)}"
            )

        rows: list[list[KeyboardButton]] = []
        idx = 0

        for row_size in layout:
            rows.append(aiogram_buttons[idx:idx + row_size])
            idx += row_size

        if idx < len(aiogram_buttons):
            rows.append(aiogram_buttons[idx:])

        return ReplyKeyboardMarkup(
            keyboard=rows,
            resize_keyboard=True,
            one_time_keyboard=True,
        )

    # UNKNOWN TYPE
    bot_logger.warning(
        f"{bot_tag} Unknown keyboard type, skipped | type={kb_type} config={keyboard_config}"
    )
    return None


async def save_last_message(
        state: FSMContext,
        answer_message: Message | None,
        answer_text: str,
        answer_keyboard,
        parse_mode: ParseMode,
):
    """
    Сохраняет snapshot последнего отправленного сообщения в state.
    Формат единообразен: id, text, keyboard (JSON), parse_mode.
    """
    if not answer_message:
        return
    await state.update_data(
        last_message={
            "id": answer_message.message_id,
            "text": answer_text,
            "keyboard": answer_keyboard.model_dump_json() if answer_keyboard else None,
            "parse_mode": parse_mode,
        }
    )
