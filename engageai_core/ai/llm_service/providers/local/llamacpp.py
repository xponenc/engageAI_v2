"""
Реализация LLMProvider для моделей в формате GGUF через llama-cpp-python.

Особенности:
- Поддержка GPU-ускорения (CUDA, Metal, Vulkan и др.)
- Очень эффективное потребление памяти
- Возможность указать количество GPU-слоёв
- Простой синхронный вызов → оборачиваем в executor для async
- Нет встроенной поддержки structured output / json mode (только текст)

Требования:
pip install llama-cpp-python
(для GPU: pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124  # пример для CUDA 12.4)
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, AsyncIterable, Dict, List, Literal, Optional, Tuple

from ..base import BaseLocalProvider, estimate_tokens
from ...config import LLMConfig
from ...dtos import GenerationMetrics
from ...interfaces import LLMProvider

logger = logging.getLogger(__name__)


class LlamaCppProvider(BaseLocalProvider):
    """
    Провайдер для GGUF-моделей через llama.cpp.

    Рекомендуемые модели:
    - Llama-3.1-8B-Instruct-Q5_K_M.gguf
    - Mistral-Nemo-Instruct-2407-Q6_K.gguf
    - Phi-3.5-mini-instruct-Q6_K.gguf
    """

    def __init__(self, config: LLMConfig):
        super().__init__(config)

        self.model_path = config.local_model_path
        if not self.model_path or not Path(self.model_path).is_file():
            raise ValueError(f"LOCAL_MODEL_PATH должен указывать на существующий GGUF-файл: {self.model_path}")

        self.model_name = config.local_model_name or Path(self.model_path).stem
        self.n_ctx = config.llm_context_length or 8192
        self.n_threads = config.n_threads or 6
        self.n_gpu_layers = config.n_gpu_layers or -1  # -1 = все слои на GPU, если доступно

        self._model = None
        self._load_model()

    def _load_model(self):
        """Загрузка модели llama.cpp"""
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise ImportError(
                "Для LlamaCppProvider нужен пакет: pip install llama-cpp-python"
                "\nДля GPU-ускорения смотрите инструкции: https://github.com/abetlen/llama-cpp-python#installation-with-openblas--metal--cublas--clblast--vulkan"
            ) from exc

        logger.info(f"Загрузка llama.cpp модели: {self.model_path}")
        logger.info(f"Параметры: n_ctx={self.n_ctx}, n_gpu_layers={self.n_gpu_layers}, n_threads={self.n_threads}")

        self._model = Llama(
            model_path=str(self.model_path),
            n_ctx=self.n_ctx,
            n_threads=self.n_threads,
            n_gpu_layers=self.n_gpu_layers,
            verbose=False,                  # можно включить True для отладки
            # rope_scaling_type = ...,      # если нужно
            # logits_all = False,
        )

        logger.info(f"llama.cpp модель загружена: {self.model_name}, "
                    f"VRAM used: ~{self._model.metadata.get('general.file_size_bytes', 0) / 1e9:.1f} GB "
                    f"(примерно)")

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

        # llama.cpp работает с одной строкой → конвертируем сообщения
        prompt = self._convert_messages_to_prompt(messages)

        try:
            def _sync_generate():
                return self._model(
                    prompt=prompt,
                    max_tokens=max_tokens or self.config.llm_max_tokens,
                    temperature=temperature or self.config.llm_temperature,
                    top_p=0.95,                     # разумные дефолты
                    top_k=40,
                    repeat_penalty=1.1,
                    seed=seed if seed is not None else -1,
                    stop=["</s>", "<|eot_id|>", "<|end_of_text|>"],
                    echo=False,
                    # frequency_penalty=0.0,
                    # presence_penalty=0.0,
                )

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, _sync_generate)

            if not result or "choices" not in result or not result["choices"]:
                raise ValueError("Пустой ответ от llama.cpp")

            generated_text = result["choices"][0]["text"].strip()

            # Очень приблизительная оценка токенов
            input_tokens = estimate_tokens(prompt)
            output_tokens = estimate_tokens(generated_text)

            # Можно попробовать получить более точные значения, если модель их отдаёт
            try:
                input_tokens = result["usage"]["prompt_tokens"]
                output_tokens = result["usage"]["completion_tokens"]
            except (KeyError, TypeError):
                pass

            metrics = self._create_metrics(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                generation_time=time.time() - start_time,
                extra={
                    "n_gpu_layers_used": self.n_gpu_layers,
                    "seed": seed,
                }
            )

            return generated_text, metrics

        except Exception as e:
            logger.error(f"Ошибка генерации в llama.cpp: {str(e)}")
            raise

    def _convert_messages_to_prompt(self, messages: List[Dict[str, str]]) -> str:
        """
        Преобразование списка сообщений в строку.

        Для llama-3 / mistral / phi-3 используем их chat-шаблоны.
        Пока упрощённая версия — в будущем лучше использовать tokenizer.apply_chat_template
        """
        parts = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "").strip()

            if role == "system":
                parts.append(f"<|system|>\n{content}\n<|end|>")
            elif role == "user":
                parts.append(f"<|user|>\n{content}\n<|end|>")
            elif role == "assistant":
                parts.append(f"<|assistant|>\n{content}\n<|end|>")

        # Завершаем приглашением к ответу
        parts.append("<|assistant|>")

        return "\n".join(parts)

    async def generate_text_stream(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterable[Tuple[str, GenerationMetrics]]:
        """
        Простейшая реализация стриминга через callback.
        Можно улучшить с помощью llama-cpp-python streaming API.
        """
        raise NotImplementedError("Streaming в llama.cpp пока не реализован в этом провайдере")

    # Мультимедиа не поддерживается
    async def generate_image(self, *args, **kwargs):
        raise NotImplementedError("Генерация изображений не поддерживается в llama.cpp")

    async def generate_speech(self, *args, **kwargs):
        raise NotImplementedError("TTS не поддерживается в llama.cpp")


# Удобная фабричная функция (если нужно)
def create_llamacpp_provider(config: LLMConfig) -> LLMProvider:
    return LlamaCppProvider(config)