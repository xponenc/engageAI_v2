bind = '127.0.0.1:8000'  # Оставляем, если используете Nginx
workers = 5              # Увеличиваем до 9 для лучшего использования CPU
threads = 2              # Добавляем 2–4 потока для I/O-bound задач
user = 'bo'              # Без изменений
timeout = 120            # Без изменений или уменьшить до 90, если запросы быстрые
loglevel = 'info'        # Добавляем для логирования
accesslog = "/home/bo/projects/engageAI_v2/logs/gunicorn_access.log"
errorlog = "/home/bo/projects/engageAI_v2/logs/gunicorn_error.log"
