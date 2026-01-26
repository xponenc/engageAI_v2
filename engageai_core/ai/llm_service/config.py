"""
Конфигурация для LLMFactory и всего LLM-модуля
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any, Literal, Annotated

from pydantic import Field, field_validator, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

import logging

logger = logging.getLogger(__name__)


class LLMConfig(BaseSettings):
    """
    Централизованная конфигурация LLM-модуля (2026-ready)
    """
    # ─── OpenAI ─────────────────────────────────────────────────────
    openai_api_key: Optional[str] = Field(
        default=None,
    )

    # ─── Основные параметры генерации ───────────────────────────────
    llm_model_name: str = Field(
        default="gpt-4o-mini",
        description="Основная модель (gpt-4o-mini, o3-mini, ...)"
    )
    llm_fallback_model: str = Field(
        default="gpt-4o-mini",
    )
    use_fallback: bool = Field(default=False)
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=2048, ge=128, le=32768)

    # ─── Локальные модели ───────────────────────────────────────────
    use_local_models: bool = Field(default=False)
    local_model_type: Literal["huggingface", "llama-cpp"] = Field(
        default="llama-cpp",
    )
    local_model_path: Optional[Path] = Field(
        default=None,
        description="Путь к модели (GGUF или HF repo/dir)"
    )

    # ─── Кэширование ────────────────────────────────────────────────
    use_cache: bool = Field(default=True)
    redis_url: Optional[str] = Field(default=None)
    cache_ttl: int = Field(default=3600, ge=60)

    # ─── Учёт затрат и мониторинг ───────────────────────────────────
    enable_cost_tracking: bool = Field(default=True)

    # ─── Медиа-генерация (DALL·E / TTS) ─────────────────────────────
    media_generation_enabled: bool = Field(default=False)
    dalle_model: str = Field(default="dall-e-3")
    tts_model: str = Field(default="tts-1")
    media_root: Path = Field(default=Path("media"))

    # ─── Таймауты и надёжность ──────────────────────────────────────
    request_timeout: float = Field(default=60.0)
    max_retries: int = Field(default=3, ge=1)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),
        populate_by_name=True
    )

    @field_validator('openai_api_key')
    @classmethod
    def check_openai_key(cls, v: Optional[str], info) -> Optional[str]:
        if not info.data.get('use_local_models', False) and not v:
            raise ValueError("OPENAI_API_KEY обязателен при использовании облачных моделей")
        return v

    @field_validator('local_model_path')
    @classmethod
    def check_local_path(cls, v: Optional[Path], info) -> Optional[Path]:
        if info.data.get('use_local_models', False) and v:
            if not v.exists():
                raise ValueError(f"Путь к локальной модели не существует: {v}")
        return v

    @classmethod
    def from_env_file(cls, path: Optional[str | Path] = None) -> 'LLMConfig':
        if path is None:
            # Автопоиск .env
            current = Path.cwd()
            for _ in range(6):
                candidate = current / ".env"
                if candidate.is_file():
                    path = candidate
                    break
                current = current.parent

        if path and Path(path).is_file():
            os.environ["ENV_FILE"] = str(path)  # для pydantic_settings

        try:
            return cls()
        except ValidationError as e:
            logger.error("Ошибка валидации конфигурации LLM:\n%s", e)
            raise

    def __repr__(self) -> str:
        d = self.model_dump(exclude={'openai_api_key'})
        if self.openai_api_key:
            d['openai_api_key'] = '***'
        return f"LLMConfig({d})"

    def public_dump(self) -> Dict[str, Any]:
        """Для логов и отладки — без секретов"""
        return self.model_dump(exclude={'openai_api_key'})