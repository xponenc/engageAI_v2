from dotenv import dotenv_values
from pathlib import Path
import sys

from pydantic import BaseModel, Field, field_validator, model_validator, ValidationError

from utils.setup_logger import setup_logger

logger = setup_logger(
    __name__,
    log_dir="logs/api_gateway",
    log_file="gateway.log",
    logger_level=10,  # DEBUG
    file_level=10,
    console_level=20
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GATEWAY_ENV_PATH = PROJECT_ROOT / "api_gateway" / ".env"

class ConfigError(Exception):
    """Ошибка некорректной конфигурации API Gateway"""
    pass

class BotConfig(BaseModel):
    """Модель настроек Telegram бота"""
    name: str
    token: str
    internal_key: str = Field(min_length=32)


class GatewayConfig(BaseModel):
    """Модель настроек сервера"""
    fastapi_ip: str = Field(..., alias="FAST_API_IP")
    fastapi_port: int = Field(..., alias="FAST_API_PORT")

    webhook_secret: str = Field(..., alias="WEBHOOK_SECRET")
    webhook_host: str = Field(..., alias="WEBHOOK_HOST")

    internal_bot_api_ip: str = Field(..., alias="INTERNAL_BOT_API_IP")
    internal_bot_api_port: int = Field(..., alias="INTERNAL_BOT_API_PORT")
    internal_bot_api_url: str = None  # будет заполнено автоматически

    bots: dict[str, BotConfig]

    @model_validator(mode="after")
    def make_urls(self):
        self.internal_bot_api_url = (
            f"http://{self.internal_bot_api_ip}:{self.internal_bot_api_port}/internal/update"
        )
        return self

    @field_validator("bots", mode="after")
    def unique_bots(cls, bots):
        names = [b.name for b in bots.values()]
        keys = [b.internal_key for b in bots.values()]

        if len(names) != len(set(names)):
            raise ValueError("Имена ботов должны быть уникальными")

        if len(keys) != len(set(keys)):
            raise ValueError("internal_key всех ботов должен быть уникальным")

        return bots


def load_gateway_env() -> dict:
    config = dotenv_values(GATEWAY_ENV_PATH)
    if not config:
        msg = f"Не удалось загрузить {GATEWAY_ENV_PATH}"
        logger.error(msg)
        raise ConfigError(msg)
    return config


def load_bots_env(config: dict) -> dict[str, BotConfig]:
    """Загрузка конфигурации ботов"""
    bots = {}
    for key, value in config.items():
        if key.startswith("BOT_NAME_"):
            bot_id = key.replace("BOT_NAME_", "")
            bot_name = value
            bot_token = config.get(f"BOT_TOKEN_{bot_id}")
            bot_internal_key = config.get(f"BOT_INTERNAL_KEY_{bot_id}")

            try:
                bot = BotConfig(
                    name=bot_name,
                    token=bot_token,
                    internal_key=bot_internal_key,
                )
                bots[bot.name] = bot
            except KeyError as e:
                msg = f"Ошибка конфигурации бота {bot_name}: {e}"
                logger.error(msg)
                raise ConfigError(msg)

    return bots


def load_config() -> GatewayConfig:
    """Загрузка конфигурации API"""
    gateway_env = load_gateway_env()
    bots = load_bots_env(config=gateway_env)

    try:
        cfg = GatewayConfig(
            **gateway_env,
            bots=bots,
        )
    except ValidationError as e:
        msg = "Ошибка валидации конфигурации Gateway:\n" + str(e)
        logger.error(msg)
        raise ConfigError(msg)

    logger.info(f"Gateway конфигурация загружена: {cfg.fastapi_ip}:{cfg.fastapi_port}")
    logger.info(f"Боты зарегистрированы: {list(cfg.bots.keys())}")

    return cfg


try:
    GATEWAY_SETTINGS = load_config()
except ValidationError as e:
    logger.error(f"Main FastApi Gateway - ошибка загрузки конфигурации {e}")
    raise