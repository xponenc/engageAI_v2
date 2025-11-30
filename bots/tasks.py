# bots/tasks.py
import asyncio
import logging

import httpx
from aiogram.types import CallbackQuery

from .celery_app import celery_app
from .bots_engine import BOTS, feed_update_with_retry
from aiogram import types
from redis.asyncio import Redis

from .test_bot.config import CORE_API, BOT_INTERNAL_KEY
from .test_bot.services.api_process import core_post

logger = logging.getLogger("bots_tasks")


@celery_app.task(bind=True, max_retries=3, default_retry_delay=3)
def process_update_task(self, bot_name: str, update_data: dict):
    """
    Универсальная задача для обработки обновлений любого бота.
    """
    bot_tag = f"[Task:{bot_name}]"
    update_id = update_data.get('update_id')
    logger.info(f"{bot_tag} Запуск задачи Celery для апдейта {update_id}")

    if bot_name not in BOTS:
        logger.error(f"{bot_tag} Бот не найден в реестре при обработке апдейта {update_id}")
        return False

    try:
        # Проверяем наличие event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Используем существующий loop
            future = asyncio.ensure_future(_async_process_update(bot_name, update_data))
            return loop.run_until_complete(future)
        else:
            # Создаем новый loop
            return asyncio.run(_async_process_update(bot_name, update_data))

    except Exception as e:
        logger.exception(f"{bot_tag} Update ID {update_id} Критическая ошибка в задаче Celery: {e}")
        # Для постоянных ошибок не пытаемся повторить
        if "bot not found" in str(e).lower() or "invalid update format" in str(e).lower():
            logger.warning(f"{bot_tag} Update ID {update_id} Постоянная ошибка, не повторяем попытки")
            return False
        # Для временных ошибок — повторяем
        raise self.retry(exc=e)
    finally:
        # Всегда помечаем update_id как обработанный
        if update_id:
            try:
                from bots.celery_app import celery_app
                redis_client = celery_app.backend.client
                key = f"telegram:processed:{update_id}"
                redis_client.setex(key, 86400, "1")  # Храним 24 часа
                logger.debug(f"{bot_tag} Update ID {update_id} помечен как обработанный")
            except Exception as e:
                logger.error(f"{bot_tag} Update ID {update_id}Ошибка сохранения update_id в Redis: {e}")


async def _async_process_update(bot_name: str, update_data: dict):
    """Обработки апдейта"""
    bot_tag = f"[Bot:{bot_name}]"
    update_id = update_data.get('update_id')

    bot_conf = BOTS[bot_name]
    bot = bot_conf["bot"]
    dp = bot_conf["dp"]

    try:
        logger.debug(f"{bot_tag} Создание объекта Update ID {update_id}")
        update = types.Update(**update_data)

        logger.info(f"{bot_tag} Запуск обработки Update ID {update_id}")
        await feed_update_with_retry(bot, dp, update, bot_name)

        logger.info(f"{bot_tag} Сохранение Update ID {update_id} в DRF")
        await _save_update_to_drf(bot_name, update_data, status="success")

        return True

    except asyncio.CancelledError:
        logger.warning(f"{bot_tag} Задача отменена, сохраняем состояние Update ID {update_id}")
        await _save_update_to_drf(bot_name, update_data, status="cancelled")

    except Exception as e:
        logger.exception(f"{bot_tag} Update ID {update_id} Критическая ошибка: {str(e)}")
        try:
            await _save_update_to_drf(bot_name, update_data, status="error", error=str(e))
        except Exception as save_err:
            logger.error(f"{bot_tag} Update ID {update_id} Не удалось сохранить ошибку: {save_err}")
        raise


async def _save_update_to_drf(bot_name: str, update_data: dict, status: str = "pending", error: str = None):
    """Асинхронное сохранение в DRF API"""
    core_drf_url = f"{CORE_API}/api/v1/chat/telegram/updates/"
    bot_tag = f"[Bot:{bot_name}]"
    update_id = update_data.get('update_id')

    context = {
        "update_id": update_id,
        "bot_name": bot_name,
        "status": status,

        # Данные о пользователе и чате
        "user_id": update_data.get('message', {}).get('from', {}).get('id') or
                   update_data.get('callback_query', {}).get('from', {}).get('id'),
        "chat_id": update_data.get('message', {}).get('chat', {}).get('id') or
                   update_data.get('callback_query', {}).get('message', {}).get('chat', {}).get('id'),
        "message_id": update_data.get('message', {}).get('message_id') or
                      update_data.get('callback_query', {}).get('message', {}).get('message_id'),

        # Тип события и содержимое
        "event_type": "message" if update_data.get('message') else
        ("callback_query" if update_data.get('callback_query') else "unknown"),
        "text_preview": (update_data.get('message', {}).get('text', '')[:50] or
                         update_data.get('callback_query', {}).get('data', '')[:50]),

        "error": error[:200] if error and isinstance(error, str) else error,
        "function": "_save_update_to_drf",
        "action": "save_telegram_update"
    }

    payload = {
        "bot_name": bot_name,
        "update": update_data,
        "processing_status": status,
        "error_message": error
    }
    ok, response = await core_post(
        url=core_drf_url,
        payload=payload,
        context=context
    )

    if not ok:
        error_msg = f"{bot_tag} Update ID {update_id} Ошибка сохранения в DRF: {response}"
        logger.error(error_msg)
        raise Exception(error_msg)

    logger.info(f"{bot_tag} Update ID {update_id} Успешно сохранено в DRF")
    return response
