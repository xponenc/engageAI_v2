# engageai_core/ai/llm/interfaces.py
"""
Абстрактные интерфейсы / протоколы для LLM-модуля.

Используем typing.Protocol (structural subtyping) вместо ABC, потому что:
- меньше бойлерплейта
- лучше работает с dataclasses / pydantic моделями
- позволяет duck-typing там, где это уместно

Все методы, которые помечаются как async, должны быть awaitable.
"""

from __future__ import annotations

from typing import (
    Any,
    AsyncIterable,
    Dict,
    List,
    Literal,
    Optional,
    Protocol,
    Tuple,
    Union,
    runtime_checkable,
)

from pydantic import BaseModel

from .dtos import GenerationMetrics, GenerationResult, LLMResponse, MediaGenerationResult


@runtime_checkable
class LLMProvider(Protocol):
    """
    Основной контракт для любого провайдера языковой модели.

    Реализации:
    - OpenAIProvider (ChatOpenAI + images/speech)
    - HuggingFaceProvider
    - LlamaCppProvider
    """

    model_name: str
    """Удобочитаемое имя модели для логов и метрик"""

    is_local: bool
    """True если модель работает полностью локально (без сетевых запросов)"""

    supports_json_mode: bool
    """Поддерживает ли модель принудительный JSON-вывод (response_format="json_object")"""

    supports_images: bool
    """Может ли генерировать изображения (DALL·E и аналоги)"""

    supports_audio: bool
    """Может ли генерировать речь из текста (TTS)"""


    async def generate_text(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Literal["text", "json_object"] = "text",
        seed: Optional[int] = None,
    ) -> Tuple[str, GenerationMetrics]:
        """
        Самый общий метод генерации текста.

        Args:
            messages: список сообщений в формате [{"role": "...", "content": "..."}]
            temperature: креативность (0.0–2.0)
            max_tokens: жёсткое ограничение на выходные токены
            response_format: "text" или "json_object" (если поддерживается)
            seed: для воспроизводимости (если модель поддерживает)

        Returns:
            (сгенерированный текст, метрики использования)
        """
        ...


    async def generate_text_stream(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterable[Tuple[str, GenerationMetrics]]:
        """
        Стриминговая генерация (токен за токеном).

        Yields:
            (новый кусок текста, частичные метрики — обычно final метрики только в конце)
        """
        ...


    async def generate_structured(
        self,
        messages: List[Dict[str, str]],
        output_schema: type[BaseModel],
        *,
        temperature: float = 0.4,
        max_tokens: Optional[int] = None,
    ) -> Tuple[BaseModel, GenerationMetrics]:
        """
        Генерация с принудительной структурой (Pydantic модель).

        Важно: не все провайдеры это умеют нативно → в некоторых будет парсинг + retry.
        """
        ...


    async def generate_image(
        self,
        prompt: str,
        *,
        size: str = "1024x1024",
        quality: str = "standard",
        n: int = 1,
    ) -> List[MediaGenerationResult]:
        """Генерация изображений (DALL·E и аналоги)"""
        ...


    async def generate_speech(
        self,
        text: str,
        *,
        voice: str = "alloy",
        speed: float = 1.0,
    ) -> MediaGenerationResult:
        """TTS — текст в речь"""
        ...


@runtime_checkable
class CostCalculator(Protocol):
    """Отвечает только за расчёт стоимости на основе токенов / символов"""

    def calculate(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int = 0,
        extra_chars: int = 0,           # для TTS
        image_count: int = 0,
    ) -> float:
        """
        Возвращает стоимость в USD (или 0.0 для локальных моделей)
        """
        ...


@runtime_checkable
class PromptBuilder(Protocol):
    """
    Отвечает за формирование списка сообщений / промпта из бизнес-данных.
    """

    def build_messages(
        self,
        system_prompt: str,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        media_context: Optional[List[Dict[str, Any]]] = None,
        last_n: int = 5,
    ) -> List[Dict[str, str]]:
        """
        Формирует список сообщений в формате OpenAI-совместимом:
        [{"role": "system"|"user"|"assistant", "content": "..."}]
        """
        ...


    def build_full_prompt_text(
        self,
        system_prompt: str,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        media_context: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Альтернативный вариант — единая строка (для локальных моделей без chat-формата)
        """
        ...


# Типы-алиасы для удобства (часто используются в сигнатурах)
LLMProviderLike = Union[LLMProvider, "LLMProvider"]
CostCalculatorLike = Union[CostCalculator, "CostCalculator"]
PromptBuilderLike = Union[PromptBuilder, "PromptBuilder"]


class FallbackConfig(BaseModel):
    """Настройки fallback-логики (если основной провайдер упал)"""
    enabled: bool = True
    max_attempts: int = 2
    models: List[str] = ["gpt-4o-mini", ]