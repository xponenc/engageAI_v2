import importlib
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import StateFilter
from aiogram.fsm.storage.base import DefaultKeyBuilder
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import Message
from dotenv import load_dotenv
from fastapi import FastAPI
from redis.asyncio import Redis

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

PROJECT_ROOT = Path(__file__).parent.parent
BOTS_ROOT = PROJECT_ROOT / "bots"
INTERNAL_BOT_API_IP = os.getenv("INTERNAL_BOT_API_IP")
INTERNAL_BOT_API_PORT = int(os.getenv("INTERNAL_BOT_API_PORT"))

MAX_RETRIES = 3  # количество попыток feed_update
RETRY_DELAY = 1.5  # задержка между попытками (сек)
FEED_TIMEOUT = 5.0  # таймаут на feed_update (сек)

REDIS_HOST = os.getenv('REDIS_HOST', '127.0.0.1')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
BOTS_REDIS_DB_ID = int(os.getenv('BOTS_REDIS_DB_ID', '1'))


async def init_redis_clients(app: FastAPI):
    """Инициализирует все необходимые Redis-клиенты"""
    # global redis_client

    # Основной клиент
    redis_client = Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=BOTS_REDIS_DB_ID,
        decode_responses=False
    )
    app.state.redis_client = redis_client
    logger.info(f"Основной Redis клиент инициализирован: {REDIS_HOST}:{REDIS_PORT}/{BOTS_REDIS_DB_ID}")


async def close_redis_clients(app: FastAPI):
    """Корректно закрывает все Redis-соединения"""
    if hasattr(app.state, 'redis_client') and app.state.redis_client:
        await app.state.redis_client.close()
        logger.info("Основной Redis клиент закрыт")


def load_bots(bots_dict: dict, bots_root: Path):
    """Динамическая загрузка ботов"""
    logger.info(f"Загрузка ботов из директории: {bots_root}")

    # Ищем только те директории, где есть config.py в корне
    bot_folders = [
        p for p in bots_root.iterdir()
        if p.is_dir()
           and p.name != "__pycache__"
           and (p / "config.py").exists()
    ]

    logger.info(f"Найдено ботов: {len(bot_folders)}")

    for folder in bot_folders:
        config_path = folder / "config.py"
        handlers_path = folder / "handlers"

        if not config_path.exists():
            logger.warning(f"Пропускаем папку {folder.name} - нет config.py")
            continue

        # Загрузка config.py бота
        spec = importlib.util.spec_from_file_location("config", config_path)
        config_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config_module)

        bot_name = getattr(config_module, "BOT_NAME", None)
        bot_token = getattr(config_module, "BOT_TOKEN", None)
        internal_key = getattr(config_module, "BOT_INTERNAL_KEY", None)
        bot_assistant_slug = getattr(config_module, "BOT_ASSISTANT_SLUG", None)

        if not all([bot_name, bot_token, internal_key]):
            logger.error(f"Bot {folder.name} имеет неполную конфигурацию\n"
                         f"bot_name={bot_name}\nbot_token={bot_token}\ninternal_key={internal_key}\n")
            continue

        # Создаём Bot и Dispatcher
        bot = Bot(bot_token)

        # bot_redis_client = Redis(
        #     host="localhost",
        #     port=6379,
        #     db=2,
        #     decode_responses=True
        # )
        bot_redis_client = Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=2,  # Отдельная БД для FSM ботов
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            health_check_interval=30
        )

        storage = RedisStorage(
            redis=bot_redis_client,
            key_builder=DefaultKeyBuilder(with_bot_id=True)  # чтобы разные боты не пересекались
        )

        dp = Dispatcher(storage=storage)
        # dp = Dispatcher()
        bot.dispatcher = dp
        bot.assistant_slug = bot_assistant_slug

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

        # Подключаем обычные хендлеры
        for router, filename in normal_handlers:
            dp.include_router(router)
            logger.info(f"Router из {filename} подключен для бота {bot_name}")

        # Подключаем fallback хендлеры (всегда в конце)
        for router, filename in fallback_handlers:
            dp.include_router(router)
            logger.info(f"Fallback router из {filename} подключен ПОСЛЕДНИМ для бота {bot_name}")

        # Если нет fallback хендлеров, добавляем эхо как запасной вариант
        if not fallback_handlers:
            logger.debug(f"Для бота {bot_name} не найдено fallback-хендлеров, добавляется эхо")
            echo_router = Router()

            @echo_router.message(StateFilter(None))
            async def echo_message_handler(message: Message):
                await message.answer(f"Эхо от {bot_name}: {message.text}")

            dp.include_router(echo_router)
            logger.info(f"Echo router подключен для бота {bot_name}")

        if bot_name in bots_dict:
            logger.error(f"Конфликт имени бота: {bot_name}")
            continue

        bots_dict[bot_name] = {
            "bot": bot,
            "dp": dp,
            "internal_key": internal_key,
            "assistant_slug": bot_assistant_slug,
        }

        logger.info(f"Бот {bot_name} успешно загружен. Всего роутеров: {len(normal_handlers) + len(fallback_handlers)}")


async def close_bot_connections(bots_dict: dict):
    """Закрывает соединения всех ботов"""
    for bot_name, bot_conf in bots_dict.items():
        try:
            await bot_conf["bot"].session.close()
            logger.info(f"Соединение бота {bot_name} закрыто")
        except Exception as e:
            logger.error(f"Ошибка закрытия соединения бота {bot_name}: {e}")
