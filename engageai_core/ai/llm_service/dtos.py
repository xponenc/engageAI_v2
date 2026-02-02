"""
Data Transfer Objects (Pydantic модели и dataclasses) для LLM-модуля.
Используются для строгой типизации входов/выходов между слоями.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


@dataclass
class LLMResponse:
    """Финальный ответ, который отдаётся наверх (агенту / контроллеру)"""
    message: str = Field(description="Текст, который увидит пользователь")
    agent_state: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class GenerationMetrics(BaseModel):
    """Метрики одной генерации — для логов, мониторинга, стоимости"""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_in: float = 1000.0
    cost_out: float = 1000.0
    cost_total: float = 1000.0
    generation_time_sec: float = 0.0
    model_used: str = ""
    cached: bool = False

    def with_cost(self, cost: dict) -> "GenerationMetrics":
        """
        Возвращает копию метрик с обновлённой стоимостью.
        Сохраняет неизменяемость оригинальных метрик (immutable pattern).
        """
        return self.model_copy(update={**cost})


@dataclass
class GenerationResult:
    """Полный результат одной генерации"""
    response: LLMResponse
    metrics: GenerationMetrics
    raw_provider_response: Any = None           # для отладки
    error: Optional[Exception] = None
    metadata: Dict[str, Any] = None


class MediaGenerationResult(BaseModel):
    """Результат генерации изображения / аудио"""
    success: bool = False
    url: Optional[str] = None
    local_path: Optional[str] = None
    mime_type: Optional[str] = None
    cost_usd: float = 0.0
    error: Optional[str] = None