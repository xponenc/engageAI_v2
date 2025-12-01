from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode

from bots.test_bot.services.api_process import core_post
from bots.test_bot.config import bot_logger, BOT_NAME

fallback_router = Router()


@fallback_router.message(StateFilter(None), F.text)
async def handle_fallback_message(message: Message, state: FSMContext):
    """
    Обрабатывает все текстовые сообщения вне заданных состояний
    """
    bot_tag = f"[{BOT_NAME}]"
    bot_logger.info(f"{bot_tag} Fallback обработчик получил сообщение от {message.from_user.id}: {message.text}")

    # Получаем данные пользователя из состояния
    state_data = await state.get_data()
    user_data = state_data.get("user_data", {})

    # Проверяем, авторизован ли пользователь
    if not user_data.get("user_id"):
        bot_logger.info(f"{bot_tag} Пользователь не авторизован, перенаправляем на регистрацию")
        await message.answer(
            "Для работы с AI-репетитором необходимо пройти регистрацию. "
            "Пожалуйста, используйте команду /registration для привязки вашего аккаунта."
        )
        return

    # Подготавливаем payload для запроса к AI-оркестратору
    payload = {
        "user_id": user_data["user_id"],  # Используем user_id вместо telegram_id
        "message_text": message.text,
        "user_context": user_data,
        "platform": "telegram"
    }

    # Используем существующий core_post для отправки запроса
    ok, response = await core_post("/ai/api/orchestrator/process/", payload)

    # Отправляем ответ пользователю
    if ok:
        response_message = response.get("response_message",
                                        "Извините, я пока не могу ответить на ваш вопрос. Попробуйте задать его по-другому.")
        await message.answer(
            response_message,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    else:
        # core_post вернул ошибку, response содержит сообщение об ошибке
        error_message = response if isinstance(response,
                                               str) else "Извините, сейчас я не могу обработать ваш запрос. Попробуйте позже или воспользуйтесь командами из меню."
        await message.answer(error_message)

    bot_logger.info(f"{bot_tag} Отправлен ответ на fallback-сообщение")