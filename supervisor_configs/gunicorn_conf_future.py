"""Конфигурация под Channels gunicorn + uvicorn"""

import os
import multiprocessing
import time

from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv('/home/bo/projects/engageAI_v2/.env')


# Автоматический расчет воркеров для Channels
def calculate_workers():
    """Оптимизация под WebSocket-нагрузку"""
    cpu_cores = multiprocessing.cpu_count()

    # Для WebSocket лучше меньше воркеров, но больше соединений на воркер
    if os.getenv('DJANGO_ENV') == 'production':
        # Формула: (ядра * 1.5) + 1 для баланса CPU/RAM
        return max(2, int(cpu_cores * 1.5) + 1)
    return 2  # Для staging/testing


# Основные настройки
bind = '127.0.0.1:8000'
workers = calculate_workers()
worker_class = 'uvicorn.workers.UvicornWorker'  # КЛЮЧЕВОЕ ИЗМЕНЕНИЕ для ASGI

# Настройки для WebSocket
worker_connections = 1000  # Макс соединений на воркер (для чатов)
timeout = 300  # 5 минут вместо 120 сек (долгие AI-запросы)
graceful_timeout = 300  # Время на завершение WebSocket при SIGTERM
keepalive = 10  # Время удержания соединения

# Защита от проблем
max_requests = 1000  # Перезапускать воркер после N запросов (борьба с memory leaks)
max_requests_jitter = 100  # Рандомизация для избежания массового рестарта
limit_request_line = 0  # Без ограничений для длинных WebSocket-сообщений

# Пользователь и права
user = 'bo'
group = 'bo'
umask = 0o007  # Права 770 для сокетов

# Логирование
loglevel = 'info'
accesslog = "/home/bo/projects/engageAI_v2/logs/gunicorn_access.log"
errorlog = "/home/bo/projects/engageAI_v2/logs/gunicorn_error.log"
capture_output = True  # Перехватывать stdout/stderr

# Оптимизации
preload_app = True  # Экономия памяти через shared imports (требует аккуратности с глобальными переменными)
forwarded_allow_ips = '*'  # Доверять всем прокси (настраивается в Nginx)

# Специфичное для Channels
proxy_protocol = True if os.getenv('USE_PROXY_PROTOCOL', 'false') == 'true' else False


# Health-check для Kubernetes/systemd
def when_ready(server):
    """Создать файл-индикатор готовности"""
    with open('/tmp/app-initialized', 'w') as f:
        f.write(f'Workers: {workers}\n')


def on_exit(server):
    """Очистка при завершении"""
    if os.path.exists('/tmp/app-initialized'):
        os.remove('/tmp/app-initialized')


def post_request(worker, req, environ, resp):
    """Логировать медленные запросы"""
    duration = time.time() - req.start_time
    if duration > 5.0:  # Запросы дольше 5 сек
        worker.log.info(f"SLOW REQUEST: {req.path} took {duration:.2f}s")