# bots/test_bot/filters/auth_filter.py
import time
import logging
from typing import Optional, Union

from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bots.test_bot.services.api_process import core_post
from bots.test_bot.config import bot_logger, BOT_NAME, AUTH_CACHE_TTL_SECONDS



class AuthFilter(BaseFilter):
    """
    Фильтр авторизации для Aiogram 3.x.
    Проверяет, привязан ли telegram_id пользователя к учётной записи.
    Кэширует результат в FSMContext на AUTH_CACHE_TTL_SECONDS.

    Пример:
    @assessment_router.message(F.text == "/base_test", AuthFilter())
    async def start_test(msg: Message, state: FSMContext):
    """

    async def __call__(self, event: Union[Message, CallbackQuery], state: FSMContext) -> bool:

        # Унификация для Message / CallbackQuery
        if isinstance(event, CallbackQuery):
            telegram_id = event.from_user.id
            reply_func = event.message.answer
            callback_answer = event.answer
        else:
            telegram_id = event.from_user.id
            reply_func = event.answer
            callback_answer = None

        # ---------- Caller detection ----------
        caller = "unknown"
        try:
            import inspect
            frame = inspect.currentframe()
            outer = inspect.getouterframes(frame)
            if len(outer) > 2:
                caller = f"{outer[2].frame.f_globals.get('__name__')}." \
                         f"{outer[2].frame.f_code.co_name}"
        except Exception:
            pass

        bot_tag = f"[{BOT_NAME}]"
        bot_logger.debug(f"{bot_tag} Проверка авторизации для telegram_id={telegram_id}, from={caller}")

        # ----- Кэш -----
        state_data = await state.get_data()
        cache = state_data.get("telegram_auth_cache", {})

        now = int(time.time())
        is_cached = (
            cache.get("telegram_id") == telegram_id
            and now - cache.get("checked_at", 0) < AUTH_CACHE_TTL_SECONDS
        )

        user_id: Optional[int] = None

        if is_cached:
            user_id = cache.get("user_id")
            if user_id:
                bot_logger.debug(f"{bot_tag} Авторизация найдена в кэше: user_id={user_id}, from={caller}")

        # ----- API -----
        if not user_id:
            bot_logger.debug(f"{bot_tag} Запрос к API /check_telegram/ для telegram_id={telegram_id}, from={caller}")
            ok, resp = await core_post(
                "/accounts/api/users/profile/",
                {"telegram_id": telegram_id}
            )
            if ok and resp.get("user_id"):
                profile = resp.get("profile")
                await state.update_data(profile=profile)
                user_id = resp["user_id"]
                await state.update_data(telegram_auth_cache={
                    "telegram_id": telegram_id,
                    "user_id": user_id,
                    "checked_at": now
                })
                bot_logger.info(f"{bot_tag} Авторизация подтверждена (API): telegram_id={telegram_id} → user_id={user_id}, from={caller}")
            else:
                bot_logger.info(f"{bot_tag} Авторизация не найдена для telegram_id={telegram_id}, from={caller}")

        # ---------- NOT AUTHORIZED ----------
        if not user_id:
            if callback_answer:
                await callback_answer()
            await reply_func(
                "🔒 Для работы с AI-репетитором нужно привязать Telegram.\n"
                "Используйте /registration, чтобы ввести код из личного кабинета."
            )
            bot_logger.info(f"{bot_tag} Пользователь {telegram_id} перенаправлен на регистрацию, from={caller}")
            return False
        # ---------- AUTHORIZED ----------
        return True
