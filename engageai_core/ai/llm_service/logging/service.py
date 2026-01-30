"""
Отдельный сервис для логирования запросов к LLM.

Принципы:
- Не бросает исключения наружу (silent fail при проблемах с БД)
- Асинхронный вызов (run_in_executor для ORM)
- Полностью отключаем по конфигу
- Логирует только успешные / неуспешные запросы
- Ограничивает длину полей для безопасности БД
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from llm_logger.models import LogLLMRequest
from ...config import LLMConfig

logger = logging.getLogger(__name__)

# Проверяем наличие Django один раз при импорте
DJANGO_AVAILABLE = False

try:
    DJANGO_AVAILABLE = True
except ImportError:
    logger.warning("Django models (LogLLMRequest) not available → LLM logging disabled")


class LLMLloggingService:
    """
    Сервис логирования запросов к LLM в базу данных.
    """

    def __init__(self, config: LLMConfig):
        self.config = config
        self.enabled = DJANGO_AVAILABLE #config.enable_llm_logging and DJANGO_AVAILABLE

        # Ограничения длины полей (защита от слишком больших промптов/ответов)
        self.max_prompt_length = 10000
        self.max_response_length = 5000
        self.max_error_length = 1000

    async def log_request(
        self,
        provider: str,
        full_prompt: str,
        generation_result: "GenerationResult",
        context: Optional[Dict[str, Any]] = None,
        status: str = "SUCCESS",
        error_message: str = "",
    ) -> None:
        """
        Асинхронно записывает лог в БД (если включено).

        Не бросает исключений — ошибки логируются в warning.
        """
        if not self.enabled:
            return

        context = context or {}

        try:
            if isinstance(full_prompt, str):
                full_prompt = {
                    "full_prompt": full_prompt,
                }


            # Подготавливаем данные для модели
            log_data = self._prepare_log_data(
                provider=provider,
                generation_result=generation_result,
                full_prompt=full_prompt,
                status=status,
                error_message=error_message,
                context=context
            )

            # Асинхронное сохранение
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._sync_save, log_data)

        except Exception as e:
            logger.warning(f"Не удалось записать лог LLM-запроса: {e}", exc_info=True)
    #
    # def _build_full_prompt(
    #     self,
    #     system_prompt: str,
    #     user_message: str,
    #     history: Optional[list] = None,
    #     media: Optional[list] = None,
    # ) -> str:
    #     """Воссоздаёт полный промпт (примерно как раньше)"""
    #     parts = [system_prompt]
    #
    #     if media:
    #         media_info = "\nКонтекст медиафайлов:"
    #         for m in media:
    #             media_info += f"\n- Тип: {m.get('type')}, URL: {m.get('url')}"
    #         parts.append(media_info)
    #
    #     if history:
    #         parts.append("\nИстория диалога:")
    #         for entry in history[-5:]:
    #             parts.append(f"Студент: {entry.get('user_message', '')}")
    #             resp = entry.get('agent_response', {})
    #             if isinstance(resp, dict):
    #                 parts.append(f"Репетитор: {resp.get('message', '...')}")
    #             else:
    #                 parts.append(f"Репетитор: {str(resp)}")
    #
    #     parts.append(f"\nСообщение студента:\n{user_message}")
    #
    #     return "\n".join(parts)

    def _prepare_log_data(
        self,
        provider: str,
        generation_result: "GenerationResult",
        full_prompt: dict,
        status: str,
        error_message: str,
        context: Dict[str, Any],
    ) -> dict:
        """Готовит словарь для создания LogLLMRequest"""
        metrics = generation_result.metrics
        response = generation_result.response

        # Ограничиваем длину
        prompt_trunc = full_prompt[:self.max_prompt_length]
        response_trunc = str(response.message)[:self.max_response_length]
        error_trunc = error_message[:self.max_error_length]

        if isinstance(response.message, str):
            response_txt = response.message
            response_json = None
        else:
            try:
                import json
                json.dumps(response.message)
                response_json = response.message
                response_txt = None
            except (TypeError, ValueError) as e:
                # Если не JSON-сериализуемо, сохраняем как строку
                response_txt = str(response.message)
                response_json = None

        data = {
            "model_name": metrics.model_used,
            "prompt": prompt_trunc,
            "response": response_txt,
            "response_json": response_json,
            "tokens_in": metrics.input_tokens,
            "tokens_out": metrics.output_tokens,
            "cost_in": round(metrics.cost_in, 6),
            "cost_out": round(metrics.cost_out, 6),
            "cost_total": round( metrics.cost_total, 6),
            "duration_sec": round(metrics.generation_time_sec, 3),
            "status": status,
            "error_message": error_trunc,
            "metadata": {
                "cached": metrics.cached,
                "temperature": self.config.llm_temperature,
                "max_tokens": self.config.llm_max_tokens,
                "provider": provider,
                "response_format": context.get("response_format", "json"),
            },
        }

        # Контекстные связи (если есть)
        for field in ["user_id", "course_id", "lesson_id", "session_id", "task_id", "request_type"]:
            if field in context and context[field]:
                data[field] = context[field]

        return data

    def _sync_save(self, log_data: dict) -> None:
        """Синхронное сохранение в БД (вызывается в executor)"""
        try:
            LogLLMRequest.objects.create(**log_data)
        except Exception as e:
            logger.error(f"Ошибка сохранения лога в БД: {e}", exc_info=True)


# Глобальный экземпляр (или можно инжектить)
llm_logging_service = LLMLloggingService(LLMConfig.from_env_file())