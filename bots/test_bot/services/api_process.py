import asyncio
import inspect
import traceback

import aiohttp
import httpx

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


async def core_post(url: str, payload: dict, context: dict = None):
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

    # Автоопределение вызывающей функции
    caller_frame = inspect.currentframe().f_back
    caller_name = caller_frame.f_code.co_name if caller_frame else "unknown"
    caller_module = inspect.getmodule(caller_frame).__name__ if caller_frame else "unknown"

    full_context = {
        "caller_function": caller_name,
        "caller_module": caller_module,
        "url": url,
        "update_id": context.get("update_id") if context else None,
        "user_id": context.get("user_id") if context else None,
        "session_id": context.get("session_id") if context else None,
        "chat_id": context.get("chat_id") if context else None,
        "traceback": traceback.format_stack(limit=5)[-2].strip() if context else None
    }

    request_log = (
        f"{bot_tag} Запрос к API\n"
        f"├── Эндпоинт: {CORE_API}{url}\n"
        f"├── Вызывающая функция: {caller_name} ({caller_module})\n"
        f"├── Update ID: {full_context['update_id'] or 'N/A'}\n"
        f"├── User ID: {full_context['user_id'] or 'N/A'}\n"
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
