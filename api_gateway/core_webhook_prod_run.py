# prod_server.py
import uvicorn
import os
import multiprocessing

from api_gateway.config import GATEWAY_SETTINGS


def get_optimal_workers():
    """Рассчитывает оптимальное количество воркеров"""
    cpu_count = multiprocessing.cpu_count()
    # В Docker cpu_count может вернуть все ядра хоста, а не контейнера
    if os.getenv("DOCKER_ENV"):
        try:
            # Читаем лимиты CPU из cgroups (для Linux-контейнеров)
            with open('/sys/fs/cgroup/cpu/cpu.cfs_quota_us') as f:
                quota = int(f.read())
            with open('/sys/fs/cgroup/cpu/cpu.cfs_period_us') as f:
                period = int(f.read())
            if quota > 0 and period > 0:
                return max(1, int(quota / period * 2 + 1))
        except (FileNotFoundError, ValueError):
            pass

    # Формула: (2 * ядра) + 1
    return max(1, (cpu_count * 2) + 1)


if __name__ == "__main__":
    uvicorn.run(
        "core_webhook:app",
        host=GATEWAY_SETTINGS.fastapi_ip,
        port=GATEWAY_SETTINGS.fastapi_port,
        workers=get_optimal_workers(),  # Динамический расчет воркеров
        lifespan="on",
        proxy_headers=True,  # Обработка X-Forwarded-* заголовков от Nginx
        # forwarded_allow_ips="*",  # Доверять всем прокси (настраивается в Nginx)
        log_level="warning",  # Меньше шума в продакшене
        access_log=False,  # Отключить детальные логи запросов
        timeout_keep_alive=60,  # Время удержания соединения WebSocket
    )