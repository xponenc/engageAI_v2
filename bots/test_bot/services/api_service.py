import logging
import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from bots.test_bot.config import bot_logger, CORE_API_URL, BOT_INTERNAL_KEY


class CoreAPIClient:
    """Надёжный клиент для связи с Core API с ретраями при сетевых ошибках."""

    def __init__(self):
        self.base_url = CORE_API_URL
        self.headers = {
            "Authorization": f"Bearer {BOT_INTERNAL_KEY}",
            "Content-Type": "application/json"
        }
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers=self.headers)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((
                aiohttp.ClientConnectionError,
                aiohttp.ServerTimeoutError,
                aiohttp.ClientPayloadError,
                aiohttp.ClientResponseError  # Только при статусах 5xx
        )),
        before_sleep=lambda retry_state: bot_logger.warning(
            f"Retrying request to Core API ({retry_state.attempt_number}/3) after error: "
            f"{retry_state.outcome.exception()}"
        )
    )
    async def _make_request(self, endpoint: str, payload: dict) -> dict:
        """Внутренний метод с ретраями для запросов."""
        url = f"{self.base_url}{endpoint}"

        try:
            async with self.session.post(url, json=payload, timeout=15) as response:
                # Не ретраить на 4xx ошибки — это ошибка валидации данных
                if 400 <= response.status < 500:
                    error_text = await response.text()
                    bot_logger.error(f"Client error {response.status}: {error_text}")
                    return None

                # Ретраить на 5xx ошибки
                if response.status >= 500:
                    error_text = await response.text()
                    bot_logger.error(f"Server error {response.status}: {error_text}")
                    raise aiohttp.ClientResponseError(
                        response.request_info,
                        response.history,
                        status=response.status,
                        message=error_text
                    )

                return await response.json()

        except Exception as e:
            bot_logger.exception(f"Request to Core API failed: {str(e)}")
            raise  # tenacity перехватит и попробует снова


    async def receive_response(self, payload: dict) -> dict | None:
        """Отправка ответа студента в Core."""
        return await self._make_request("ai/orchestrator/process/", payload)