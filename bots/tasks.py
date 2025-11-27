import asyncio
import logging

from celery_app import celery_app
from bots_engine import BOTS, feed_update_with_retry
from aiogram import types

logger = logging.getLogger("bots_tasks")

@celery_app.task(bind=True, max_retries=3, default_retry_delay=3)
def process_update_task(self, bot_name: str, update_data: dict):
    """
    Celery задача для обработки update Telegram через aiogram.
    """
    if bot_name not in BOTS:
        logger.error(f"Bot not found: {bot_name}")
        return

    bot_conf = BOTS[bot_name]
    bot = bot_conf["bot"]
    dp = bot_conf["dp"]

    update = types.Update(**update_data)

    try:
        asyncio.run(feed_update_with_retry(bot, dp, update, bot_name))
        logger.info(f"Update {update.update_id} успешно обработан Celery")
    except Exception as e:
        logger.exception(f"Ошибка обработки update {update.update_id} через Celery: {e}")
        raise self.retry(exc=e)