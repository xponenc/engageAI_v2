import os
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict

import yaml
from aiogram.filters import StateFilter
from aiogram.fsm.storage.base import DefaultKeyBuilder
from aiogram.fsm.storage.redis import RedisStorage
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Depends
from aiogram import Bot, Dispatcher, types, Router
import importlib.util
import uvicorn
from redis.asyncio import Redis

from bots.services.startup_process import init_redis_clients, load_bots, close_bot_connections, close_redis_clients
from bots.state_manager import BotStateManager
from bots.test_bot.config import bot_logger
from utils.setup_logger import setup_logger

logger = setup_logger(
    __name__,
    log_dir="logs/bots",
    log_file="bots.log",
    logger_level=10,  # DEBUG
    file_level=10,
    console_level=20  # INFO
)

load_dotenv()

BOTS_ROOT = Path(__file__).parent
INTERNAL_BOT_API_IP = os.getenv("INTERNAL_BOT_API_IP")
INTERNAL_BOT_API_PORT = int(os.getenv("INTERNAL_BOT_API_PORT"))

MAX_RETRIES = 3  # количество попыток feed_update
RETRY_DELAY = 1.5  # задержка между попытками (сек)
FEED_TIMEOUT = 5.0  # таймаут на feed_update (сек)

REDIS_HOST = os.getenv('REDIS_HOST', '127.0.0.1')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
BOTS_REDIS_DB_ID = int(os.getenv('BOTS_REDIS_DB_ID', '1'))


# Глобальный Redis клиент
# redis_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управляет жизненным циклом приложения"""

    logger.info("Clustered Bots Service starting up...")

    try:
        # Инициализация Redis-клиентов
        await init_redis_clients(app)

        # Загрузка ботов
        # Словарь всех ботов
        # bot_name -> {"bot": Bot, "dp": Dispatcher, "internal_key": str}
        app.state.bots = {}
        load_bots(app.state.bots, bots_root=BOTS_ROOT)
        BotStateManager.set_bots(app.state.bots)

        logger.info(f"Боты успешно загружены: {list(app.state.bots.keys())}")
        yield

        # Завершение при остановке
        logger.info("Clustered Bots Service shutting down...")

        BotStateManager.clear()

        # Закрытие сессий ботов
        for bot_name, bot_conf in app.state.bots.items():
            try:
                await bot_conf["bot"].session.close()
                logger.info(f"Сессия бота {bot_name} закрыта")
            except Exception as e:
                logger.error(f"Ошибка закрытия сессии бота {bot_name}: {e}")

        # Закрытие Redis-клиентов
        if hasattr(app.state, 'redis_client') and app.state.redis_client:
            await app.state.redis_client.close()
            logger.info("Redis client закрыт")

        logger.info("✅ Все ресурсы успешно освобождены")

    finally:
        logger.info("Clustered Bots Service shutting down...")

        try:
            BotStateManager.clear()

            # Закрытие соединений ботов
            await close_bot_connections(app.state.bots)

            # Закрытие Redis-клиентов
            await close_redis_clients(app)

            logger.info(" Все ресурсы успешно освобождены")
        except Exception as e:
            logger.error(f"Ошибка при завершении работы: {e}")


app = FastAPI(
    title="Clustered Bots Service",
    description="Internal API для кластера ботов",
    lifespan=lifespan
)


# # --- Startup / Shutdown ---
# @app.on_event("startup")
# async def on_startup():
#     global redis_client
#
#     # Инициализируем асинхронный Redis-клиент
#     redis_client = Redis(
#         host=REDIS_HOST,
#         port=REDIS_PORT,
#         db=BOTS_REDIS_DB_ID,
#         decode_responses=False  # Для эффективной работы с байтами
#     )
#     logger.info(f"Redis client initialized: {REDIS_HOST}:{REDIS_PORT}/{BOTS_REDIS_DB_ID}")
#
#     logger.info("Clustered Bots Service starting up...")
#     load_bots()
#     logger.info(f"Боты зарегистрированы: {list(BOTS.keys())}")

#
# @app.on_event("shutdown")
# async def on_shutdown():
#     for bot_conf in BOTS.values():
#         await bot_conf["bot"].session.close()
#
#     # Закрываем Redis-клиент
#     if redis_client:
#         await redis_client.close()
#         logger.info("Redis client closed")
#
#     logger.info("Clustered Bots Service stopped")


async def get_redis_client(request: Request):
    """Получает Redis-клиент из состояния приложения"""
    return request.app.state.redis_client


# --- Feed update с Retry ---
async def feed_update_with_retry(bot: Bot, dispatcher: Dispatcher, update: types.Update, bot_name: str):
    bot_tag = f"[Bot:{bot_name}]"
    # Извлекаем ID обновления безопасно
    update_id = None

    # Логируем структуру update для отладки
    bot_logger.debug(f"Структура update при получении: {type(update)}")
    bot_logger.debug(f"update.as_dict(): {yaml.dump(update.model_dump(), default_flow_style=False)}")

    # Сначала пробуем стандартный update_id
    if hasattr(update, 'update_id') and update.update_id:
        update_id = update.update_id
    # Для callback_query
    elif hasattr(update, 'callback_query'):
        update_id = f"cb_{update.callback_query.id}"
        # Важно: для callback ID сообщения получаем через callback_query.message
        if hasattr(update.callback_query, 'message') and hasattr(update.callback_query.message, 'message_id'):
            bot_logger.debug(f"Callback message_id: {update.callback_query.message.message_id}")
    # Для обычных сообщений
    elif hasattr(update, 'message') and hasattr(update.message, 'message_id'):
        update_id = f"msg_{update.message.message_id}"
    # Для других типов апдейтов
    else:
        # Дополнительные проверки для других типов апдейтов
        if hasattr(update, 'edited_message') and hasattr(update.edited_message, 'message_id'):
            update_id = f"edit_{update.edited_message.message_id}"
        elif hasattr(update, 'channel_post') and hasattr(update.channel_post, 'message_id'):
            update_id = f"chpost_{update.channel_post.message_id}"
        else:
            update_id = "unknown"
            bot_logger.warning(f"Не удалось определить update_id для объекта типа: {type(update)}")

    last_exception = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await asyncio.wait_for(dispatcher.feed_update(bot, update), timeout=FEED_TIMEOUT)
            logger.info(f"{bot_tag} (attempt {attempt}) Update id={update_id} успешно обработан ботом")
            return
        except Exception as e:
            logger.warning(f"{bot_tag} (attempt {attempt}) Update id={update_id} завершился ошибкой: {e}")
            last_exception = e
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)
    logger.error(f"{bot_tag} Update id={update_id} не обработан после {MAX_RETRIES} попыток")
    raise last_exception


@app.post("/internal/update")
async def internal_update(
        request: Request,
        background_tasks: BackgroundTasks,
        redis_client=Depends(get_redis_client)
):
    """
    Принимает апдейт от Gateway и проксирует в нужного бота.
    Мгновенно отвечает OK.
    Обработка апдейта — в фоне.
    """
    key = request.headers.get("X-Internal-Key")
    data = await request.json()

    bot_name = data.get("bot_name")
    update_data = data.get("update")
    update_id = update_data.get("update_id") if update_data else None

    if not bot_name or not update_data:
        logger.warning("400 Bad Request: Отсутствует bot_name или update")
        raise HTTPException(status_code=400, detail="Missing bot_name or update")

    bot_conf = BotStateManager.get_bot(bot_name=bot_name)
    if bot_conf is None:
        logger.warning(f"404 Bot not found: {bot_name}")
        raise HTTPException(status_code=404, detail="Bot not found")

    if key != bot_conf["internal_key"]:
        logger.warning(f"403 Forbidden: Invalid internal key for {bot_name}")
        raise HTTPException(status_code=403, detail="Forbidden")

    # тест-проверка Update
    try:
        update = types.Update(**update_data)
    except Exception as e:
        logger.error(f"Ошибка парсинга update: {e}")
        raise HTTPException(status_code=400, detail="Invalid update format")

    if update_id:
        try:
            duplicate_key = f"telegram:processed:{update_id}"
            exists = await redis_client.exists(duplicate_key)
            if exists:
                logger.info(f"Дубликат update_id={update_id}, отклоняем обработку")
                return {"accepted": True, "duplicate": True}
        except Exception as e:
            logger.error(f"Ошибка при проверке дубликата в Redis: {e}")
            # При ошибке продолжаем обработку (лучше обработать лишний раз, чем потерять апдейт)
    # background_tasks.add_task(
    #     feed_update_with_retry,
    #     bot_conf["bot"],
    #     bot_conf["dp"],
    #     update,
    #     bot_name
    # )
    from bots.tasks import process_update_task
    process_update_task.delay(bot_name, update_data)

    return {"accepted": True}


# --- Запуск ---
if __name__ == "__main__":
    uvicorn.run("bots_engine:app", host=INTERNAL_BOT_API_IP, port=INTERNAL_BOT_API_PORT, reload=True)
