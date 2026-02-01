"""
Тонкая фабрика / фасад для LLM-модуля.

Основная задача:
- Создать GenerationService с правильными зависимостями
- Предоставить удобные методы generate_* (как было раньше)
- Скрыть детали инициализации провайдеров, сервисов и конфигурации

Теперь это НЕ большой класс с тысячами строк — просто точка входа.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .config import LLMConfig
from .dtos import GenerationResult
from .services.generation import GenerationService
from .prompt.builder import DefaultPromptBuilder, PromptBuilder
from .cost.calculator import OpenAICostCalculator, ZeroCostCalculator, CostCalculator


class LLMFactory:
    """
    Фасад для работы с LLM.

    Пример использования:
        factory = LLMFactory()
        result = await factory.generate_json_response(
            system_prompt="Ты полезный репетитор",
            user_message="Объясни, что такое интеграл",
            conversation_history=[...]
        )
    """

    def __init__(
        self,
        config: Optional[LLMConfig] = None,
        prompt_builder: Optional[PromptBuilder] = None,
        cost_calculator: Optional[CostCalculator] = None,
        **kwargs,
    ):
        """
        Args:
            config: если не передан → берётся из .env / переменных окружения
            prompt_builder: кастомный билдер промптов (редко нужен)
            cost_calculator: кастомный калькулятор стоимости (почти никогда)
            **kwargs: переопределения полей конфигурации (llm_model_name, temperature и т.д.)
        """
        self.config = config or LLMConfig.from_env_file()

        # Переопределения из kwargs (удобно для тестов / экспериментов)
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)

        # Создаём зависимости
        self.prompt_builder = prompt_builder or DefaultPromptBuilder(
            history_limit=5,
            add_json_instruction=True,
        )

        if cost_calculator is not None:
            self.cost_calculator = cost_calculator
        else:
            # Автоматически выбираем в зависимости от режима
            if self.config.use_local_models:
                from .cost.calculator import zero_cost_calculator
                self.cost_calculator = zero_cost_calculator
            else:
                from .cost.calculator import openai_cost_calculator
                self.cost_calculator = openai_cost_calculator

        # Главный сервис — создаётся один раз
        self._service: GenerationService = GenerationService(
            config=self.config,
            prompt_builder=self.prompt_builder,
            cost_calculator=self.cost_calculator,
        )

    # ─── Высокоуровневые методы (совместимы со старым API) ───

    async def generate_json_response(
        self,
        system_prompt: str,
        user_message: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        media_context: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,  # для логирования
        **kwargs,
    ) -> GenerationResult:
        """
        Генерирует структурированный JSON-ответ (как раньше).
        """
        return await self._service.generate_json_response(
            system_prompt=system_prompt,
            user_message=user_message,
            conversation_history=conversation_history,
            media_context=media_context,
            temperature=temperature,
            max_tokens=max_tokens,
            context=context,
            **kwargs,
        )

    async def generate_text_response(
        self,
        system_prompt: str,
        user_message: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        media_context: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,  # для логирования
        **kwargs,
    ) -> GenerationResult:
        """
        Генерирует обычный текстовый ответ (без принудительного JSON).
        """
        # Можно добавить отдельный метод в GenerationService позже
        # Пока используем тот же механизм, но с response_format="text"
        # TODO универсальный метод надо доделать
        return await self._service.generate_text_response(
            system_prompt=system_prompt,
            user_message=user_message,
            conversation_history=conversation_history,
            media_context=media_context,
            temperature=temperature,
            max_tokens=max_tokens,
            context=context,
            **kwargs,
        )

    async def generate_media(
        self,
        media_type: str,  # "image" | "audio"
        prompt: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Генерирует изображение или аудио (только для OpenAI-провайдера).
        """
        result = await self._service.generate_media(
            media_type=media_type,
            prompt=prompt,
            **kwargs,
        )
        return result.model_dump()  # или адаптировать под старый формат

    # Дополнительные методы, если нужны
    @property
    def current_model(self) -> str:
        """Текущая используемая модель (для логов / отладки)"""
        return self._service.provider.model_name

    @property
    def is_local(self) -> bool:
        """Работаем с локальной моделью?"""
        return self._service.provider.is_local

    def reload_config(self, new_config: LLMConfig):
        """Перезагрузка конфигурации и пересоздание сервиса (редко)"""
        self.config = new_config
        self._service = GenerationService(
            config=new_config,
            prompt_builder=self.prompt_builder,
            cost_calculator=self.cost_calculator,
        )


# Глобальный экземпляр (как было раньше)
llm_factory = LLMFactory()