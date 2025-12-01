import asyncio
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
import httpx

from api_gateway.config import GATEWAY_SETTINGS
from utils.setup_logger import setup_logger

logger = setup_logger(
    __name__,
    log_dir="logs/api_gateway",
    log_file="gateway.log",
    logger_level=10,
    file_level=10,
    console_level=20
)

router = APIRouter(prefix="/webhook", tags=["Telegram Webhook"])

MAX_RETRIES = 3
RETRY_DELAY = 1.5
TIMEOUT = 5.0


async def forward_update(bot_name: str, bot_conf, update_data: dict):
    """Фоновая обработка — отправка апдейта во внутренний API."""
    update_id = update_data.get("update_id")
    last_exception = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.post(
                    GATEWAY_SETTINGS.internal_bot_api_url,
                    headers={"X-Internal-Key": bot_conf.internal_key},
                    json={"bot_name": bot_name, "update": update_data},
                )
                resp.raise_for_status()

                logger.info(
                    f"Апдейт {update_id} для {bot_name} проксирован успешно (attempt {attempt})"
                )
                return

        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            logger.warning(f"[{bot_name}] Попытка {attempt} failed: {e}")
            last_exception = e
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)

    logger.error(
        f"[{bot_name}] Апдейт {update_id} не проксирован после {MAX_RETRIES} попыток\n"
        f"Ошибка: {last_exception}"
    )


@router.post("/{bot_name}/")
async def telegram_webhook(bot_name: str, request: Request, background_tasks: BackgroundTasks):
    token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if token != GATEWAY_SETTINGS.webhook_secret:
        logger.warning(f"Webhook 403 Invalid secret token for bot {bot_name}")
        raise HTTPException(status_code=403, detail="Invalid secret token")

    bots = GATEWAY_SETTINGS.bots

    if bot_name not in bots:
        logger.warning(f"Webhook 404 Bot not found: {bot_name}")
        raise HTTPException(status_code=404, detail="Bot not found")

    bot_conf = bots[bot_name]

    update_data = await request.json()
    update_id = update_data.get("update_id")

    logger.debug(f"Получен апдейт {update_id} для {bot_name}")

    # Добавляем фоновые задачи — обработку апдейта
    background_tasks.add_task(forward_update, bot_name, bot_conf, update_data)

    # отвечаем Telegram
    return {"ok": True}
