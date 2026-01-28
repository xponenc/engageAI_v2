"""
Базовые классы, утилиты и общие реализации для всех LLM-провайдеров.

Здесь НЕ должно быть специфичной логики OpenAI / HuggingFace / llama.cpp —
только то, что повторяется в нескольких провайдерах.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC
from typing import Any, AsyncIterable, Dict, List, Literal, Optional, Tuple, Union, Callable, Awaitable, TypeVar

import httpx
from openai import RateLimitError, APIConnectionError, APIError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    AsyncRetrying,
)

from ...config import LLMConfig  # предполагаем, что config вынесен на уровень выше
from ..dtos import GenerationMetrics, GenerationResult, LLMResponse
from ..interfaces import LLMProvider, CostCalculator

T = TypeVar("T")


class BaseProvider(LLMProvider, ABC):
    """
    Базовый класс для всех провайдеров (и облачных, и локальных).

    Содержит:
    - общие retry-механизмы
    - базовые метрики
    - общие свойства (is_local, supports_...)
    """

    def __init__(self, config: LLMConfig):
        self.config = config
        self.model_name = config.llm_model_name
        self.temperature = config.llm_temperature
        self.max_tokens = config.llm_max_tokens

        # По умолчанию — самые консервативные значения
        self.is_local = False
        self.supports_json_mode = False
        self.supports_images = False
        self.supports_audio = False

    @property
    def identifier(self) -> str:
        """Уникальный строковый идентификатор провайдера для логов и конфигов"""
        return f"{self.__class__.__name__}({self.model_name})"

    async def _with_retry(self, func: Callable[[], Awaitable[T]],
                          max_attempts: int = 3, min_wait: float = 4.0):
        """
        Обёртка для повторных попыток — используется почти всеми провайдерами.
        """
        async for attempt in AsyncRetrying(
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential(multiplier=1, min=min_wait, max=30),
                retry=(
                        retry_if_exception_type((RateLimitError, APIConnectionError, APIError, httpx.TimeoutException))
                        | retry_if_exception_type(ConnectionError)
                ),
                reraise=True,
        ):
            with attempt:
                return await func()

    def _create_metrics(
            self,
            input_tokens: int = 0,
            output_tokens: int = 0,
            generation_time: float = 0.0,
            cached: bool = False,
            extra: Optional[Dict[str, Any]] = None,
    ) -> GenerationMetrics:
        """Удобный конструктор метрик"""
        return GenerationMetrics(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_total=0.0,  # будет перезаписано в CostCalculator
            cost_in=0.0,  # будет перезаписано в CostCalculator
            cost_out=0.0,  # будет перезаписано в CostCalculator
            generation_time_sec=generation_time,
            model_used=self.model_name,
            cached=cached,
            **(extra or {})
        )

    # Дефолтные заглушки — переопределяются в конкретных провайдерах
    async def generate_text_stream(
            self,
            messages: List[Dict[str, str]],
            *,
            temperature: Optional[float] = None,
            max_tokens: Optional[int] = None,
    ) -> AsyncIterable[Tuple[str, GenerationMetrics]]:
        # По умолчанию — не поддерживается, можно реализовать fallback через generate_text
        raise NotImplementedError("Streaming not supported by this provider")

    async def generate_structured(
            self,
            messages: List[Dict[str, str]],
            output_schema: type,
            *,
            temperature: Optional[float] = None,
            max_tokens: Optional[int] = None,
    ) -> Tuple[Any, GenerationMetrics]:
        # Базовая реализация: генерируем текст → парсим JSON → валидируем
        # В OpenAI можно сделать нативно, здесь — универсальный fallback
        text, metrics = await self.generate_text(
            messages,
            temperature=temperature or self.temperature,
            max_tokens=max_tokens or self.max_tokens,
            response_format="text",
        )

        start_parse = time.time()
        try:
            import json
            parsed = json.loads(text)
            instance = output_schema.model_validate(parsed)
            parse_time = time.time() - start_parse
            metrics.generation_time_sec += parse_time
            return instance, metrics
        except Exception as e:
            raise ValueError(f"Failed to parse structured output: {e}") from e


# ──────────────────────────────────────────────────────────────
# Утилиты, которые могут понадобиться нескольким провайдерам


def estimate_tokens(text: str) -> int:
    """
    Очень грубая оценка количества токенов (примерно 1 токен ≈ 4 символа).
    Для точности нужно использовать tokenizer конкретной модели.
    """
    return max(1, len(text) // 4 + 1)


class ZeroCostCalculator(CostCalculator):
    """Для локальных моделей — стоимость всегда 0"""

    def calculate(
            self,
            model: str,
            input_tokens: int,
            output_tokens: int = 0,
            extra_chars: int = 0,
            image_count: int = 0,
    ) -> dict:
        return {
            "cost_total": 0.0,
            "cost_in": 0.0,
            "cost_out": 0.0,
        }


class BaseLocalProvider(BaseProvider):
    """
    Базовый класс специально для локальных моделей (HF, llama.cpp и будущие).
    Добавляет общие вещи: device detection, memory optimization hints и т.д.
    """

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.is_local = True
        self.supports_json_mode = False  # большинство локальных моделей — нет
        self.supports_images = False
        self.supports_audio = False

    def _detect_device(self) -> str:
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
            return "cpu"
        except ImportError:
            return "cpu"
