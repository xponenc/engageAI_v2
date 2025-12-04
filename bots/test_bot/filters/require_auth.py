import inspect
import os
import time
from typing import Optional, Union, Any

from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bots.test_bot.services.api_process import core_post, auto_context
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

    async def __call__(self,
                       event: Union[Message, CallbackQuery],
                       state: FSMContext,
                       handler: Any
                       ) -> bool:
        bot_tag = f"[{BOT_NAME}]"

        # Извлекаем информацию о хендлере
        # handler_name = handler.callback.__name__ if hasattr(handler, 'callback') else "unknown"
        # handler_module = handler.callback.__module__ if hasattr(handler, 'callback') else "unknown"
        handler_info = self._get_handler_info(handler)

        # Унификация для Message / CallbackQuery
        if isinstance(event, CallbackQuery):
            telegram_id = event.from_user.id
            reply_func = event.message.answer
            callback_answer = event.answer
            message_id = event.message.message_id
        else:
            telegram_id = event.from_user.id
            reply_func = event.answer
            callback_answer = None
            message_id = event.message_id

        bot_logger.info(
            f"{bot_tag} Проверка авторизации для telegram_id={telegram_id}, "
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
            cache.get("telegram_id") == telegram_id
            and now - cache.get("checked_at", 0) < AUTH_CACHE_TTL_SECONDS
        )

        user_id: Optional[int] = None

        if is_cached:
            user_id = cache.get("user_id")
            if user_id:
                bot_logger.debug(
                    f"{bot_tag} Авторизация найдена в кэше: user_id={user_id}, "
                    f"Хендлер: {handler_info['full_name']}"
                )

        # Вызов API
        if not user_id:
            bot_logger.debug(
                f"{bot_tag} Запрос к API /check_telegram/ для telegram_id={telegram_id}, "
                f"Хендлер: {handler_info['full_name']}"
            )
            context = {
                # "handler": f"{handler_name} ({handler_module})",
                "function": handler_info['name'],
                "caller_module": handler_info['file_path'],
                "update_id": getattr(event, "update_id", None),
                "user_id": telegram_id,
                "message_id": message_id,
            }

            ok, resp = await core_post(
                url="/accounts/api/v1/users/profile/",
                payload={"telegram_id": telegram_id},
                context=context
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
                bot_logger.info(
                    f"{bot_tag} Авторизация подтверждена (API): telegram_id={telegram_id} → user_id={user_id},"
                    f" Хендлер: {handler_info['full_name']}"
                )
            else:
                bot_logger.info(
                    f"{bot_tag} Авторизация не найдена для telegram_id={telegram_id}, "
                    f"Хендлер: {handler_info['full_name']}"
                )

        # NOT AUTHORIZED
        if not user_id:
            if callback_answer:
                await callback_answer()
            await reply_func(
                "🔒 Для работы с AI-репетитором нужно привязать Telegram.\n"
                "Используйте /registration, чтобы ввести код из личного кабинета."
            )
            bot_logger.info(f"{bot_tag} Пользователь {telegram_id} перенаправлен на регистрацию, "
                             f"Хендлер: {handler_info['full_name']}")
            return False
        # AUTHORIZED
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