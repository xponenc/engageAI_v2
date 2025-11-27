"""
Security middleware для Assessment API.

Разрешает:
 - внутренние запросы от Telegram-ботов (X-Internal-Key)
 - запросы из браузера (User-Agent содержит 'Mozilla')
"""

from fastapi import Header, HTTPException, Request
from config import BOTS
from utils.setup_logger import setup_logger

logger = setup_logger(
    __name__,
    log_dir="logs/backend",
    log_file="security.log",
    logger_level=10,
    file_level=10,
    console_level=20
)

INTERNAL_KEYS = {conf["key"] for conf in BOTS.values()}


async def verify_internal_or_web(
    request: Request,
    x_internal_key: str | None = Header(default=None)
):
    ua = request.headers.get("User-Agent", "")

    # WEB-клиент (браузер)
    if "Mozilla" in ua:
        logger.debug("Web-client authorized")
        return True

    # Telegram → внутренний ключ
    if x_internal_key in INTERNAL_KEYS:
        logger.debug("Bot authorized via X-Internal-Key")
        return True

    logger.warning("Forbidden access: missing X-Internal-Key")
    raise HTTPException(status_code=403, detail="Forbidden")
