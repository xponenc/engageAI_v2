import sys
from pathlib import Path

from celery import Celery, signals
import os

from celery.schedules import crontab

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'engageai_core.settings')

app = Celery('engageai_core')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

#
# @signals.worker_process_init.connect
# def init_worker(**kwargs):
#     # # Инициализация классов парсеров
#     # from app_parsers.services.parsers.init_registry import initialize_parser_registry
#     # initialize_parser_registry()
#     # # Инициализация классов сплиттеров
#     # from app_chunks.splitters.init_registry import initialize_splitter_registry
#     # initialize_splitter_registry()
#     pass

app.conf.beat_schedule = {
    'cleanup-stale-thumbnail-tasks': {
        'task': 'chat.tasks.cleanup_stale_thumbnail_tasks',
        'schedule': crontab(minute='*/720'),  # Каждые 720 минут
    },
}