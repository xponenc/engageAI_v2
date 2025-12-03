import asyncio
import logging
import sys

import yaml

from .celery_app import celery_app
from .bots_engine import feed_update_with_retry
from aiogram import types, Bot, Dispatcher

from bots.test_bot.services.api_process import core_post, auto_context

logger = logging.getLogger("bots_tasks")


# @celery_app.task(bind=True, max_retries=3, default_retry_delay=3)
@celery_app.task(bind=True)
def process_update_task(self, bot_name: str, update_data: dict):
    """
    Универсальная задача для обработки обновлений любого бота.
    """
    bot_tag = f"[Task:{bot_name}]"
    update_id = update_data.get('update_id')
    logger.info(f"{bot_tag} Запуск задачи Celery для апдейта {update_id}")

    try:
        bots = self.app.conf.bots

        # logger.warning(f"process_update_task bots:\n"
        #                f"{yaml.dump(bots, allow_unicode=True, default_flow_style=False)}")

        if bot_name not in bots:
            logger.error(f"{bot_tag} Update ID {update_id} Бот не найден в состоянии воркера")
            # Попробуем перезагрузить ботов при следующей задаче
            raise self.retry(countdown=5, max_retries=1)

        bot_conf = bots[bot_name]
        bot = bot_conf["bot"]
        dp = bot_conf["dp"]
        assistant_slug = bot_conf["assistant_slug"]

        logger.warning(f"process_update_task bot_conf:assistant_slug - {assistant_slug}")

        if sys.platform == "win32":
            # Windows + solo → нужен nest_asyncio
            import nest_asyncio
            nest_asyncio.apply()
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(_async_process_update(
                bot_name=bot_name,
                bot=bot,
                dispatcher=dp,
                update_data=update_data,
                assistant_slug=assistant_slug
            ))
        else:
            # Linux / любой нормальный пул → чистый asyncio.run
            return asyncio.run(_async_process_update(
                bot_name=bot_name,
                bot=bot,
                dispatcher=dp,
                update_data=update_data,
                assistant_slug=assistant_slug
            ))

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


async def _async_process_update(
        bot_name: str,
        bot: Bot,
        dispatcher: Dispatcher,
        update_data: dict,
        assistant_slug: str
):
    """Обработки апдейта"""
    bot_tag = f"[Bot:{bot_name}]"
    update_id = update_data.get('update_id')

    try:
        logger.debug(f"{bot_tag} Создание объекта Update ID {update_id}")
        update = types.Update(**update_data)

        logger.info(f"{bot_tag} Запуск обработки Update ID {update_id}")
        await feed_update_with_retry(bot, dispatcher, update, bot_name)

        logger.info(f"{bot_tag} Сохранение Update ID {update_id} в DRF")
        await _save_update_to_drf(
            bot_name=bot_name,
            update_data=update_data,
            assistant_slug=assistant_slug,
            status="success")

        return True

    except asyncio.CancelledError:
        logger.warning(f"{bot_tag} Задача отменена, сохраняем состояние Update ID {update_id}")
        await _save_update_to_drf(
            bot_name=bot_name,
            update_data=update_data,
            assistant_slug=assistant_slug,
            status="cancelled"
        )

    except Exception as e:
        logger.exception(f"{bot_tag} Update ID {update_id} Критическая ошибка: {str(e)}")
        try:
            await _save_update_to_drf(bot_name, update_data, status="error", error=str(e))
        except Exception as save_err:
            logger.error(f"{bot_tag} Update ID {update_id} Не удалось сохранить ошибку: {save_err}")
        raise


@auto_context()
async def _save_update_to_drf(
        bot_name: str,
        update_data: dict,
        assistant_slug: str,
        status: str = "pending",
        error: str = None,
        **kwargs):
    """Асинхронное сохранение в DRF API"""
    core_drf_url = f"/chat/api/v1/chat/telegram/updates/"
    bot_tag = f"[Bot:{bot_name}]"
    update_id = update_data.get('update_id')

    context = kwargs.get("context", {})
    logger.warning(f"_save_update_to_drf context:\n"
                   f"{yaml.dump(context, allow_unicode=True, default_flow_style=False)}")

    context.update({
        "update_id": update_id,
        "bot_name": bot_name,
        "status": status,
        "user_id": update_data.get('message', {}).get('from', {}).get('id') or
                   update_data.get('callback_query', {}).get('from', {}).get('id'),
        "chat_id": update_data.get('message', {}).get('chat', {}).get('id') or
                   update_data.get('callback_query', {}).get('message', {}).get('chat', {}).get('id'),
        "message_id": update_data.get('message', {}).get('message_id') or
                      update_data.get('callback_query', {}).get('message', {}).get('message_id'),
        "event_type": "message" if update_data.get('message') else
        ("callback_query" if update_data.get('callback_query') else "unknown"),
        "text_preview": (update_data.get('message', {}).get('text', '')[:50] or
                         update_data.get('callback_query', {}).get('data', '')[:50]),
        "error": error[:200] if error and isinstance(error, str) else error,
        "action": "save_telegram_update"
    })

    logger.warning(f"_save_update_to_drf updated context:\n"
                   f"{yaml.dump(context, allow_unicode=True, default_flow_style=False)}")

    payload = {
        "bot_name": bot_name,
        "assistant_slug": assistant_slug,
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
