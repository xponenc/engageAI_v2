"""
полный запуск тестового сервера через ngrok
"""
import subprocess
import time
import requests
from pathlib import Path
from dotenv import dotenv_values, set_key
import re
import threading

BASE_DIR = Path(__file__).resolve().parent
NGROK_PATH = BASE_DIR / "utils" / "ngrok.exe"
NGROK_CONFIG = BASE_DIR / "utils" / "ngrok.yml"
GATEWAY_ENV = BASE_DIR / "api_gateway" / ".env"
PROJECT_ENV = BASE_DIR / ".env"
DJANGO_SETTINGS = BASE_DIR / "engageai_core" / "engageai_core" / "local_settings.py"


def start_ngrok():
    print("🚀 Launching ngrok with visible logs...")
    # Запускаем ngrok с выводом в консоль для отладки
    return subprocess.Popen(
        [str(NGROK_PATH), "start", "--config", str(NGROK_CONFIG), "--all", "--log", "stdout"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1  # Построчный вывод
    )


def read_ngrok_logs(ngrok_proc):
    """Читает и выводит логи ngrok в реальном времени"""
    print("📋 ngrok logs:")
    print("-" * 50)
    for line in ngrok_proc.stdout:
        print(line.strip())
        # Ищем строку с веб-интерфейсом
        if "web interface" in line.lower():
            print(f"🔍 {line.strip()}")
    print("-" * 50)


def extract_port(addr_str):
    """Надежно извлекает номер порта из строки addr ngrok"""
    if not addr_str:
        return None

    # Убираем протокол если есть
    if addr_str.startswith(('http://', 'https://')):
        addr_str = addr_str.split('://', 1)[1]

    # Ищем порт в конце строки
    match = re.search(r':(\d+)$', addr_str)
    if match:
        return match.group(1)

    # Если порт указан отдельно
    if addr_str.isdigit():
        return addr_str

    return None


def get_ngrok_url(port, timeout=30):
    """Надежно получает ngrok URL для указанного порта"""
    print(f"⏳ Waiting for ngrok public URL for port {port}...")
    url = "http://127.0.0.1:4040/api/tunnels"

    start_time = time.time()
    last_error = None

    while time.time() - start_time < timeout:
        try:
            response = requests.get(url, timeout=1)
            response.raise_for_status()
            data = response.json()

            # Отладочная информация
            # print(f"Tunnel data: {json.dumps(data, indent=2)}")

            for tunnel in data.get("tunnels", []):
                # Извлекаем порт из конфигурации
                config = tunnel.get("config", {})
                addr = config.get("addr", "")

                # Проверяем соответствие порта
                tunnel_port = extract_port(addr)
                if tunnel_port != str(port):
                    continue

                # Ищем HTTPS URL
                public_url = tunnel.get("public_url", "")
                if public_url.startswith("https://"):
                    print(f"🌍 NGROK URL for port {port} detected: {public_url}")
                    return public_url

            # Проверяем по имени туннеля если не нашли по порту
            for tunnel in data.get("tunnels", []):
                name = tunnel.get("name", "").lower()
                public_url = tunnel.get("public_url", "")

                if str(port) in name and public_url.startswith("https://"):
                    print(f"🌍 NGROK URL for port {port} detected by name: {public_url}")
                    return public_url

        except Exception as e:
            last_error = str(e)
            print(f"⚠️ API error: {last_error}")

        time.sleep(1)

    # Финальная попытка получить данные для отладки
    try:
        response = requests.get(url, timeout=1)
        print(f"❌ Final API response: {response.text}")
    except:
        pass

    raise RuntimeError(
        f"❌ NGROK public URL for port {port} not found after {timeout}s. "
        f"Last error: {last_error}"
    )


# ---------------------------
# Update .env
# ---------------------------
def update_env(env_path, key, value):
    print(f"🔧 Updating {key} in {env_path}")
    set_key(str(env_path), key, value)
    print(f"✔ {key} updated to {value}")


# ---------------------------
# Update Django ALLOWED_HOSTS + INTERNAL_IPS + CSRF_TRUSTED_ORIGINS
# ---------------------------
def update_django_config(ngrok_url: str):
    """
    Обновляет локальный settings.py для Django:
      - добавляет ngrok URL в ALLOWED_HOSTS
      - добавляет ngrok хост в INTERNAL_IPS
      - добавляет ngrok хост в CSRF_TRUSTED_ORIGINS
    """
    host = ngrok_url.replace("https://", "").replace("http://", "")
    print(f"🔧 Updating Django config with {host}")

    with open(DJANGO_SETTINGS, "r+", encoding="utf-8") as f:
        content = f.read()

        # ALLOWED_HOSTS
        content = re.sub(
            r"ALLOWED_HOSTS\s*=\s*\[.*?\]",
            f'ALLOWED_HOSTS = ["127.0.0.1", "{host}"]',
            content
        ) if re.search(r"ALLOWED_HOSTS\s*=\s*\[.*?\]",
                       content) else content + f'\nALLOWED_HOSTS = ["127.0.0.1", "{host}"]\n'

        # INTERNAL_IPS
        content = re.sub(
            r"INTERNAL_IPS\s*=\s*\[.*?\]",
            f'INTERNAL_IPS = ["127.0.0.1", "{host}"]',
            content
        ) if re.search(r"INTERNAL_IPS\s*=\s*\[.*?\]",
                       content) else content + f'\nINTERNAL_IPS = ["127.0.0.1", "{host}"]\n'

        # CSRF_TRUSTED_ORIGINS
        content = re.sub(
            r"CSRF_TRUSTED_ORIGINS\s*=\s*\[.*?\]",
            f'CSRF_TRUSTED_ORIGINS = ["https://{host}"]',
            content
        ) if re.search(r"CSRF_TRUSTED_ORIGINS\s*=\s*\[.*?\]",
                       content) else content + f'\nCSRF_TRUSTED_ORIGINS = ["https://{host}"]\n'

        # Перезаписываем файл
        f.seek(0)
        f.write(content)
        f.truncate()

    print("✔ Django config updated (ALLOWED_HOSTS + INTERNAL_IPS + CSRF_TRUSTED_ORIGINS)")


# ---------------------------
# Start subprocesses
# ---------------------------
def start_gateway():
    env = dotenv_values(GATEWAY_ENV)
    print("🚀 Starting FastAPI Gateway...")
    return subprocess.Popen(
        ["uvicorn", "core_webhook:app", "--host", env.get("FAST_API_IP", "127.0.0.1"),
         "--port", env.get("FAST_API_PORT", "8001"), "--log-level", "warning", "--no-use-colors"],
        cwd=str(BASE_DIR / "api_gateway")
    )


def start_bots():
    env = dotenv_values(PROJECT_ENV)
    print("🤖 Starting Bots Cluster...")
    return subprocess.Popen(
        ["uvicorn", "bots_engine:app", "--host", env.get("INTERNAL_BOT_API_IP", "127.0.0.1"),
         "--port", env.get("INTERNAL_BOT_API_PORT", "8002"), "--log-level", "warning", "--no-use-colors"],
        cwd=str(BASE_DIR / "bots")
    )


def start_django():
    print("🟢 Starting Django server...")
    return subprocess.Popen(
        ["python", "manage.py", "runserver", "127.0.0.1:8000"],
        cwd=str(BASE_DIR / "engageai_core")
    )


def start_celery():
    print("⚡ Starting Celery worker...")
    return subprocess.Popen(
        ["celery", "-A", "engageai_core", "worker", "--pool=solo", "-l", "info"],
        cwd=str(BASE_DIR / "engageai_core")
    )


# ---------------------------
# Launcher
# ---------------------------
def main():
    print("======================================")
    print("      ENGAGE.AI – Launcher")
    print("======================================")

    ngrok_proc = start_ngrok()
    # Запускаем чтение логов в отдельном потоке
    log_thread = threading.Thread(target=read_ngrok_logs, args=(ngrok_proc,), daemon=True)
    log_thread.start()
    time.sleep(5)  # Даем время на запуск и вывод информации

    try:
        gateway_url = get_ngrok_url(8001)
        django_url = get_ngrok_url(8000)
    except Exception as e:
        print(e)
        ngrok_proc.kill()
        return

    update_env(GATEWAY_ENV, "WEBHOOK_HOST", gateway_url)
    update_django_config(django_url)

    gateway_proc = start_gateway()
    bots_proc = start_bots()
    django_proc = start_django()
    celery_proc = start_celery()

    print("\n🚀 All systems launched! Press CTRL+C to stop everything.\n")

    processes = [ngrok_proc, gateway_proc, bots_proc, django_proc, celery_proc]

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("🛑 Stopping all services...")
        for p in processes:
            p.kill()
        print("✔ All stopped cleanly.")


if __name__ == "__main__":
    main()
