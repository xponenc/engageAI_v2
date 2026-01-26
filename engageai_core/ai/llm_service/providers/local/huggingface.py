"""
Реализация LLMProvider для моделей Hugging Face Transformers.

Особенности:
- Поддержка GPU/CPU/MPS
- Квантование (4-bit / 8-bit) для экономии памяти
- Асинхронная обёртка над синхронным pipeline
- Очень грубая оценка токенов (без настоящего токенизатора пока)
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

logger = logging.getLogger(__name__)


class HuggingFaceProvider(BaseLocalProvider):
    """
    Провайдер для моделей из Hugging Face (transformers).

    Требует:
    pip install transformers torch accelerate bitsandbytes (опционально для 4/8-bit)

    Поддерживает:
    - text-generation pipeline
    - device_map="auto" для multi-GPU / CPU fallback
    - 4-bit квантование (если установлен bitsandbytes)
    """

    def __init__(self, config: LLMConfig):
        super().__init__(config)

        self.model_path = config.local_model_path
        if not self.model_path:
            raise ValueError("LOCAL_MODEL_PATH required for HuggingFaceProvider")

        self._model = None
        self._tokenizer = None
        self._pipeline = None

        self.model_name = config.local_model_name or Path(self.model_path).name
        self.device = self._detect_device()

        self._load_model()

    def _load_model(self):
        """Ленивая загрузка модели + токенизатора"""
        try:
            import torch
            from transformers import (
                AutoModelForCausalLM,
                AutoTokenizer,
                pipeline,
                BitsAndBytesConfig,
            )
        except ImportError as exc:
            raise ImportError(
                "Для HuggingFaceProvider нужны: transformers torch (желательно accelerate bitsandbytes)"
            ) from exc

        logger.info(f"Загрузка HuggingFace модели: {self.model_path} на {self.device}")

        quantization_config = None
        if torch.cuda.is_available():
            try:
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_quant_type="nf4",
                )
                logger.info("Включаем 4-bit квантование")
            except Exception:
                logger.warning("Не удалось включить 4-bit квантование (bitsandbytes?) → обычная загрузка")

        model_kwargs = {
            "device_map": "auto",
            "torch_dtype": torch.float16 if self.device != "cpu" else torch.float32,
        }
        if quantization_config:
            model_kwargs["quantization_config"] = quantization_config

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token

        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            **model_kwargs,
            trust_remote_code=True,  # для некоторых моделей
        )

        self._pipeline = pipeline(
            "text-generation",
            model=self._model,
            tokenizer=self._tokenizer,
            device_map="auto",
            torch_dtype=model_kwargs.get("torch_dtype"),
        )

        logger.info(f"HuggingFace модель загружена: {self.model_name} на {self.device}")

    async def generate_text(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Literal["text", "json_object"] = "text",
        seed: Optional[int] = None,
    ) -> Tuple[str, GenerationMetrics]:
        """
        Для локальных моделей chat-формат преобразуем в одну строку.
        """
        start_time = time.time()

        # HuggingFace pipeline ожидает строку, а не список сообщений
        # Берём последний user-сообщение + системный промпт + историю в простой текст
        full_prompt = self._convert_messages_to_prompt(messages)

        try:
            # Синхронная генерация → оборачиваем в executor
            def _sync_generate():
                return self._pipeline(
                    full_prompt,
                    max_new_tokens=max_tokens or self.config.llm_max_tokens,
                    temperature=temperature or self.config.llm_temperature,
                    do_sample=True,
                    num_return_sequences=1,
                    pad_token_id=self._tokenizer.pad_token_id,
                    eos_token_id=self._tokenizer.eos_token_id,
                    return_full_text=False,
                )

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, _sync_generate)

            generated_text = result[0]["generated_text"].strip()

            input_tokens = estimate_tokens(full_prompt)
            output_tokens = estimate_tokens(generated_text)

            metrics = self._create_metrics(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                generation_time=time.time() - start_time,
                extra={"device": self.device},
            )

            # Для json_object можно добавить пост-обработку, но пока просто текст
            return generated_text, metrics

        except Exception as e:
            logger.error(f"Ошибка генерации в HuggingFace: {e}")
            raise

    def _convert_messages_to_prompt(self, messages: List[Dict[str, str]]) -> str:
        """
        Преобразование chat-формата в одну строку (примитивно, но работает для большинства моделей)
        """
        parts = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"].strip()
            if role == "system":
                parts.append(f"[System]\n{content}\n")
            elif role == "user":
                parts.append(f"[User]\n{content}\n")
            elif role == "assistant":
                parts.append(f"[Assistant]\n{content}\n")
        return "\n".join(parts) + "\n[Assistant]\n"

    async def generate_text_stream(self, *args, **kwargs) -> AsyncIterable[Tuple[str, GenerationMetrics]]:
        raise NotImplementedError("Streaming пока не реализован для HuggingFaceProvider")

    # Мультимедиа не поддерживается локально
    async def generate_image(self, *args, **kwargs):
        raise NotImplementedError("Image generation not supported locally")

    async def generate_speech(self, *args, **kwargs):
        raise NotImplementedError("TTS not supported locally")