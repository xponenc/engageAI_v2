import logging
from abc import ABC, abstractmethod
from typing import Optional, Type, Any, TypeVar

from asgiref.sync import sync_to_async
from django.db import transaction

from ai.llm_service.factory import llm_factory

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BaseContentGenerator(ABC):
    """
    Базовый класс для всех генераторов контента.
    Обеспечивает единый интерфейс работы с LLM и обработку ошибок.
    """

    def __init__(self):
        self.llm = llm_factory
        self.logger = logger

    @abstractmethod
    async def generate(self, *args, **kwargs):
        """Основной метод генерации контента"""
        pass

    @sync_to_async
    @transaction.atomic
    def _atomic_db_operation(self, operation, *args, **kwargs):
        """
        Обертка для атомарных операций с БД.
        """
        return operation(*args, **kwargs)

    async def _safe_llm_call(self,
                             system_prompt: str,
                             user_message: str,
                             response_format: Type[T],
                             temperature: Optional[float] = None,
                             context: Optional[dict] = None) -> T:
        """
        Безопасный вызов LLM с обработкой ошибок и логированием.
        """
        try:
            result = await self.llm.generate_json_response(
                system_prompt=system_prompt,
                user_message=user_message,
                temperature=temperature,
                context=context or {}
            )

            if result.error:
                logger.error(f"LLM error: {result.error}", extra={"raw_response": result.raw_provider_response})
                raise ValueError(f"LLM generation failed: {result.error}")

            data = result.response.message
            if not isinstance(data, response_format):
                raise ValueError(f"Invalid LLM response format: expected {response_format}, got {type(data).__name__}")

            return data

        except Exception as e:
            logger.exception("Critical error during LLM call",
                             extra={"system_prompt": system_prompt[:100], "user_message": user_message[:100],
                                    "context": context})
            raise

    # def _log_critical_step_error(
    #         self,
    #         step_name: str,
    #         context: dict,
    #         error: Exception,
    #         is_critical: bool = True
    # ):
    #     """Стандартизированное логирование ошибок этапов генерации"""
    #     log_method = self.logger.critical if is_critical else self.logger.error
    #
    #     log_method(
    #         f"{'КРИТИЧЕСКАЯ ОШИБКА' if is_critical else 'Ошибка'} на этапе '{step_name}': {str(error)}",
    #         extra={
    #             "step": step_name,
    #             "error_type": type(error).__name__,
    #             **context
    #         },
    #         exc_info=True
    #     )
