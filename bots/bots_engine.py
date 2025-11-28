import os
import asyncio
from pathlib import Path
from typing import Dict

from aiogram.filters import StateFilter
from aiogram.fsm.storage.base import DefaultKeyBuilder
from aiogram.fsm.storage.redis import RedisStorage
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from aiogram import Bot, Dispatcher, types, Router
import importlib.util
import uvicorn
from redis.asyncio import Redis

from utils.setup_logger import setup_logger

logger = setup_logger(
    __name__,
    log_dir="logs/bots",
    log_file="bots.log",
    logger_level=10,   # DEBUG
    file_level=10,
    console_level=20   # INFO
)

load_dotenv()

BOTS_ROOT = Path(__file__).parent
INTERNAL_BOT_API_IP = os.getenv("INTERNAL_BOT_API_IP")
INTERNAL_BOT_API_PORT = int(os.getenv("INTERNAL_BOT_API_PORT"))

MAX_RETRIES = 3        # количество попыток feed_update
RETRY_DELAY = 1.5      # задержка между попытками (сек)
FEED_TIMEOUT = 5.0     # таймаут на feed_update (сек)

app = FastAPI(title="Clustered Bots Service", description="Internal API для кластера ботов")

# --- Словарь всех ботов ---
# bot_name -> {"bot": Bot, "dp": Dispatcher, "internal_key": str}
BOTS: Dict[str, Dict] = {}


# --- Динамическая загрузка ботов ---
def load_bots():
    bot_folders = [p for p in BOTS_ROOT.iterdir() if p.is_dir()]
    for folder in bot_folders:
        config_path = folder / "config.py"
        handlers_path = folder / "handlers"

        if not config_path.exists():
            continue

        # Загрузка config.py бота
        spec = importlib.util.spec_from_file_location("config", config_path)
        config_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config_module)

        bot_name = getattr(config_module, "BOT_NAME", None)
        bot_token = getattr(config_module, "BOT_TOKEN", None)
        internal_key = getattr(config_module, "BOT_INTERNAL_KEY", None)

        if not all([bot_name, bot_token, internal_key]):
            logger.error(f"Bot {folder.name} имеет неполную конфигурацию\n"
                         f"bot_name={bot_name}\nbot_token={bot_token}\ninternal_key={internal_key}\n")
            continue

        # Создаём Bot и Dispatcher
        bot = Bot(bot_token)

        redis_client = Redis(
            host="localhost",
            port=6379,
            db=2,
            decode_responses=True
        )

        storage = RedisStorage(
            redis=redis_client,
            key_builder=DefaultKeyBuilder(with_bot_id=True)  # чтобы разные боты не пересекались
        )

        dp = Dispatcher(storage=storage)
        # dp = Dispatcher()
        bot.dispatcher = dp

        # --- Подключение хендлеров ---
        normal_handlers = []
        fallback_handlers = []

        if handlers_path.exists() and handlers_path.is_dir():
            # Собираем все файлы с хендлерами
            handler_files = list(handlers_path.glob("*.py"))

            for py_file in handler_files:
                # Определяем тип хендлера по имени файла
                is_fallback = py_file.name.startswith('z_') or 'fallback' in py_file.name.lower()

                spec = importlib.util.spec_from_file_location("handler", py_file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Подключаем все Router'ы из модуля
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, Router):
                        if is_fallback:
                            fallback_handlers.append((attr, py_file.name))
                        else:
                            normal_handlers.append((attr, py_file.name))

        # --- Подключаем обычные хендлеры ---
        for router, filename in normal_handlers:
            dp.include_router(router)
            logger.info(f"Router из {filename} подключен для бота {bot_name}")

        # --- Подключаем fallback хендлеры (всегда в конце) ---
        for router, filename in fallback_handlers:
            dp.include_router(router)
            logger.info(f"Fallback router из {filename} подключен ПОСЛЕДНИМ для бота {bot_name}")

        # --- Если нет fallback хендлеров, добавляем эхо как запасной вариант ---
        if not fallback_handlers:
            logger.debug(f"Для бота {bot_name} не найдено fallback-хендлеров, добавляется эхо")
            echo_router = Router()

            @echo_router.message(StateFilter(None))
            async def echo_message_handler(message: types.Message):
                await message.answer(f"Эхо от {bot_name}: {message.text}")

            dp.include_router(echo_router)
            logger.info(f"Echo router подключен для бота {bot_name}")

        # --- Добавляем в глобальный словарь ---
        if bot_name in BOTS:
            logger.error(f"Конфликт имени бота: {bot_name}")
            continue

        BOTS[bot_name] = {
            "bot": bot,
            "dp": dp,
            "internal_key": internal_key
        }

        logger.info(f"Бот {bot_name} успешно загружен. Всего роутеров: {len(normal_handlers) + len(fallback_handlers)}")

# --- Feed update с Retry ---

async def feed_update_with_retry(bot: Bot, dp: Dispatcher, update: types.Update, bot_name: str):
    last_exception = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await asyncio.wait_for(dp.feed_update(bot, update), timeout=FEED_TIMEOUT)
            logger.info(f"Апдейт успешно обработан ботом {bot_name} (attempt {attempt})")
            return
        except Exception as e:
            logger.warning(f"Попытка {attempt} feed_update для {bot_name} не удалась: {e}")
            last_exception = e
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)
    # Если все попытки провалились
    logger.error(f"Апдейт для {bot_name} не обработан после {MAX_RETRIES} попыток")
    raise last_exception


@app.post("/internal/update")
async def internal_update(request: Request, background_tasks: BackgroundTasks):
    """
    Принимает апдейт от Gateway и проксирует в нужного бота.
    Мгновенно отвечает OK.
    Обработка апдейта — в фоне.
    """
    key = request.headers.get("X-Internal-Key")
    data = await request.json()

    bot_name = data.get("bot_name")
    update_data = data.get("update")

    if not bot_name or not update_data:
        logger.warning("400 Bad Request: Отсутствует bot_name или update")
        raise HTTPException(status_code=400, detail="Missing bot_name or update")

    if bot_name not in BOTS:
        logger.warning(f"404 Bot not found: {bot_name}")
        raise HTTPException(status_code=404, detail="Bot not found")

    bot_conf = BOTS[bot_name]

    if key != bot_conf["internal_key"]:
        logger.warning(f"403 Forbidden: Invalid internal key for {bot_name}")
        raise HTTPException(status_code=403, detail="Forbidden")

    # Создаём объект Update
    try:
        update = types.Update(**update_data)
    except Exception as e:
        logger.error(f"Ошибка парсинга update: {e}")
        raise HTTPException(status_code=400, detail="Invalid update format")

    background_tasks.add_task(
        feed_update_with_retry,
        bot_conf["bot"],
        bot_conf["dp"],
        update,
        bot_name
    )
    # process_update_task.delay(bot_name, update_data)  # TODO отправка задачи в Celery

    return {"accepted": True}


# --- Startup / Shutdown ---
@app.on_event("startup")
async def on_startup():
    logger.info("Clustered Bots Service starting up...")
    load_bots()
    logger.info(f"Боты зарегистрированы: {list(BOTS.keys())}")


@app.on_event("shutdown")
async def on_shutdown():
    for bot_conf in BOTS.values():
        await bot_conf["bot"].session.close()
    logger.info("Clustered Bots Service stopped")


# --- Запуск ---
if __name__ == "__main__":
    uvicorn.run("bots_engine:app", host=INTERNAL_BOT_API_IP, port=INTERNAL_BOT_API_PORT, reload=False)
