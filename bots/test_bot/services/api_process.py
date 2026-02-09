import functools
import inspect
import traceback
from typing import Callable, Any

import httpx
import yaml
from aiogram.types import Message, CallbackQuery
from asgiref.sync import async_to_sync

from bots.test_bot.config import CORE_API, BOT_INTERNAL_KEY, bot_logger, BOT_NAME


async def core_post(url: str, payload: dict, context: dict = None, **kwargs):
    """
    Унифицированный запрос к DRF API с расширенным логгированием и обработкой ошибок

    Args:
        url: Эндпоинт API (без базового URL)
        payload: Данные для отправки
        context: Контекст вызова для логгирования (опционально)
            {
                "caller": "function_name",
                "update_id": 12345,
                "user_id": 67890,
                "session_id": "abc123"
            }

    Returns:
        tuple: (success: bool, response: dict|str)
    """
    bot_tag = f"[{BOT_NAME}]"

    if context is None:
        context = kwargs.get("context", {})

    # Если context всё ещё пустой — минимальный fallback
    if not context:
        context = {"handler": "direct_call", "function": "core_post"}

    # bot_logger.warning(f"process_update_task bots:\n"
    #                f"{yaml.dump(context, allow_unicode=True, default_flow_style=False)}")

    if "telegram_message_id" not in payload and context.get("message_id"):
        payload["telegram_message_id"] = context["message_id"]

    if "user_telegram_id" not in payload and context.get("user_telegram_id"):
        payload["user_telegram_id"] = context["user_telegram_id"]

    caller_name = context.get("function", "unknown")
    caller_module = context.get("caller_module", "unknown")

    full_context = {
        "caller_function": caller_name,
        "caller_module": caller_module,
        "url": url,
        "update_id": context.get("update_id") if context else None,
        "user_id": context.get("user_id") if context else None,
        "event_type": context.get("event_type") if context else None,
        "traceback": traceback.format_stack(limit=5)[-2].strip() if context else None,
        "error_message": context.get("error_message") if context else None,
    }

    base_log = (

        f"├── Эндпоинт: {CORE_API}{url}\n"
        f"├── Вызывающая функция: {caller_name} ({caller_module})\n"
        f"├── User ID: {full_context['user_id'] or 'N/A'}\n"
    )
    update_id = full_context['update_id']
    if update_id:
        base_log += f"├── Update ID: {update_id}\n"

    request_log = f"{bot_tag} Запрос к API\n" + base_log

    event_type = full_context['event_type']
    if event_type:
        request_log += f"├── Event type: {event_type}\n"

    # traceback_data = full_context['traceback']
    # if traceback_data:
    #     request_log += f"├── Traceback: {traceback_data}\n"

    error_message = full_context['error_message']
    if error_message:
        request_log += f"├── Update ID: {error_message}\n"

    request_log += f"└── Payload: {payload}"

    bot_logger.info(request_log)

    try:
        async with httpx.AsyncClient(
                timeout=15.0,
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                headers={"X-Internal-Key": BOT_INTERNAL_KEY}
        ) as client:
            response = await client.post(
                f"{CORE_API}{url}",
                json=payload,
                headers={"Content-Type": "application/json"}
            )

            response_log = (
                               f"{bot_tag} Ответ от API\n"
                               f"├── Статус: {response.status_code}\n"
                           ) + base_log + (
                               f"├── Длина ответа: {len(response.content)} байт\n"
                               f"└── Ответ[:50]: {response.content[:50]}"
                           )

            bot_logger.info(response_log)

            try:
                response.raise_for_status()

                try:
                    data = response.json()
                except ValueError as e:
                    error_msg = f"Ошибка парсинга JSON: {str(e)}"
                    error_log = (
                            f"{bot_tag} Ответ от API(обработка)\n" + base_log +
                            f"├── {error_msg}\n"
                            f"└── Ответ: {response.text}"
                    )
                    bot_logger.error(error_log)
                    return False, error_msg
                success_msg = "Успешный парсинг ответа"
                success_log = (
                        f"{bot_tag} Ответ от API(обработка)\n" + base_log +
                        f"├── {success_msg}\n"
                        f"└── Data: {data}"
                )
                bot_logger.debug(success_log)
                return True, data

            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                error_detail = e.response.text
                error_msg = f"HTTP ошибка ({status_code})"
                error_log = (
                        f"{bot_tag} Ответ от API(ошибка)\n" + base_log +
                        f"├── {error_msg}\n"
                        f"├── Заголовки запроса: {dict(response.request.headers)}\n"
                        f"└── Ответ сервера: {error_detail[:500]}"
                )

                bot_logger.error(error_log)

                if status_code in (401, 403):
                    return False, "Ошибка авторизации бота. Сообщите администратору."
                elif status_code >= 500:
                    return False, "Сервер временно недоступен. Попробуйте позже."
                else:
                    return False, f"Ошибка API: {status_code}. {error_detail[:100]}"

    except httpx.TimeoutException as e:
        # Таймауты
        error_msg = f"Таймаут запроса"
        timeout_log = (
                f"{bot_tag} Ответ от API(таймаут)\n" + base_log +
                f"├── {error_msg}\n"
                f"└── Ошибка: {str(e)}"
        )
        bot_logger.warning(timeout_log)
        return False, "Сервер не отвечает. Попробуйте позже."

    except Exception as e:
        # Неизвестные ошибки
        error_msg = f"Неизвестная ошибка"
        exception_log = (
                f"{bot_tag} Ответ от API(ошибка)\n" + base_log +
                f"├── {error_msg}\n"
                f"├── Тип ошибки: {type(e).__name__}\n"
                f"├── Сообщение: {str(e)}\n"
                f"└── Traceback:\n{traceback.format_exc()}"
        )
        bot_logger.exception(exception_log)
        return False, "Неизвестная ошибка. Попробуйте позже."


def auto_context(explicit_caller: str = None):
    """
    Универсальный декоратор: автоматически добавляет в kwargs["context"] информацию о вызове.
    - Работает в sync и async функциях.
    - Автоматически определяет имя функции и модуля (без inspect.currentframe()).
    - Если есть event (Message/CallbackQuery) в args — добавляет user_id, chat_id и т.д.
    - Можно указать explicit_caller для переопределения имени.

    Пример использования:
    @auto_context()
    async def my_handler(event, state):
        await core_post(url="...", payload=...)  # context добавится автоматически!
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            return async_to_sync(_add_context)(func, explicit_caller, *args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            return _add_context(func, explicit_caller, *args, **kwargs)

        # Возвращаем async или sync версию в зависимости от оригинальной функции
        return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper

    return decorator


def _add_context(func, explicit_caller: str, *args, **kwargs):
    """
    Формирует context для core_post автоматически.
    Работает для Message и CallbackQuery.
    """
    # TODO надо расширить
    func_name = explicit_caller or func.__name__
    module_name = func.__module__

    context = {
        "handler": f"{func_name} ({module_name})",
        "function": func_name,
        "caller_module": module_name,
    }

    event = None
    for arg in args:
        if isinstance(arg, (Message, CallbackQuery)):
            event = arg
            break

    if isinstance(event, Message):
        context["event_type"] = "message"
        context["user_id"] = event.from_user.id
        context["user_telegram_id"] = event.from_user.id
        context["chat_id"] = event.chat.id
        context["message_id"] = event.message_id

    elif isinstance(event, CallbackQuery):
        context["event_type"] = "callback"
        context["user_id"] = event.from_user.id
        context["user_telegram_id"] = event.from_user.id

        # callback может быть без .message → inline mode
        if event.message:
            # context["user_id"] = event.message.from_user.id
            # context["user_telegram_id"] = event.from_user.id
            context["chat_id"] = event.message.chat.id
            context["message_id"] = event.message.message_id
        else:
            # inline callback — chat_id нет
            context["chat_id"] = None
            context["message_id"] = None

    kwargs.setdefault("context", {}).update(context)

    return func(*args, **kwargs)
