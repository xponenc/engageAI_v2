import asyncio

import aiohttp

from bots.test_bot.config import CORE_API, BOT_INTERNAL_KEY, bot_logger, BOT_NAME


async def core_post(url: str, payload: dict, ):
    """Унифицированный запрос с безопасной обработкой ошибок."""
    bot_tag = f"[{BOT_NAME}]"
    bot_logger.info(f"{bot_tag} запрос {CORE_API}{url}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    f"{CORE_API}{url}",
                    json=payload,
                    headers={"X-Internal-Key": BOT_INTERNAL_KEY},
                    timeout=15
            ) as resp:

                bot_logger.info(f"{bot_tag} POST {url} payload={payload} status={resp.status}")

                if resp.status >= 500:
                    return False, "Сервер временно недоступен. Попробуйте позже."
                if resp.status in (401, 403):
                    return False, "Ошибка авторизации бота. Сообщите администратору."

                try:
                    data = await resp.json()
                except Exception:
                    bot_logger.error(f"{bot_tag} Ошибка чтения JSON")
                    return False, "Ошибка обработки ответа сервера."

                if not data.get("success", True):
                    bot_logger.warning(f"{bot_tag} API вернул ошибку: {data}")
                    return False, data.get("detail", "Ошибка на сервере.")

                bot_logger.info(f"{bot_tag} Успешный ответ: {data}")
                return True, data

    except asyncio.TimeoutError:
        bot_logger.warning(f"{bot_tag} Timeout при обращении к {url}")
        return False, "Сервер не отвечает. Попробуйте позже."
    except Exception as e:
        bot_logger.error(f"{bot_tag} Неизвестная ошибка: {e}")
        return False, "Неизвестная ошибка. Попробуйте позже."

