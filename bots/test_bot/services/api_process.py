import functools
import inspect
import traceback
from typing import Callable, Any

import httpx
from aiogram.types import Message, CallbackQuery

from bots.test_bot.config import CORE_API, BOT_INTERNAL_KEY, bot_logger, BOT_NAME


# async def core_post(url: str, payload: dict, ):
#     """Унифицированный запрос с безопасной обработкой ошибок."""
#     bot_tag = f"[{BOT_NAME}]"
#     bot_logger.info(f"{bot_tag} запрос {CORE_API}{url}")
#     try:
#         async with aiohttp.ClientSession() as session:
#             async with session.post(
#                     f"{CORE_API}{url}",
#                     json=payload,
#                     headers={"X-Internal-Key": BOT_INTERNAL_KEY},
#                     timeout=15
#             ) as resp:
#
#                 bot_logger.info(f"{bot_tag} POST {url} payload={payload} status={resp.status}")
#
#                 if resp.status >= 500:
#                     return False, "Сервер временно недоступен. Попробуйте позже."
#                 if resp.status in (401, 403):
#                     return False, "Ошибка авторизации бота. Сообщите администратору."
#
#                 try:
#                     data = await resp.json()
#                 except Exception:
#                     bot_logger.error(f"{bot_tag} Ошибка чтения JSON")
#                     return False, "Ошибка обработки ответа сервера."
#
#                 if not data.get("success", True):
#                     bot_logger.warning(f"{bot_tag} API вернул ошибку: {data}")
#                     return False, data.get("detail", "Ошибка на сервере.")
#
#                 bot_logger.info(f"{bot_tag} Успешный ответ: {data}")
#                 return True, data
#
#     except asyncio.TimeoutError:
#         bot_logger.warning(f"{bot_tag} Timeout при обращении к {url}")
#         return False, "Сервер не отвечает. Попробуйте позже."
#     except Exception as e:
#         bot_logger.error(f"{bot_tag} Неизвестная ошибка: {e}")
#         return False, "Неизвестная ошибка. Попробуйте позже."


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

    caller_name = context.get("function", "unknown")
    caller_module = context.get("caller_module", "unknown")

    full_context = {
        "caller_function": caller_name,
        "caller_module": caller_module,
        "url": url,
        "update_id": context.get("update_id") if context else None,
        "user_id": context.get("user_id") if context else None,
        "session_id": context.get("session_id") if context else None,
        "chat_id": context.get("chat_id") if context else None,
        "event_type": context.get("event_type") if context else None,
        "traceback": traceback.format_stack(limit=5)[-2].strip() if context else None
    }

    request_log = (
        f"{bot_tag} Запрос к API\n"
        f"├── Эндпоинт: {CORE_API}{url}\n"
        f"├── Вызывающая функция: {caller_name} ({caller_module})\n"
        f"├── Update ID: {full_context['update_id'] or 'N/A'}\n"
        f"├── User ID: {full_context['user_id'] or 'N/A'}\n"
        f"├── Event type: {full_context['event_type'] or 'N/A'}\n"
        f"└── Payload: {payload}"
    )
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
                f"├── Эндпоинт: {CORE_API}{url}\n"
                f"├── Update ID: {full_context['update_id'] or 'N/A'}\n"
                f"└── Длина ответа: {len(response.content)} байт"
            )
            bot_logger.info(response_log)

            try:
                response.raise_for_status()

                try:
                    data = response.json()
                except ValueError as e:
                    error_msg = f"Ошибка парсинга JSON: {str(e)}"
                    bot_logger.error(f"{bot_tag} {error_msg}\nОтвет: {response.text[:200]}")
                    return False, error_msg

                if not data.get("success", True):
                    detail = data.get("detail", "Неизвестная ошибка бизнес-логики")
                    bot_logger.warning(f"{bot_tag} Бизнес-ошибка API: {detail}\nДанные: {data}")
                    return False, detail

                success_log = (
                    f"{bot_tag} Успешный запрос\n"
                    f"├── Эндпоинт: {CORE_API}{url}\n"
                    f"├── Update ID: {full_context['update_id'] or 'N/A'}\n"
                    f"└── Ответ: {data}"
                )
                bot_logger.debug(success_log)
                return True, data

            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                error_detail = e.response.text

                error_log = (
                    f"{bot_tag} HTTP ошибка ({status_code})\n"
                    f"├── Эндпоинт: {CORE_API}{url}\n"
                    f"├── Update ID: {full_context['update_id'] or 'N/A'}\n"
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
        timeout_log = (
            f"{bot_tag} ⏱ Таймаут запроса\n"
            f"├── Эндпоинт: {CORE_API}{url}\n"
            f"├── Update ID: {full_context['update_id'] or 'N/A'}\n"
            f"└── Ошибка: {str(e)}"
        )
        bot_logger.warning(timeout_log)
        return False, "Сервер не отвечает. Попробуйте позже."

    except Exception as e:
        # Неизвестные ошибки
        exception_log = (
            f"{bot_tag} Неизвестная ошибка\n"
            f"├── Эндпоинт: {CORE_API}{url}\n"
            f"├── Update ID: {full_context['update_id'] or 'N/A'}\n"
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
            return await _add_context(func, explicit_caller, *args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            return _add_context(func, explicit_caller, *args, **kwargs)

        # Возвращаем async или sync версию в зависимости от оригинальной функции
        return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper

    return decorator


def _add_context(func, explicit_caller: str, *args, **kwargs) -> Any:
    # Определяем имя функции и модуля (надёжно, без currentframe)
    func_name = explicit_caller or func.__name__
    module_name = func.__module__

    # Базовый контекст
    context = {
        "handler": f"{func_name} ({module_name})",
        "function": func_name,
        "caller_module": module_name,
    }

    # Если передан event (Message или CallbackQuery) — добавляем данные из него
    for arg in args:
        if isinstance(arg, Message):
            tg_user_id = arg.from_user.id

            chat_id = arg.chat.id
            event_message_id = arg.message_id
            command = arg.text
            event_type = "message"
            context.update({
                    "user_id": tg_user_id,
                    "chat_id": chat_id,
                    "message_id": event_message_id,
                    "event_type": event_type,
                })
            break
        elif isinstance(arg, CallbackQuery):
            tg_user_id = arg.from_user.id
            chat_id = arg.message.chat.id
            event_message_id = arg.message.message_id
            event_type = "callback"
            context.update({
                "user_id": tg_user_id,
                "chat_id": chat_id,
                "message_id": event_message_id,
                "event_type": event_type,
            })
            break
        # if hasattr(arg, "from_user") and hasattr(arg.from_user, "id"):
        #     context.update({
        #         "user_id": arg.from_user.id,
        #         "chat_id": getattr(getattr(arg, "chat", None), "id", None),
        #         "update_id": getattr(arg, "update_id", None),
        #         "message_id": getattr(arg, "message_id", None),
        #         "event_type": "callback_query" if hasattr(arg, "callback_query") else "message",
        #     })
        #     break

    # Если в kwargs уже есть context — дополняем его нашим
    if "context" in kwargs:
        kwargs["context"].update(context)
    else:
        kwargs["context"] = context

    # Вызываем оригинальную функцию с обновлёнными kwargs
    return func(*args, **kwargs)