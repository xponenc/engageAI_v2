"""
Основной модуль API Gateway:
- FastAPI приложение с Lifespan
- Проксирование апдейтов Telegram в внутренние боты
- Подключение роутеров: webhook_setup и assessment
"""
import sys

from fastapi import FastAPI
from contextlib import asynccontextmanager
from api_gateway.config import GATEWAY_SETTINGS

from routers import webhook_setup
# from routers.assessment import router as assessment_router
from utils.setup_logger import setup_logger
from aiogram import Bot

logger = setup_logger(
    __name__,
    log_dir="logs/api_gateway",
    log_file="gateway.log",
    logger_level=10,
    file_level=10,
    console_level=20
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan FastAPI: автоматическая установка webhook при старте сервера
    и логирование shutdown.
    """
    logger.info("Main FastApi Gateway starting up...")

    bots = GATEWAY_SETTINGS.bots
    for bot_name, bot_config in bots.items():
        bot_token = bot_config.token
        bot = Bot(bot_token)

        webhook_url = f"{GATEWAY_SETTINGS.webhook_host}/webhook/{bot_name}"
        logger.info(webhook_url)
        webhook_host = GATEWAY_SETTINGS.webhook_host.strip().rstrip('/')
        bot_name_clean = bot_name.strip()
        webhook_url = f"{webhook_host}/webhook/{bot_name_clean}/"
        logger.info(f"Чистый webhook URL: '{webhook_url}'")  # Для отладки
        try:
            await bot.delete_webhook()
            result = await bot.set_webhook(webhook_url, secret_token=GATEWAY_SETTINGS.webhook_secret)
            logger.info(f"Main FastApi Gateway - Webhook автоматически установлен для"
                        f" {bot_name}: {webhook_url} - {result}")
        except Exception as e:
            logger.error(f"Main FastApi Gateway - Не удалось установить webhook для {bot_name}: {e}")
        finally:
            await bot.session.close()

    yield  # Всё что после yield → shutdown
    logger.info("Main FastApi Gateway Gateway shutting down...")

# Создание FastAPI с lifespan
app = FastAPI(title="Universal Telegram Gateway", lifespan=lifespan, redirect_slashes=False)

# Подключение роутеров
app.include_router(webhook_setup.router)
# app.include_router(assessment_router)

@app.get("/")
async def root():
    """Проверка статуса шлюза"""
    logger.info("Ping / status check")
    return {"status": "gateway_ok"}


# ---------------------------------------
# Запуск через uvicorn
# ---------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("core_webhook:app", host=GATEWAY_SETTINGS.fastapi_ip, port=GATEWAY_SETTINGS.fastapi_port, reload=False)
