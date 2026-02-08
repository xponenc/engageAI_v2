import asyncio
import os
import importlib
from celery import Celery
from pathlib import Path
from celery.signals import worker_ready, worker_shutdown
from dotenv import load_dotenv

import sys
import os
from pathlib import Path

load_dotenv()

REDIS_HOST = os.getenv('REDIS_HOST', '127.0.0.1')
REDIS_PORT = os.getenv('REDIS_PORT', '6379')
BOTS_REDIS_DB_ID = os.getenv('BOTS_REDIS_DB_ID', '1')

CELERY_BROKER_URL = f'redis://{REDIS_HOST}:{REDIS_PORT}/{BOTS_REDIS_DB_ID}'
CELERY_RESULT_BACKEND = f'redis://{REDIS_HOST}:{REDIS_PORT}/{BOTS_REDIS_DB_ID}'

celery_app = Celery('bots')
logger = celery_app.log.get_default_logger()

celery_app.config_from_object({
    'broker_url': CELERY_BROKER_URL,
    'result_backend': CELERY_RESULT_BACKEND,
    'task_serializer': 'json',
    'accept_content': ['json'],
    'result_serializer': 'json',
    'timezone': 'Europe/Moscow',
    'enable_utc': True,
    'task_routes': {
        'bots.tasks.process_update_task': {'queue': 'telegram_updates'},
        'bots.tasks.save_to_drf_async': {'queue': 'drf_saves'},
        'bots.*.*': {'queue': 'bots_default'},
    },
    'task_default_queue': 'default',
    'task_default_exchange': 'tasks',
    'task_default_routing_key': 'task.default',
})


def autodiscover_bot_tasks():
    """Автоматически находит все файлы tasks.py в папках ботов"""
    bots_root = Path(__file__).parent
    task_modules = ["bots.tasks"]

    # Ищем все директории ботов
    for item in bots_root.iterdir():
        if item.is_dir() and not item.name.startswith('__') and item.name != 'utils':
            # Проверяем наличие файла tasks.py
            tasks_file = item / 'tasks.py'
            if tasks_file.exists():
                module_name = f"bots.{item.name}.tasks"
                task_modules.append(module_name)
                logger.info(f"Найдены задачи в модуле: {module_name}")

    return task_modules


# Загружаем задачи
celery_app.autodiscover_tasks(
    packages=autodiscover_bot_tasks,
    related_name='tasks',
    force=True
)

# celery_app.autodiscover_tasks(packages=['bots'], related_name='tasks', force=True)
# celery_app.autodiscover_tasks(['bots'], force=True)
celery_app.conf.bots = {}



@worker_ready.connect
def worker_ready_handler(sender, **kwargs):
    logger.info(f"Celery worker {sender.hostname} готов к работе")
    logger.info(f"Загружены задачи: {list(celery_app.tasks.keys())}")


@worker_shutdown.connect
def worker_shutdown_handler(sender, **kwargs):
    logger.info(f"Celery worker {sender.hostname} завершает работу")


@worker_ready.connect
def init_bots_on_worker_start(sender, **kwargs):
    """Загружает ботов при запуске каждого Celery-воркера"""
    logger.info(f"Воркер {sender.hostname} начинает загрузку ботов...")

    # Определяем путь к директории с ботами
    # Важно: путь должен быть относительно корня проекта
    project_root = Path(__file__).parent.parent  # Поднимаемся до engageAI_v2/
    bots_root = project_root / "bots"

    # Очищаем существующее состояние
    sender.app.conf.bots = {}

    # Используем существующую функцию load_bots
    from bots.services.startup_process import load_bots
    load_bots(sender.app.conf.bots, bots_root)

    logger.info(f"Воркер {sender.hostname} загрузил ботов: {list(sender.app.conf.bots.keys())}")
    logger.info(f"Всего загружено ботов: {len(sender.app.conf.bots)}")


#
# @worker_shutdown.connect
# def shutdown_bots_on_worker_stop(sender, **kwargs):
#     """Закрывает соединения ботов при остановке воркера"""
#     logger.info(f"Воркер {sender.hostname} начинает завершение работы...")
#
#     # if hasattr(sender.app.conf, 'bots') and sender.app.conf.bots:
#     #     for bot_name, bot_conf in sender.app.conf.bots.items():
#     #         try:
#     #             # Закрываем сессию бота
#     #             if hasattr(bot_conf["bot"], 'session') and bot_conf["bot"].session:
#     #                 bot_conf["bot"].session.close()
#     #                 logger.info(f"Сессия бота {bot_name} закрыта")
#     #         except Exception as e:
#     #             logger.error(f"Ошибка закрытия сессии бота {bot_name}: {e}")
#     #
#     #     # Очищаем состояние
#     #     sender.app.conf.bots = {}
#     #     logger.info("Все боты остановлены и состояние очищено")
#
#     bots = getattr(sender.app.conf, 'bots', {})
#     if not bots:
#         return
#
#     async def close_sessions():
#         for bot_name, bot_conf in list(bots.items()):  # list() чтобы избежать изменений во время итерации
#             bot = bot_conf.get("bot")
#             if bot and hasattr(bot, "session") and bot.session:
#                 try:
#                     await bot.session.close()
#                     logger.info(f"Сессия бота {bot_name} закрыта асинхронно")
#                 except Exception as e:
#                     logger.error(f"Ошибка закрытия сессии {bot_name}: {e}")
#         sender.app.conf.bots.clear()
#
#     # Универсальный запуск
#     try:
#         loop = asyncio.get_running_loop()
#         loop.create_task(close_sessions())  # не блокируем shutdown
#     except RuntimeError:  # нет запущенного loop'а (редко)
#         asyncio.run(close_sessions())


def shutdown_bots_on_worker_stop(sender, **kwargs):
    """Корректное закрытие асинхронных сессий ботов при остановке воркера"""
    logger.info(f"Воркер {sender.hostname} начинает завершение работы...")

    bots = getattr(sender.app.conf, 'bots', {})
    if not bots:
        logger.info("Нет загруженных ботов для закрытия")
        return

    async def close_sessions():
        """Асинхронное закрытие всех сессий ботов"""
        close_tasks = []
        for bot_name, bot_conf in list(bots.items()):
            bot = bot_conf.get("bot")
            if bot and hasattr(bot, "session") and bot.session and not bot.session.closed:
                logger.debug(f"Запрашивается закрытие сессии для бота {bot_name}")
                close_tasks.append(bot.session.close())

        if close_tasks:
            results = await asyncio.gather(*close_tasks, return_exceptions=True)
            for bot_name, result in zip(bots.keys(), results):
                if isinstance(result, Exception):
                    logger.error(f"Ошибка закрытия сессии {bot_name}: {result}")
                else:
                    logger.info(f"Сессия бота {bot_name} успешно закрыта")
        else:
            logger.info("Нет активных сессий для закрытия")

        # Очищаем состояние после закрытия всех сессий
        sender.app.conf.bots.clear()

    try:
        # Проверяем, есть ли запущенный event loop
        loop = asyncio.get_running_loop()
        logger.debug("Обнаружен запущенный event loop")

        # Создаем задачу и ждем ее завершения с таймаутом
        task = loop.create_task(close_sessions())
        try:
            loop.run_until_complete(asyncio.wait_for(task, timeout=5.0))
            logger.info("Все сессии ботов закрыты в основном event loop")
        except asyncio.TimeoutError:
            logger.warning("Таймаут при закрытии сессий (5 секунд). Некоторые соединения могут быть не закрыты")
        except Exception as e:
            logger.error(f"Критическая ошибка при закрытии сессий: {e}")

    except RuntimeError:
        # Нет активного event loop - создаем новый
        logger.debug("Создание нового event loop для закрытия сессий")
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            new_loop.run_until_complete(close_sessions())
            logger.info("Все сессии ботов закрыты в новом event loop")
        except Exception as e:
            logger.error(f"Ошибка в новом event loop при закрытии сессий: {e}")
        finally:
            new_loop.close()
            asyncio.set_event_loop(None)

# можно запускать разные воркеры для разных очередей с разной приоритетностью или ресурсами.
# Воркер только для Telegram-апдейтов (высокий приоритет, быстрая реакция)
# celery -A bots.celery_app worker -Q telegram_updates -c 4

# Воркер для фоновых операций (сохранение, отчёты)
# celery -A bots.celery_app worker -Q drf_saves,bots_default -c 2

# Windows
# celery -A bots.celery_app worker --loglevel=INFO --pool=solo --queues=telegram_updates,drf_saves
