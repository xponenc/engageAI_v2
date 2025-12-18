import inspect
import os
import time
from typing import Optional, Union, Any

from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bots.services.utils import get_assistant_slug
from bots.test_bot.services.api_process import core_post, auto_context
from bots.test_bot.config import bot_logger, BOT_NAME, AUTH_CACHE_TTL_SECONDS, NO_EMOJI
from bots.test_bot.services.sender import reply_and_update_last_message


class AuthFilter(BaseFilter):
    """
    Фильтр авторизации для Aiogram 3.x.
    Проверяет, привязан ли telegram_id пользователя к учётной записи.
    Кэширует результат в FSMContext на AUTH_CACHE_TTL_SECONDS.

    Пример:
    @assessment_router.message(F.text == "/base_test", AuthFilter())
    async def start_test(msg: Message, state: FSMContext):
    """

    async def __call__(self,
                       event: Union[Message, CallbackQuery],
                       state: FSMContext,
                       handler: Any
                       ) -> bool:
        bot_tag = f"[{BOT_NAME}]"

        handler_info = self._get_handler_info(handler)

        # Унификация для Message / CallbackQuery
        if isinstance(event, CallbackQuery):
            user_telegram_id = event.from_user.id
            from_user = event.from_user
            reply_func = event.message.answer
            callback_answer = event.answer
            message_id = event.message.message_id
        else:
            user_telegram_id = event.from_user.id
            from_user = event.from_user
            reply_func = event.answer
            callback_answer = None
            message_id = event.message_id

        bot_logger.info(
            f"{bot_tag} Проверка авторизации для telegram_id={user_telegram_id}, "
            f"Хендлер: {handler_info['full_name']}\n"
            f"├── Модуль: {handler_info['module']}\n"
            f"├── Файл: {handler_info['file_path']}\n"
            f"├── Строка: {handler_info['line_number']}\n"
            f"└── Сигнатура: {handler_info['signature']}"
        )

        # Кэш авторизации
        state_data = await state.get_data()
        cache = state_data.get("telegram_auth_cache", {})

        now = int(time.time())
        is_cached = (
                cache.get("telegram_id") == user_telegram_id
                and now - cache.get("checked_at", 0) < AUTH_CACHE_TTL_SECONDS
        )

        core_user_id = None

        if is_cached:
            core_user_id = cache.get("core_user_id")

            if core_user_id:
                bot_logger.debug(
                    f"{bot_tag} Авторизация найдена в кэше: user_id={core_user_id}, Хендлер: {handler_info['full_name']}"
                )

        # Вызов API
        if not core_user_id:
            bot_logger.debug(
                f"{bot_tag} Запрос к API /check_telegram/ для telegram_id={user_telegram_id}, "
                f"Хендлер: {handler_info['full_name']}"
            )
            context = {
                # "handler": f"{handler_name} ({handler_module})",
                "function": handler_info['name'],
                "caller_module": handler_info['file_path'],
                "user_telegram_id": user_telegram_id,
                "message_id": message_id,
            }

            ok, resp = await core_post(
                url="/accounts/api/v1/users/profile/",
                payload={
                    "user_telegram_id": user_telegram_id,
                    "telegram_username": from_user.username,
                    "telegram_username_first_name": from_user.first_name,
                    "telegram_username_last_name": from_user.last_name,
                },
                context=context
            )
            if ok and isinstance(resp, dict) and resp.get("profile"):

                bot_logger.error(f"\n\n\n Проверка авторизации: {resp=}")

                profile = resp["profile"]
                core_user_id = profile["core_user_id"]

                await state.update_data(profile=profile)
                await state.update_data(telegram_auth_cache={
                    "telegram_id": user_telegram_id,
                    "core_user_id": core_user_id,
                    "checked_at": now
                })

                bot_logger.info(
                    f"{bot_tag} Авторизация успешна (API): telegram_id={user_telegram_id} → core_user={core_user_id}"
                )

            else:
                bot_logger.warning(
                    f"{bot_tag} Авторизация не найдена (telegram_id={user_telegram_id})"
                )

        # не авторизован
        if not core_user_id:
            await state.update_data(telegram_auth_cache={}, profile={})

            if callback_answer:
                await callback_answer()

            # await reply_func(
            #     "🔒 Для работы с AI-репетитором нужно привязать Telegram.\n"
            #     "Используйте /registration, чтобы ввести код из личного кабинета."
            # )
            assistant_slug = get_assistant_slug(event.bot)
            answer_text = (
                    "🔒 <b>Требуется регистрация!</b>\n\n"
                    "Чтобы пользоваться AI-репетитором, привяжите Telegram.\n"
                    "Используйте /registration, чтобы ввести код из личного кабинета."
                )
            last_message_update_text = f"\n\n{NO_EMOJI}\t Базовый тест уровня языка"

            await reply_and_update_last_message(
                event=event,
                state=state,
                last_message_update_text=last_message_update_text,
                answer_text=answer_text,
                answer_keyboard=None,
                current_ai_response=None,
                assistant_slug=assistant_slug,
            )

            bot_logger.info(
                f"{bot_tag} Пользователь {user_telegram_id} отправлен на регистрацию"
            )
            return False

        # OK
        return True

    def _get_handler_info(self, handler: Any) -> dict:
        """Получает подробную информацию о хендлере через интроспекцию"""
        result = {
            "name": "unknown",
            "module": "unknown",
            "file_path": "unknown",
            "line_number": "unknown",
            "signature": "unknown",
            "full_name": "unknown",
            "docstring": "unknown"
        }

        try:
            if hasattr(handler, 'callback'):
                callback = handler.callback

                # Имя функции
                result["name"] = callback.__name__

                # Модуль
                if hasattr(callback, '__module__'):
                    result["module"] = callback.__module__

                # Путь к файлу и номер строки
                try:
                    file_path = inspect.getfile(callback)
                    # Обрезаем путь до проекта для читаемости
                    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
                    relative_path = os.path.relpath(file_path, project_root)
                    result["file_path"] = relative_path

                    # Номер строки
                    _, line_number = inspect.getsourcelines(callback)
                    result["line_number"] = line_number
                except (TypeError, OSError, IOError):
                    pass

                # Сигнатура функции
                try:
                    signature = inspect.signature(callback)
                    result["signature"] = str(signature)
                except ValueError:
                    pass

                # Docstring
                if callback.__doc__:
                    # Берем только первую строку docstring
                    result["docstring"] = callback.__doc__.strip().split('\n')[0]

                # Формируем полное имя
                result["full_name"] = f"{result['name']} ({result['module']})"

        except Exception as e:
            bot_logger.warning(f"Ошибка при получении информации о хендлере: {e}")

        return result
