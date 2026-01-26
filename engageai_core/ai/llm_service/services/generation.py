"""
Главный сервис генерации ответов от LLM.

Отвечает за:
- Выбор подходящего провайдера (OpenAI / HF / llama.cpp) в зависимости от конфига
- Построение промпта / сообщений через PromptBuilder
- Вызов генерации с retry / fallback
- Расчёт стоимости через CostCalculator
- Парсинг и валидацию ответа (особенно JSON)
- Формирование единого GenerationResult
- Логирование (опционально)
- Обработку ошибок с graceful fallback

Не занимается: кэшированием, медиа-сохранением на диск, Django-моделями — это выше по стеку.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Literal, Optional, Tuple, Type

from pydantic import BaseModel, ValidationError

from ..cost.calculator import ZeroCostCalculator, OpenAICostCalculator
from ..dtos import GenerationMetrics, GenerationResult, LLMResponse, MediaGenerationResult
from ..interfaces import LLMProvider, CostCalculator, PromptBuilder
from ..logging.service import llm_logging_service
from ..prompt.builder import DefaultPromptBuilder
from ..providers.openai import OpenAIProvider
from ..providers.local.huggingface import HuggingFaceProvider
from ..providers.local.llamacpp import LlamaCppProvider
from ...config import LLMConfig


class GenerationService:
    """
    Оркестратор генерации ответов.

    Использование:
    service = GenerationService(config)
    result = await service.generate_json_response(...)
    """

    def __init__(
        self,
        config: LLMConfig,
        prompt_builder: Optional[PromptBuilder] = None,
        cost_calculator: Optional[CostCalculator] = None,
    ):
        self.config = config

        # Выбор провайдера один раз при создании сервиса
        self.provider: LLMProvider = self._create_provider()

        # Построитель промптов (дефолтный или кастомный)
        self.prompt_builder = prompt_builder or DefaultPromptBuilder(
            history_limit=5,
            add_json_instruction=True,
        )

        # Калькулятор стоимости
        if self.provider.is_local:
            self.cost_calculator = cost_calculator or ZeroCostCalculator()
        else:
            self.cost_calculator = cost_calculator or OpenAICostCalculator()

        self.fallback_enabled = config.use_fallback or False
        self.max_retries = config.max_retries or 3

    def _create_provider(self) -> LLMProvider:
        """Фабрика провайдеров — выбирает нужную реализацию"""
        if self.config.use_local_models:
            if self.config.local_model_type == "huggingface":
                return HuggingFaceProvider(self.config)
            elif self.config.local_model_type == "llama-cpp":
                return LlamaCppProvider(self.config)
            else:
                raise ValueError(f"Неизвестный тип локальной модели: {self.config.local_model_type}")
        else:
            return OpenAIProvider(self.config)

    async def generate_json_response(
        self,
        system_prompt: str,
        user_message: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        media_context: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_schema: Optional[Type[BaseModel]] = None,  # для structured output
        context_for_logging: Optional[Dict[str, Any]] = None,
    ) -> GenerationResult:
        """
        Основной метод для генерации структурированного JSON-ответа.

        Возвращает GenerationResult с:
        - response (LLMResponse)
        - metrics (токены, стоимость, время)
        - raw_provider_response (для отладки)
        """
        start_time = time.time()

        try:
            # 1. Формируем сообщения
            messages = self.prompt_builder.build_messages(
                system_prompt=system_prompt,
                user_message=user_message,
                conversation_history=conversation_history,
                media_context=media_context,
            )
            print(f"{messages=}")

            # 2. Генерация
            text, base_metrics = await self._generate_with_fallback(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format="json_object" if self.provider.supports_json_mode else "text",
            )
            print(f"{text=}")
            print(f"{base_metrics=}")

            # 3. Парсинг и валидация
            parsed = self._parse_json_response(text)

            print(f"{parsed=}")

            print(f"{self.cost_calculator=}")

            # 4. Расчёт стоимости (если не локально)
            cost = self.cost_calculator.calculate(
                model=self.provider.model_name,
                input_tokens=base_metrics.input_tokens,
                output_tokens=base_metrics.output_tokens,
            )
            # 5. Обогащаем метрики стоимостью
            metrics = base_metrics.with_cost(cost)
            print(f"{metrics=}")

            # 6. Формируем ответ
            response = LLMResponse(
                message=parsed if parsed else "Ошибка ответа",
                agent_state=parsed.get("agent_state", {}),
            )

            result = GenerationResult(
                response=response,
                metrics=metrics,
                raw_provider_response=text,
            )

            await llm_logging_service.log_request(
                system_prompt=system_prompt,
                user_message=user_message,
                generation_result=result,
                context=context_for_logging,
                status="SUCCESS",
            )

            return result

        except Exception as exc:
            # Graceful fallback / ошибка
            error_msg = f"Ошибка генерации: {str(exc)}"
            metrics = GenerationMetrics(
                generation_time_sec=time.time() - start_time,
                model_used=self.provider.model_name,
            )
            response = LLMResponse(
                message="Извините, произошла техническая ошибка. Попробуйте позже.",
                agent_state={"error": error_msg},
                metadata={"error": str(exc)},
            )

            result = GenerationResult(
                response=response,
                metrics=metrics,
                raw_provider_response=None,
                error=exc,
            )
            await llm_logging_service.log_request(
                system_prompt=system_prompt,
                user_message=user_message,
                generation_result=result,  # даже при ошибке
                context=context_for_logging,
                status="ERROR",
                error_message=str(exc),
            )
            return result

    async def _generate_with_fallback(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float],
        max_tokens: Optional[int],
        response_format: Literal["text", "json_object"],
    ) -> Tuple[str, GenerationMetrics]:
        """
        Пытается сгенерировать ответ, при ошибке — fallback на другую модель (если включено).
        """
        primary_model = self.provider.model_name

        try:
            return await self.provider.generate_text(
                messages=messages,
                temperature=temperature or self.config.llm_temperature,
                max_tokens=max_tokens or self.config.llm_max_tokens,
                response_format=response_format,
            )
        except Exception as primary_exc:
            if not self.fallback_enabled or not hasattr(self.config, "llm_fallback_model"):
                raise primary_exc

            # Пробуем fallback
            fallback_provider = OpenAIProvider(self.config)  # пока только OpenAI fallback
            fallback_provider.model_name = self.config.llm_fallback_model

            try:
                text, metrics = await fallback_provider.generate_text(
                    messages=messages,
                    temperature=temperature or self.config.llm_temperature,
                    max_tokens=max_tokens or self.config.llm_max_tokens,
                    response_format=response_format,
                )
                metrics.model_used = fallback_provider.model_name  # перезаписываем
                return text, metrics
            except Exception as fallback_exc:
                raise RuntimeError(
                    f"Primary ({primary_model}) и fallback ({self.config.llm_fallback_model}) оба провалились"
                ) from fallback_exc

    def _parse_json_response(self, raw_text: str) -> Dict[str, Any]:
        """Безопасный парсинг JSON с очисткой"""
        cleaned = raw_text.strip()
        # Убираем возможные ```json ... ```
        if cleaned.startswith("```json"):
            cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
        elif cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1].strip()

        try:
            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict):
                raise ValueError("JSON не является объектом")
            return parsed
        except json.JSONDecodeError as e:
            raise ValueError(f"Невалидный JSON от модели: {e}\nRaw: {raw_text[:200]}...") from e

    # Дополнительные методы (можно расширять)
    async def generate_text_response(self, *args, **kwargs):
        # Аналогично, но без парсинга JSON
        pass

    async def generate_media(
        self,
        media_type: Literal["image", "audio"],
        prompt: str,
        **kwargs,
    ) -> MediaGenerationResult:
        if not self.provider.supports_images and media_type == "image":
            raise NotImplementedError("Генерация изображений не поддерживается текущим провайдером")
        if not self.provider.supports_audio and media_type == "audio":
            raise NotImplementedError("TTS не поддерживается текущим провайдером")

        if media_type == "image":
            results = await self.provider.generate_image(prompt, **kwargs)
            return results[0] if results else MediaGenerationResult(success=False)
        elif media_type == "audio":
            return await self.provider.generate_speech(prompt, **kwargs)