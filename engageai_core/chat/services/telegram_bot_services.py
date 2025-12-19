from pathlib import Path
from typing import Any

import requests
from django.conf import settings
from dotenv import dotenv_values


class TelegramBotService:
    """Сервис для взаимодействия с Telegram Bot API"""

    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def get_file(self, file_id: str) -> dict:
        """Получает информацию о файле"""
        response = requests.get(
            f"{self.base_url}/getFile",
            params={"file_id": file_id}
        )
        response.raise_for_status()
        return response.json()["result"]

    def get_file_url(self, file_path: str) -> str:
        """Формирует URL для загрузки файла"""
        return f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"

    def download_file(self, url: str) -> bytes:
        """Скачивает файл по URL"""
        response = requests.get(url)
        response.raise_for_status()
        return response.content


def get_bot_by_tag(bot_tag: str) -> Any:
    """Получает объект бота по тегу (пример реализации)"""
    # В реальном проекте здесь должна быть логика получения токена
    # bot_name = bot_tag[5:-1]
    # bot_token = settings.INTERNAL_BOTS.get(bot_name)
    # TODO в Django тоже нужны токены ботов
    BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent  # 4 уровня вверх до корня
    env_path = BASE_DIR / ".env"

    config = dotenv_values(env_path)
    bot_token = config.get("TEST_BOT_TG_KEY")
    return type('Bot', (), {'token': bot_token})()
