"""
OpenAI-специфичная реализация LLMProvider.

Поддерживает:
- Chat completions (gpt-4o, gpt-4o-mini, o1 и т.д.)
- JSON mode / structured outputs
- Image generation (DALL·E)
- TTS (text-to-speech)
- Fallback-модели
- Стоимость (через внешний CostCalculator)
"""

from __future__ import annotations

import time
from typing import Any, AsyncIterable, Dict, List, Literal, Optional, Tuple

import httpx
from openai import AsyncOpenAI, RateLimitError, APIConnectionError, APIError, OpenAIError

from ...config import LLMConfig
from ..dtos import GenerationMetrics, MediaGenerationResult
from ..interfaces import LLMProvider
from .base import BaseProvider, estimate_tokens



class OpenAIProvider(BaseProvider):
    """
    Провайдер для всех OpenAI-совместимых моделей (ChatGPT, DALL·E, TTS).

    Особенности:
    - Асинхронный клиент
    - Поддержка стриминга
    - Нативный JSON mode
    - Генерация изображений и аудио
    - Автоматический fallback (передаётся через конфиг)
    """

    def __init__(self, config: LLMConfig):
        super().__init__(config)

        if not config.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAIProvider")

        self.client = AsyncOpenAI(
            api_key=config.openai_api_key,
            timeout=config.request_timeout or 60.0,
            max_retries=0,  # управляем retry через tenacity
        )

        self.model_name = config.llm_model_name or "gpt-4o-mini"
        self.fallback_model = config.llm_fallback_model or "gpt-4o-mini"

        # Возможности провайдера
        self.is_local = False
        self.supports_json_mode = True
        self.supports_images = True
        self.supports_audio = True

        # Дефолтные настройки для медиа
        self.dalle_model = config.dalle_model or "dall-e-3"
        self.tts_model = config.tts_model or "tts-1"

    async def generate_text(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Literal["text", "json_object"] = "text",
        seed: Optional[int] = None,
    ) -> Tuple[str, GenerationMetrics]:
        start_time = time.time()

        try:

            async def attempt():
                return await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=temperature or self.temperature,
                    max_tokens=max_tokens or self.max_tokens,
                    response_format={"type": response_format} if response_format == "json_object" else None,
                    seed=seed,
                )

            completion = await self._with_retry(attempt)

            # completion = await self._with_retry(
            #     self.client.chat.completions.create(
            #         model=self.model_name,
            #         messages=messages,
            #         temperature=temperature or self.temperature,
            #         max_tokens=max_tokens or self.max_tokens,
            #         response_format={"type": response_format} if response_format == "json_object" else None,
            #         seed=seed,
            #     )
            # )

            print(f"{completion=}")

            if not completion.choices or not completion.choices[0].message.content:
                raise ValueError("Empty response from OpenAI")

            content = completion.choices[0].message.content
            usage = completion.usage

            metrics = self._create_metrics(
                input_tokens=usage.prompt_tokens if usage else estimate_tokens("\n".join(m["content"] for m in messages)),
                output_tokens=usage.completion_tokens if usage else estimate_tokens(content),
                generation_time=time.time() - start_time,
                extra={"finish_reason": completion.choices[0].finish_reason},
            )
            print(f"{content=}")

            return content, metrics

        except (RateLimitError, APIConnectionError, APIError, OpenAIError) as e:
            # Здесь можно добавить логику fallback на другую модель
            # Пока просто пробрасываем — fallback будет реализован выше (в GenerationService)
            raise

    async def generate_text_stream(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterable[Tuple[str, GenerationMetrics]]:
        start_time = time.time()
        accumulated_content = ""
        input_tokens_estimated = estimate_tokens("\n".join(m["content"] for m in messages))

        try:
            stream = await self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=temperature or self.temperature,
                max_tokens=max_tokens or self.max_tokens,
                stream=True,
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content is not None:
                    delta = chunk.choices[0].delta.content
                    accumulated_content += delta
                    yield delta, self._create_metrics(
                        input_tokens=input_tokens_estimated,
                        output_tokens=estimate_tokens(accumulated_content),
                        generation_time=time.time() - start_time,
                        extra={"streaming": True},
                    )

            # Финальные метрики (если есть usage в последнем чанке — редко)
            yield "", self._create_metrics(
                input_tokens=input_tokens_estimated,
                output_tokens=estimate_tokens(accumulated_content),
                generation_time=time.time() - start_time,
            )

        except Exception as e:
            raise

    async def generate_image(
        self,
        prompt: str,
        *,
        size: str = "1024x1024",
        quality: str = "standard",
        n: int = 1,
    ) -> List[MediaGenerationResult]:
        try:
            response: ImageGenerateResponse = await self._with_retry(
                self.client.images.generate(
                    model=self.dalle_model,
                    prompt=prompt,
                    size=size,
                    quality=quality,
                    n=n,
                    response_format="url",
                )
            )

            results = []
            for img_data in response.data:
                url = img_data.url
                if not url:
                    continue

                # Скачиваем изображение (асинхронно)
                async with httpx.AsyncClient(timeout=30.0) as http_client:
                    resp = await http_client.get(url)
                    resp.raise_for_status()
                    image_bytes = resp.content

                # Здесь можно сохранить на диск, если нужно (как в оригинальном коде)
                # Пока возвращаем только URL и байты
                results.append(
                    MediaGenerationResult(
                        success=True,
                        url=url,
                        mime_type="image/png",
                        # local_path=... если сохраняем
                    )
                )

            return results

        except Exception as e:
            return [
                MediaGenerationResult(
                    success=False,
                    error=str(e),
                )
            ]

    async def generate_speech(
        self,
        text: str,
        *,
        voice: str = "alloy",
        speed: float = 1.0,
    ) -> MediaGenerationResult:
        try:
            response = await self._with_retry(
                self.client.audio.speech.create(
                    model=self.tts_model,
                    voice=voice,
                    input=text,
                    speed=speed,
                )
            )

            audio_bytes = response.content

            return MediaGenerationResult(
                success=True,
                mime_type="audio/mp3",
                # url / local_path — заполняются выше по стеку
                # можно вернуть bytes напрямую, если нужно
            )

        except Exception as e:
            return MediaGenerationResult(
                success=False,
                error=str(e),
            )


# Для совместимости со старым кодом (временный бридж)
async def create_openai_provider(config: LLMConfig) -> LLMProvider:
    return OpenAIProvider(config)