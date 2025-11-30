import os
import importlib
from celery import Celery
from pathlib import Path
from celery.signals import worker_ready, worker_shutdown
from dotenv import load_dotenv

load_dotenv()

REDIS_HOST = os.getenv('REDIS_HOST', '127.0.0.1')
REDIS_PORT = os.getenv('REDIS_PORT', '6379')
BOTS_REDIS_DB_ID = os.getenv('BOTS_REDIS_DB_ID', '1')

CELERY_BROKER_URL = f'redis://{REDIS_HOST}:{REDIS_PORT}/{BOTS_REDIS_DB_ID}'
CELERY_RESULT_BACKEND = f'redis://{REDIS_HOST}:{REDIS_PORT}/{BOTS_REDIS_DB_ID}'

celery_app = Celery('bots_tasks')

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
    task_modules = []

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

celery_app.autodiscover_tasks(packages=['bots'], related_name='tasks', force=True)

logger = celery_app.log.get_default_logger()


@worker_ready.connect
def worker_ready_handler(sender, **kwargs):
    logger.info(f"Celery worker {sender.hostname} готов к работе")
    logger.info(f"Загружены задачи: {list(celery_app.tasks.keys())}")


@worker_shutdown.connect
def worker_shutdown_handler(sender, **kwargs):
    logger.info(f"Celery worker {sender.hostname} завершает работу")

# можно запускать разные воркеры для разных очередей с разной приоритетностью или ресурсами.
# Воркер только для Telegram-апдейтов (высокий приоритет, быстрая реакция)
# celery -A bots.celery_app worker -Q telegram_updates -c 4

# Воркер для фоновых операций (сохранение, отчёты)
# celery -A bots.celery_app worker -Q drf_saves,bots_default -c 2
