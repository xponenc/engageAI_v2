import asyncio
import sys

from asgiref.sync import async_to_sync

from bots.test_bot.config import BOT_NAME, bot_logger
from bots.test_bot.services.api_process import auto_context, core_post
from ..celery_app import celery_app


@celery_app.task(bind=True, queue="drf_saves")
def process_save_message(self, payload: dict):
    url = "/api/v1/chat/telegram/message/"
    if sys.platform == "win32":
        # Windows + solo → нужен nest_asyncio
        import nest_asyncio
        nest_asyncio.apply()
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_save_update_to_drf(
            url=url,
            payload=payload,
        ))
    else:
        # Linux / любой нормальный пул → чистый asyncio.run
        # return asyncio.run(_save_update_to_drf(
        #     url=url,
        #     payload=payload,
        # ))
        return async_to_sync(_save_update_to_drf)(
            url=url,
            payload=payload,
        )


@auto_context()
async def _save_update_to_drf(
        url: str,
        payload: dict,
        **kwargs
):
    """Асинхронное сохранение в DRF API"""
    bot_tag = f"[Bot:{BOT_NAME}]"

    context = kwargs.get("context", {})

    ok, response = await core_post(
        url=url,
        payload=payload,
        context=context
    )

    if not ok:
        error_msg = f"{bot_tag} Message {payload} Ошибка сохранения в DRF: {response}"
        bot_logger.error(error_msg)
        raise Exception(error_msg)

    # logger.info(f"{bot_tag} Update ID {update_id} Успешно сохранено в DRF")
    return response
