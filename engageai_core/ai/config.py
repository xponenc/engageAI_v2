"""
Конфигурация для LLMFactory

Этот модуль предоставляет централизованную конфигурацию для всех LLM-моделей
в системе. Он полностью независим от Django и предназначен для использования
в любом Python-проекте.

Основные функции:
- Единое место для всех параметров LLM
- Автоматическое чтение из .env файла
- Строгая валидация типов и значений
- Безопасное управление секретами (API-ключи никогда не выводятся в логи)
- Поддержка как облачных (OpenAI), так и локальных моделей

Важные особенности:
1. Приоритет источников конфигурации:
   - Переменные окружения (наивысший приоритет)
   - Файл .env (средний приоритет)
   - Значения по умолчанию (низший приоритет)

2. Безопасность:
   - API-ключи автоматически маскируются в логах и представлениях
   - Валидация обязательных параметров перед использованием

3. Гибкость:
   - Все параметры можно переопределить через переменные окружения
   - Автоматический поиск .env файла в родительских директориях
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator, ValidationError
import logging

logger = logging.getLogger(__name__)

class LLMConfig(BaseSettings):
    """
    Конфигурация для LLMFactory

    Содержит все необходимые параметры для инициализации и работы
    с языковыми моделями. Использует pydantic для валидации типов
    и значений параметров.
    """

    # OpenAI API (опционально, требуется только при use_local_models=False)
    openai_api_key: Optional[str] = Field(default=None, env="OPENAI_API_KEY")

    # Основные параметры моделей
    llm_model_name: str = Field(default="gpt-4.1-mini", env="LLM_MODEL_NAME")
    llm_fallback_model: str = Field(default="gpt-4.1-mini", env="LLM_FALLBACK_MODEL")
    llm_temperature: float = Field(default=0.0, ge=0.0, le=1.0, env="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=20000, env="LLM_MAX_TOKENS")

    # Локальные модели (опционально)
    use_local_models: bool = Field(default=False, env="USE_LOCAL_MODELS")
    local_model_path: Optional[str] = Field(default=None, env="LOCAL_MODEL_PATH")
    local_model_type: str = Field(default="huggingface", env="LOCAL_MODEL_TYPE")  # Доступные типы: huggingface, llama-cpp

    # Кэширование запросов
    use_cache: bool = Field(default=True, env="USE_LLM_CACHE")
    redis_url: Optional[str] = Field(default=None, env="REDIS_URL")
    cache_ttl: int = Field(default=3600, env="CACHE_TTL")  # Время жизни кэша в секундах

    # Трекинг затрат (только для OpenAI)
    enable_cost_tracking: bool = Field(default=True, env="ENABLE_COST_TRACKING")

    # Rate limiting и retry механизмы
    max_retries: int = Field(default=3, ge=1, le=10, env="MAX_RETRIES")
    base_retry_delay: float = Field(default=1.0, ge=0.1, env="BASE_RETRY_DELAY")
    max_retry_delay: float = Field(default=10.0, ge=1.0, env="MAX_RETRY_DELAY")

    # Медиа-генерация (только для OpenAI)
    media_generation_enabled: bool = Field(default=True, env="MEDIA_GENERATION_ENABLED")
    dalle_model: str = Field(default="dall-e-3", env="DALLE_MODEL")
    tts_model: str = Field(default="tts-1", env="TTS_MODEL")

    # Папки для медиа
    media_root: str = Field(default="media/", env="MEDIA_ROOT")
    generated_images_dir: str = Field(default="generated/images/", env="GENERATED_IMAGES_DIR")
    generated_audio_dir: str = Field(default="generated/audio/", env="GENERATED_AUDIO_DIR")

    # Таймауты запросов
    request_timeout: int = Field(default=30, env="REQUEST_TIMEOUT")
    media_generation_timeout: int = Field(default=60, env="MEDIA_GENERATION_TIMEOUT")

    @field_validator('openai_api_key')
    @classmethod
    def validate_openai_api_key(cls, v, info):
        """
        Валидация API ключа OpenAI

        Проверяет, что API ключ предоставлен, если не используются локальные модели

        Args:
            v: Значение поля openai_api_key
            info: Дополнительная информация о конфигурации

        Raises:
            ValueError: Если API ключ отсутствует при использовании OpenAI
        """
        use_local_models = info.data.get('use_local_models', False)
        if not use_local_models and not v:
            raise ValueError("OPENAI_API_KEY is required when not using local models")
        return v

    @field_validator('local_model_path')
    @classmethod
    def validate_local_model_path(cls, v, info):
        """
        Валидация пути к локальной модели

        Проверяет, что путь существует и указывает на файл или директорию,
        если используются локальные модели

        Args:
            v: Значение поля local_model_path
            info: Дополнительная информация о конфигурации

        Raises:
            ValueError: Если путь не существует или не является файлом/директорией
        """
        use_local_models = info.data.get('use_local_models', False)
        if use_local_models and v:
            if not os.path.exists(v):
                raise ValueError(f"Local model path does not exist: {v}")
            if not (os.path.isfile(v) or os.path.isdir(v)):
                raise ValueError(f"Local model path is not a valid file or directory: {v}")
        return v

    @classmethod
    def from_env_file(cls, env_file_path: Optional[str] = None) -> 'LLMConfig':
        """
        Создает конфигурацию из файла .env

        Автоматически ищет .env файл в текущей и родительских директориях,
        если путь не указан явно.

        Args:
            env_file_path: Путь к файлу .env (если None, ищет автоматически)

        Returns:
            Экземпляр LLMConfig с загруженными настройками

        Raises:
            ValidationError: Если конфигурация не прошла валидацию
        """
        if env_file_path is None:
            # Автоматический поиск .env файла
            current_dir = Path.cwd()
            for _ in range(5):  # Проверяем до 5 уровней вверх
                env_path = current_dir / ".env"
                if env_path.exists():
                    env_file_path = str(env_path)
                    logger.debug(f"Found .env file at: {env_file_path}")
                    break
                current_dir = current_dir.parent

        # Загрузка переменных окружения из .env файла
        if env_file_path and os.path.exists(env_file_path):
            try:
                from dotenv import load_dotenv
                load_dotenv(env_file_path)
                logger.info(f"Loaded environment variables from {env_file_path}")
            except ImportError:
                logger.warning("python-dotenv package not installed. Environment variables must be set manually.")

        # Создание и валидация конфигурации
        try:
            config = cls()
            logger.info("LLM configuration loaded successfully")
            return config
        except ValidationError as e:
            logger.error(f"Configuration validation error: {e}")
            raise

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # Игнорируем неизвестные переменные окружения
        protected_namespaces = ("settings_",)  # Защита от конфликтов имен

    def __repr__(self):
        """Возвращает человекочитаемое представление конфигурации (без секретов)"""
        # Создаем копию атрибутов без секретов
        attrs = {}
        for k, v in self.__dict__.items():
            if k == 'openai_api_key' and v:
                attrs[k] = "***REDACTED***"  # Маскируем API ключ
            else:
                attrs[k] = v
        return f"LLMConfig({', '.join(f'{k}={repr(v)}' for k, v in attrs.items())})"

    def model_dump_public(self) -> Dict[str, Any]:
        """
        Возвращает публичную часть конфигурации без секретов

        Полезно для логирования и отладки

        Returns:
            Словарь с публичными параметрами конфигурации
        """
        return {
            "use_local_models": self.use_local_models,
            "model_name": self.llm_model_name if not self.use_local_models else os.path.basename(self.local_model_path or ""),
            "model_type": self.local_model_type if self.use_local_models else "openai",
            "temperature": self.llm_temperature,
            "max_tokens": self.llm_max_tokens,
            "use_cache": self.use_cache,
            "enable_cost_tracking": self.enable_cost_tracking if not self.use_local_models else False
        }