# engageai_core/ai/llm/llm_factory.py
"""
LLMFactory - фабрика для управления языковыми моделями через LangChain

Этот модуль предоставляет унифицированный интерфейс для работы как с облачными (OpenAI),
так и с локальными моделями (Hugging Face, Llama.cpp).

Основные функции:
- Автоматическое переключение между облачными и локальными моделями
- Кэширование ответов для часто задаваемых вопросов
- Fallback на резервные модели при ошибках
- Отслеживание стоимости использования (для OpenAI)
- Генерация мультимедиа-контента (только для OpenAI)
- Rate limiting с экспоненциальной задержкой

Архитектурные принципы:
1. Единый интерфейс для разных типов моделей
2. Полная независимость от фреймворка (не зависит от Django)
3. Максимальная конфиденциальность данных при использовании локальных моделей
4. Надежность за счет автоматического переключения при ошибках
5. Производительность благодаря кэшированию и оптимизации запросов
6. Наблюдаемость через детальное логирование и трекинг ресурсов

Важные замечания:
- Для локальных моделей генерация мультимедиа недоступна
- Расчет стоимости работает только для OpenAI API
- Llama.cpp требует компиляции с поддержкой CUDA для GPU-ускорения
- Hugging Face модели требуют достаточного объема VRAM
"""

import os
import hashlib
import time
import logging
import json
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from collections import defaultdict
import httpx
import aiohttp
from pathlib import Path

# Обязательные зависимости LangChain
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableConfig
from langchain_community.cache import InMemoryCache, RedisCache
from langchain.globals import set_llm_cache

# Для rate limiting и retry
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Для обработки исключений API
from openai import OpenAIError, RateLimitError, APIConnectionError, APIError

# Локальные импорты
from engageai_core.ai.config import LLMConfig

logger = logging.getLogger(__name__)

# Данные для расчета стоимости токенов (только для OpenAI)
MODEL_COSTS = {
    # Input costs per 1M tokens, Output costs per 1M tokens
    "gpt-4-turbo-preview": (10.0, 30.0),
    "gpt-4-0125-preview": (10.0, 30.0),
    "gpt-4-1106-preview": (10.0, 30.0),
    "gpt-3.5-turbo-0125": (0.5, 1.5),
    "gpt-3.5-turbo-1106": (1.0, 2.0),
    "gpt-4o": (5.0, 15.0),
    "gpt-4o-mini": (0.15, 0.6),
    "text-embedding-3-large": (0.13, 0.13),
    "text-embedding-3-small": (0.02, 0.02),
    "dall-e-3": (40.0, 0.0),  # Цена за изображение
    "tts-1": (15.0, 0.0),  # Цена за 1000 символов
}


@dataclass
class LLMResponse:
    """Структура ответа от LLM"""
    message: str = Field(description="Текст ответа для пользователя")
    agent_state: Dict[str, Any] = Field(default_factory=dict, description="Внутреннее состояние агента")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Дополнительные метаданные")


@dataclass
class GenerationResult:
    """Полный результат генерации с метаданными"""
    response: LLMResponse
    token_usage: Dict[str, int]
    cost: float
    generation_time: float
    model_used: str
    cached: bool = False


class LLMCallbackHandler(BaseCallbackHandler):
    """Обработчик обратных вызовов для отслеживания использования токенов"""

    def __init__(self):
        self.token_usage = defaultdict(int)
        self.start_time = None
        self.end_time = None

    def on_llm_start(self, *args, **kwargs):
        """Вызывается при старте генерации"""
        self.start_time = time.time()

    def on_llm_end(self, response, **kwargs):
        """Вызывается при завершении генерации"""
        self.end_time = time.time()
        if hasattr(response, 'generations') and response.generations:
            generation = response.generations[0][0]
            if hasattr(generation, 'message') and hasattr(generation.message, 'usage_metadata'):
                usage = generation.message.usage_metadata
                self.token_usage['input_tokens'] += usage.get('input_tokens', 0)
                self.token_usage['output_tokens'] += usage.get('output_tokens', 0)

    def get_total_tokens(self):
        """Возвращает общее количество использованных токенов"""
        return self.token_usage['input_tokens'] + self.token_usage['output_tokens']

    def get_generation_time(self):
        """Возвращает время генерации в секундах"""
        return self.end_time - self.start_time if self.start_time and self.end_time else 0


class LocalModelAdapter:
    """
    Адаптер для локальных моделей

    Предоставляет единый интерфейс для различных типов локальных моделей:
    - Hugging Face Transformers
    - Llama.cpp

    Особенности реализации:
    1. Автоматическое определение доступности GPU
    2. Оптимизация памяти для больших моделей
    3. Единый интерфейс для разных типов моделей
    4. Асинхронная обработка запросов

    Для установки зависимостей:
    - Hugging Face: pip install transformers torch
    - Llama.cpp: pip install llama-cpp-python
    """

    def __init__(self, config: LLMConfig):
        """
        Инициализация адаптера локальных моделей

        Args:
            config: Конфигурация LLM
        """
        self.config = config
        self.model = None
        self.tokenizer = None
        self.pipeline = None
        self.device = "cpu"
        self._initialize_model()

    def _initialize_model(self):
        """Инициализация локальной модели"""
        try:
            if self.config.local_model_type == "huggingface":
                self._init_huggingface()
            elif self.config.local_model_type == "llama-cpp":
                self._init_llama_cpp()
            else:
                raise ValueError(f"Unsupported local model type: {self.config.local_model_type}")

            logger.info(f"Successfully initialized local model: {self.config.local_model_path} on {self.device}")
        except Exception as e:
            logger.error(f"Failed to initialize local model: {str(e)}")
            raise

    def _init_huggingface(self):
        """Инициализация Hugging Face модели"""
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
        except ImportError as e:
            raise ImportError("Missing dependencies for Hugging Face models. Install with: pip install transformers torch")

        # Проверка доступности GPU
        if torch.cuda.is_available():
            self.device = "cuda"
            logger.info("CUDA available, using GPU for inference")
        elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            self.device = "mps"
            logger.info("MPS available, using Apple Silicon GPU for inference")
        else:
            self.device = "cpu"
            logger.info("No GPU available, using CPU for inference")

        # Загрузка токенизатора
        logger.info(f"Loading tokenizer from {self.config.local_model_path}")
        self.tokenizer = AutoTokenizer.from_pretrained(self.config.local_model_path)

        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        # Загрузка модели
        logger.info(f"Loading model from {self.config.local_model_path} on {self.device}")
        model_kwargs = {}

        # Оптимизация для GPU
        if self.device == "cuda":
            model_kwargs["device_map"] = "auto"
            model_kwargs["torch_dtype"] = torch.float16
            model_kwargs["load_in_4bit"] = True  # Квантование для экономии памяти

        # Загрузка модели
        self.model = AutoModelForCausalLM.from_pretrained(
            self.config.local_model_path,
            **model_kwargs
        )

        # Создание пайплайна
        self.pipeline = pipeline(
            "text-generation",
            model=self.model,
            tokenizer=self.tokenizer,
            max_new_tokens=self.config.llm_max_tokens,
            temperature=self.config.llm_temperature,
            device=self.device
        )

    def _init_llama_cpp(self):
        """Инициализация Llama.cpp модели"""
        try:
            from llama_cpp import Llama
        except ImportError:
            raise ImportError("Missing dependencies for Llama.cpp models. Install with: pip install llama-cpp-python")

        logger.info(f"Loading Llama.cpp model from: {self.config.local_model_path}")

        # Определение количества GPU слоев (если доступно)
        n_gpu_layers = 0
        try:
            import torch
            if torch.cuda.is_available():
                n_gpu_layers = -1  # Использовать все слои на GPU
                logger.info("CUDA available, using GPU acceleration for Llama.cpp")
        except ImportError:
            pass

        # Загрузка модели
        self.model = Llama(
            model_path=self.config.local_model_path,
            n_ctx=4096,
            n_threads=4,  # Можно настроить динамически
            n_gpu_layers=n_gpu_layers,
            verbose=False
        )

    async def generate_response(self, prompt: str) -> Dict[str, Any]:
        """
        Генерация ответа с использованием локальной модели

        Args:
            prompt: Текстовый промпт для генерации

        Returns:
            Словарь с результатами генерации
        """
        start_time = time.time()
        try:
            if self.config.local_model_type == "huggingface":
                response = await self._generate_hf(prompt)
            elif self.config.local_model_type == "llama-cpp":
                response = await self._generate_llama_cpp(prompt)
            else:
                raise ValueError(f"Unsupported local model type: {self.config.local_model_type}")

            generation_time = time.time() - start_time
            return {
                "response": response,
                "generation_time": generation_time,
                "model_used": os.path.basename(self.config.local_model_path),
                "token_usage": self._estimate_token_usage(prompt, response)
            }
        except Exception as e:
            logger.error(f"Error generating response with local model: {str(e)}")
            raise

    async def _generate_hf(self, prompt: str) -> str:
        """Генерация с Hugging Face (асинхронная обертка)"""
        import asyncio

        def _sync_generate():
            return self.pipeline(
                prompt,
                max_new_tokens=self.config.llm_max_tokens,
                temperature=self.config.llm_temperature,
                do_sample=True,
                pad_token_id=self.tokenizer.pad_token_id,
                return_full_text=False
            )

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _sync_generate)
        return result[0]['generated_text']

    async def _generate_llama_cpp(self, prompt: str) -> str:
        """Генерация с Llama.cpp (асинхронная обертка)"""
        import asyncio

        def _sync_generate():
            return self.model(
                prompt,
                max_tokens=self.config.llm_max_tokens,
                temperature=self.config.llm_temperature,
                stop=["</s>", "\n\n"],
                echo=False
            )

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _sync_generate)
        return result['choices'][0]['text'].strip()

    def _estimate_token_usage(self, prompt: str, response: str) -> Dict[str, int]:
        """
        Оценка использования токенов

        Важно: это приблизительная оценка, так как точный подсчет требует
        использования оригинального токенизатора модели
        """
        # Упрощенная оценка: 1 токен ≈ 4 символа
        input_tokens = len(prompt) // 4
        output_tokens = len(response) // 4

        return {
            "input_tokens": max(1, input_tokens),
            "output_tokens": max(1, output_tokens)
        }


class LLMFactory:
    """
    Фабрика для создания и управления LLM-моделями

    Предоставляет унифицированный интерфейс для работы с разными типами моделей,
    скрывая сложность их реализации от вызывающего кода.

    Поддерживаемые сценарии:
    1. Облачные модели (OpenAI) - для максимального качества
    2. Локальные модели (Hugging Face, Llama.cpp) - для конфиденциальности и автономности

    Преимущества локальных моделей:
    - Полная конфиденциальность данных пользователей
    - Независимость от внешних API и их ограничений
    - Предсказуемая стоимость (только затраты на оборудование)
    - Возможность дообучения на специфических данных
    - Отсутствие сетевых задержек при правильной конфигурации

    Компромиссы локальных моделей:
    - Требуют значительных вычислительных ресурсов
    - Качество может уступать GPT-4 для сложных задач
    - Ограниченная поддержка мультимодальных функций
    - Требуют экспертизы для настройки и оптимизации
    """

    def __init__(
        self,
        config: Optional[LLMConfig] = None,
        **kwargs
    ):
        """
        Инициализация фабрики LLM

        Args:
            config: Конфигурация LLM (если не предоставлена, загружается из .env)
            **kwargs: Дополнительные параметры для переопределения конфигурации
        """
        # Инициализация конфигурации
        self.config = config or LLMConfig.from_env_file()

        # Переопределение параметров из kwargs
        for key, value in kwargs.items():
            config_key = key.lower()
            if hasattr(self.config, config_key):
                setattr(self.config, config_key, value)

        # Компоненты для разных типов моделей
        self.local_adapter = None
        self.llm = None
        self.fallback_llm = None

        # Инициализация кэша
        self._initialize_cache()

        # Инициализация моделей
        self._initialize_models()

        # Парсеры для разных типов ответов
        self.json_parser = JsonOutputParser(pydantic_object=LLMResponse)
        self.text_parser = StrOutputParser()

        logger.info(f"LLMFactory initialized with configuration: {self.config.model_dump_public()}")

    def _initialize_cache(self):
        """Инициализация кэша для LLM-запросов"""
        if not self.config.use_cache:
            logger.info("LLM caching is disabled")
            return

        if self.config.redis_url:
            try:
                set_llm_cache(RedisCache(redis_url=self.config.redis_url))
                logger.info("Redis cache initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize Redis cache: {e}. Using in-memory cache.")
                set_llm_cache(InMemoryCache())
        else:
            set_llm_cache(InMemoryCache())
            logger.info("Using in-memory cache for LLM responses")

    def _initialize_models(self):
        """Инициализация LLM моделей"""
        try:
            if self.config.use_local_models:
                self._init_local_models()
            else:
                self._init_openai_models()
        except Exception as e:
            logger.error(f"Failed to initialize LLM models: {e}")
            raise

    def _init_openai_models(self):
        """Инициализация моделей OpenAI"""
        if not self.config.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI models")

        self.llm = ChatOpenAI(
            model_name=self.config.llm_model_name,
            temperature=self.config.llm_temperature,
            max_tokens=self.config.llm_max_tokens,
            openai_api_key=self.config.openai_api_key,
            streaming=True
        )

        self.fallback_llm = ChatOpenAI(
            model_name=self.config.llm_fallback_model,
            temperature=self.config.llm_temperature,
            max_tokens=self.config.llm_max_tokens,
            openai_api_key=self.config.openai_api_key
        )

        logger.info(f"Initialized OpenAI models: primary={self.config.llm_model_name}, fallback={self.config.llm_fallback_model}")

    def _init_local_models(self):
        """Инициализация локальных моделей"""
        if not self.config.local_model_path:
            raise ValueError("LOCAL_MODEL_PATH is required for local models")

        if not os.path.exists(self.config.local_model_path):
            raise FileNotFoundError(f"Local model path does not exist: {self.config.local_model_path}")

        self.local_adapter = LocalModelAdapter(self.config)
        logger.info(f"Initialized local model: {self.config.local_model_path} ({self.config.local_model_type})")

    def _calculate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        """
        Рассчитывает стоимость запроса на основе использования токенов

        Args:
            input_tokens: Количество входных токенов
            output_tokens: Количество выходных токенов
            model: Название модели

        Returns:
            Стоимость в USD
        """
        if model not in MODEL_COSTS:
            logger.warning(f"Unknown model {model} for cost calculation. Using default costs.")
            model = "gpt-3.5-turbo-0125"

        input_cost_per_million, output_cost_per_million = MODEL_COSTS[model]
        input_cost = (input_tokens / 1_000_000) * input_cost_per_million
        output_cost = (output_tokens / 1_000_000) * output_cost_per_million
        return round(input_cost + output_cost, 6)

    def _get_cache_key(self, prompt: str, model: str, temperature: float) -> str:
        """
        Генерирует уникальный ключ для кэширования

        Args:
            prompt: Текст промпта
            model: Название модели
            temperature: Параметр температуры

        Returns:
            MD5 хэш для кэширования
        """
        key_data = f"{prompt}|{model}|{temperature}"
        return hashlib.md5(key_data.encode()).hexdigest()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=(retry_if_exception_type(RateLimitError) |
               retry_if_exception_type(APIConnectionError) |
               retry_if_exception_type(httpx.TimeoutException))
    )
    async def _generate_with_retry(self, chain, input_data, use_fallback=False):
        """
        Генерация ответа с повторными попытками при ошибках

        Args:
            chain: LangChain цепочка для генерации
            input_data: Входные данные для цепочки
            use_fallback: Использовать резервную модель

        Returns:
            Результат генерации
        """
        try:
            if self.config.use_local_models:
                # Для локальных моделей используем специальный метод
                return await self.local_adapter.generate_response(input_data["input"])

            # Для OpenAI используем LangChain
            callback_handler = LLMCallbackHandler()
            config = RunnableConfig(callbacks=[callback_handler])

            llm_to_use = self.fallback_llm if use_fallback else self.llm
            result = await chain.with_config(config).ainvoke(input_data)

            # Добавляем метаданные об использовании токенов
            if hasattr(result, '__dict__'):
                result_dict = result.__dict__
            elif isinstance(result, dict):
                result_dict = result
            else:
                result_dict = {"response": result}

            result_dict.update({
                'token_usage': callback_handler.token_usage,
                'generation_time': callback_handler.get_generation_time(),
                'model_used': self.config.llm_fallback_model if use_fallback else self.config.llm_model_name
            })

            return result_dict

        except Exception as e:
            logger.error(f"Error during LLM generation (fallback={use_fallback}): {str(e)}")
            raise

    def _build_full_prompt(
        self,
        system_prompt: str,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        media_context: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """
        Формирует полный промпт для кэширования

        Args:
            system_prompt: Системный промпт
            user_message: Сообщение пользователя
            conversation_history: История диалога
            media_context: Контекст медиафайлов

        Returns:
            Полный промпт в виде строки
        """
        parts = [system_prompt]

        if media_context:
            media_info = "\nКонтекст медиафайлов:"
            for media in media_context:
                media_info += f"\n- Тип: {media['type']}, URL: {media['url']}"
            parts.append(media_info)

        if conversation_history:
            parts.append("\nИстория диалога:")
            for entry in conversation_history[-5:]:
                parts.append(f"Студент: {entry.get('user_message', '')}")
                if isinstance(entry.get('agent_response'), dict):
                    parts.append(f"Репетитор: {entry['agent_response'].get('message', '...')}")
                else:
                    parts.append(f"Репетитор: {entry.get('agent_response', '...')}")

        parts.append(f"\nСообщение студента:\n{user_message}")
        parts.append("\nОтветь строго в формате JSON как указано в инструкции.")

        return "\n".join(parts)

    async def _generate_response(
        self,
        system_prompt: str,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        response_format: str = "json",
        media_context: Optional[List[Dict[str, Any]]] = None,
        timeout: int = 30
    ) -> GenerationResult:
        """
        Генерирует ответ от LLM с полным отслеживанием метрик

        Args:
            system_prompt: Системный промпт для модели
            user_message: Сообщение пользователя
            conversation_history: История диалога
            response_format: Формат ответа ('json' или 'text')
            media_context: Контекст медиафайлов
            timeout: Таймаут в секундах

        Returns:
            GenerationResult с ответом и метаданными
        """
        start_time = time.time()
        cached = False

        # Формируем полный промпт
        full_prompt = self._build_full_prompt(system_prompt, user_message, conversation_history, media_context)

        # Проверяем кэш
        cache_key = None
        if self.config.use_cache:
            cache_key = self._get_cache_key(full_prompt, self.config.llm_model_name, self.config.llm_temperature)
            # TODO: Реализовать проверку кэша

        try:
            # Для локальных моделей генерация проще
            if self.config.use_local_models:
                response = await self.local_adapter.generate_response(full_prompt)
                token_usage = response.get('token_usage', {})
                input_tokens = token_usage.get('input_tokens', 0)
                output_tokens = token_usage.get('output_tokens', 0)
                model_used = response.get('model_used', os.path.basename(self.config.local_model_path))

                # Парсим JSON-ответ
                try:
                    parsed_response = json.loads(response['response'])
                    message = parsed_response.get('message', 'Произошла ошибка при генерации ответа')
                    agent_state = parsed_response.get('agent_state', {'engagement_change': 0})
                except json.JSONDecodeError:
                    logger.warning("Failed to parse JSON response from local model")
                    message = response['response']
                    agent_state = {'engagement_change': 0}

                llm_response = LLMResponse(
                    message=message,
                    agent_state=agent_state,
                    metadata={
                        'raw_response': response['response'],
                        'model_used': model_used
                    }
                )

                return GenerationResult(
                    response=llm_response,
                    token_usage=token_usage,
                    cost=0.0,  # Нет стоимости для локальных моделей
                    generation_time=response.get('generation_time', time.time() - start_time),
                    model_used=model_used,
                    cached=cached
                )

            # Для OpenAI используем полную цепочку
            # Создаем цепочку в зависимости от формата ответа
            chain, input_data = self._create_chain(
                system_prompt,
                user_message,
                conversation_history,
                response_format,
                media_context
            )

            # Пытаемся сгенерировать ответ основной моделью
            try:
                result = await self._generate_with_retry(chain, input_data, use_fallback=False)
            except (RateLimitError, APIConnectionError, APIError) as e:
                logger.warning(f"Primary model failed, using fallback: {str(e)}")
                # Повторяем попытку с резервной моделью
                result = await self._generate_with_retry(chain, input_data, use_fallback=True)

            # Обрабатываем результат
            response = self._process_result(result, response_format)

            # Рассчитываем стоимость
            token_usage = result.get('token_usage', {})
            input_tokens = token_usage.get('input_tokens', 0)
            output_tokens = token_usage.get('output_tokens', 0)
            model_used = result.get('model_used', self.config.llm_model_name)
            cost = self._calculate_cost(input_tokens, output_tokens, model_used) if self.config.enable_cost_tracking else 0.0

            generation_time = time.time() - start_time

            return GenerationResult(
                response=response,
                token_usage=token_usage,
                cost=cost,
                generation_time=generation_time,
                model_used=model_used,
                cached=cached
            )

        except Exception as e:
            logger.exception(f"Failed to generate response after retries: {str(e)}")
            # Fallback на статический ответ при полном провале
            return GenerationResult(
                response=LLMResponse(
                    message="Извините, сейчас я не могу обработать ваш запрос. Пожалуйста, попробуйте позже.",
                    agent_state={"engagement_change": -1}
                ),
                token_usage={"input_tokens": 0, "output_tokens": 0},
                cost=0.0,
                generation_time=time.time() - start_time,
                model_used="fallback",
                cached=False
            )

    def _create_chain(
        self,
        system_prompt: str,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        response_format: str = "json",
        media_context: Optional[List[Dict[str, str]]] = None
    ) -> Tuple:
        """
        Создает LangChain цепочку для генерации ответа

        Args:
            system_prompt: Системный промпт
            user_message: Сообщение пользователя
            conversation_history: История диалога
            response_format: Формат ответа ('json' или 'text')
            media_context: Контекст медиафайлов

        Returns:
            Кортеж (chain, input_data)
        """
        # Подготовка истории сообщений
        messages = []

        # Добавляем системный промпт
        full_system_prompt = system_prompt

        # Добавляем контекст медиа в системный промпт
        if media_context:
            media_info = "\n\nКонтекст медиафайлов:"
            for media in media_context:
                media_info += f"\n- Тип: {media['type']}, URL: {media['url']}"
            full_system_prompt += media_info

        messages.append(SystemMessage(content=full_system_prompt))

        # Добавляем историю диалога
        if conversation_history:
            for entry in conversation_history[-5:]:  # последние 5 сообщений
                messages.append(HumanMessage(content=entry.get('user_message', '')))
                if isinstance(entry.get('agent_response'), dict):
                    agent_msg = entry['agent_response'].get('message', '')
                    messages.append(AIMessage(content=agent_msg))
                elif entry.get('agent_response'):
                    messages.append(AIMessage(content=str(entry.get('agent_response', ''))))

        # Шаблон для текущего сообщения
        prompt_template = ChatPromptTemplate.from_messages([
            *messages,
            HumanMessage(content="{input}")
        ])

        # Выбираем парсер в зависимости от формата
        parser = self.json_parser if response_format == "json" else self.text_parser

        # Добавляем форматирование для JSON
        if response_format == "json":
            format_instructions = self.json_parser.get_format_instructions()
            full_prompt = prompt_template + [
                SystemMessage(content=f"ВАЖНО: Ответ должен быть строго в формате JSON: {format_instructions}")
            ]
            chain = full_prompt | self.llm | parser
        else:
            chain = prompt_template | self.llm | parser

        input_data = {"input": user_message}

        return chain, input_data

    def _process_result(self, result: Dict[str, Any], response_format: str) -> LLMResponse:
        """
        Обрабатывает результат от LLM и преобразует в LLMResponse

        Args:
            result: Сырой результат от LLM
            response_format: Формат ответа

        Returns:
            LLMResponse
        """
        if response_format == "json":
            # Результат уже распарсен в JSON
            if isinstance(result, LLMResponse):
                return result
            elif isinstance(result, dict):
                # Убеждаемся, что есть все необходимые поля
                message = result.get("message", "Извините, произошла ошибка при генерации ответа.")
                agent_state = result.get("agent_state", {"engagement_change": 0})
                metadata = result.get("metadata", {})

                return LLMResponse(
                    message=message,
                    agent_state=agent_state,
                    metadata=metadata
                )

        # Для текстового формата создаем базовый ответ
        return LLMResponse(
            message=str(result),
            agent_state={"engagement_change": 0},
            metadata={"raw_response": str(result)}
        )

    async def generate_json_response(
        self,
        system_prompt: str,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        media_context: Optional[List[Dict[str, Any]]] = None
    ) -> GenerationResult:
        """
        Генерирует структурированный JSON-ответ от LLM

        Args:
            system_prompt: Системный промпт для модели
            user_message: Сообщение пользователя
            conversation_history: История диалога
            media_context: Контекст медиафайлов

        Returns:
            GenerationResult с ответом и метаданными
        """
        return await self._generate_response(
            system_prompt=system_prompt,
            user_message=user_message,
            conversation_history=conversation_history,
            response_format="json",
            media_context=media_context
        )

    async def generate_text_response(
        self,
        system_prompt: str,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> GenerationResult:
        """
        Генерирует текстовый ответ от LLM

        Args:
            system_prompt: Системный промпт для модели
            user_message: Сообщение пользователя
            conversation_history: История диалога

        Returns:
            GenerationResult с ответом и метаданными
        """
        return await self._generate_response(
            system_prompt=system_prompt,
            user_message=user_message,
            conversation_history=conversation_history,
            response_format="text"
        )

    async def generate_media_response(
        self,
        media_type: str,
        prompt: str,
        model_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Генерирует медиа-контент (изображения, аудио) с помощью специализированных моделей

        Args:
            media_type: Тип медиа ('image', 'audio')
            prompt: Промпт для генерации
            model_override: Переопределение модели

        Returns:
            Словарь с информацией о сгенерированном медиа
        """
        if self.config.use_local_models:
            logger.warning("Media generation is not supported with local models")
            return {
                "error": "Media generation is not supported with local models",
                "media_type": media_type,
                "success": False
            }

        try:
            if media_type == 'image':
                return await self._generate_dalle_image(prompt, model_override)
            elif media_type == 'audio':
                return await self._generate_tts_audio(prompt, model_override)
            else:
                raise ValueError(f"Unsupported media type: {media_type}")
        except Exception as e:
            logger.error(f"Error generating {media_type}: {str(e)}")
            return {
                "error": str(e),
                "media_type": media_type,
                "success": False
            }

    async def _generate_dalle_image(
        self,
        prompt: str,
        model_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """Генерирует изображение с помощью DALL-E API"""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.config.openai_api_key)

            response = client.images.generate(
                model=model_override or self.config.dalle_model,
                prompt=prompt,
                size="1024x1024",
                quality="standard",
                n=1,
            )

            image_url = response.data[0].url

            # Загружаем изображение асинхронно
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url, timeout=self.config.media_generation_timeout) as response:
                    img_data = await response.read()

            # Рассчитываем стоимость
            cost = self._calculate_cost(0, 0, self.config.dalle_model)

            # Создаем директорию для сохранения
            os.makedirs(os.path.join(self.config.media_root, self.config.generated_images_dir), exist_ok=True)

            # Сохраняем файл
            import uuid
            filename = f"ai_image_{uuid.uuid4().hex}.png"
            filepath = os.path.join(self.config.media_root, self.config.generated_images_dir, filename)

            with open(filepath, 'wb') as f:
                f.write(img_data)

            # Формируем URL
            file_url = f"/{self.config.generated_images_dir}{filename}"

            return {
                "url": file_url,
                "path": filepath,
                "data": img_data,
                "success": True,
                "cost": cost
            }

        except Exception as e:
            logger.error(f"DALL-E generation error: {str(e)}")
            raise

    async def _generate_tts_audio(
        self,
        text: str,
        model_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """Генерирует аудио с помощью TTS API"""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.config.openai_api_key)

            response = client.audio.speech.create(
                model=model_override or self.config.tts_model,
                voice="alloy",
                input=text
            )

            audio_data = response.content

            # Рассчитываем стоимость
            chars_count = len(text)
            cost = self._calculate_cost(chars_count, 0, self.config.tts_model)

            # Создаем директорию для сохранения
            os.makedirs(os.path.join(self.config.media_root, self.config.generated_audio_dir), exist_ok=True)

            # Сохраняем файл
            import uuid
            filename = f"ai_audio_{uuid.uuid4().hex}.mp3"
            filepath = os.path.join(self.config.media_root, self.config.generated_audio_dir, filename)

            with open(filepath, 'wb') as f:
                f.write(audio_data)

            # Формируем URL
            file_url = f"/{self.config.generated_audio_dir}{filename}"

            return {
                "url": file_url,
                "path": filepath,
                "data": audio_data,
                "success": True,
                "cost": cost,
                "chars_count": chars_count
            }

        except Exception as e:
            logger.error(f"TTS generation error: {str(e)}")
            raise

# Инициализация глобального экземпляра для использования в других модулях
llm_factory = LLMFactory()