import json
from typing import List, Dict

from ai.llm_service.dtos import GenerationResult
from ai.llm_service.factory import llm_factory
from ai.orchestrator_v1.context.agent_context import AgentContext
from llm_logger.models import LLMRequestType


class TopManagerAgent:
    """
    Специализированный агент для агрегации ответов нескольких агентов.

    Задача: Принять ответы от основного и вспомогательных агентов,
    собрать гармоничный финальный ответ через LLM.

    Пример:
    Вход:
    - ContentAgent: "Past Perfect используется для действия, завершившегося до другого..."
    - SupportAgent: {"micro_success": "Вы правильно заметили сложность!", "soft_cta": "Давайте закрепим?"}
    - ProfessionalAgent: "Пример из бэкенда: 'Код уже был задеплоен...'"

    Выход (через LLM):
    "Past Perfect здесь потому, что одно действие завершилось РАНЬШЕ другого в прошлом.
    Вы правильно заметили сложность этой темы — это уже половина успеха!
    Пример из вашей сферы (бэкенд): 'Код уже был задеплоен, когда я пришёл на работу'.
    Давайте закрепим на коротком примере?"
    """
    name = "TopManagerAgent"
    description = "Агрегация ответов нескольких агентов в единый связный текст"
    response_max_length = 300  # максимальная длина ответа

    def __init__(self):
        """Инициализация агента"""
        self.llm = llm_factory

    async def handle(
            self,
            request_type: LLMRequestType,
            agents_responses: List[Dict],
            agent_context: AgentContext,
            response_max_length: int = None
    ) -> GenerationResult:
        """
        Агрегация ответов через LLM.

        Алгоритм:
        1. Собрать все компоненты в структурированный промпт
        2. Передать в LLM с инструкцией собрать единый текст
        3. Вернуть финальный ответ
        """
        # Формирование компонентов для агрегации

        response_max_length = response_max_length or self.response_max_length
        agents_responses = [
            {
                "agent": ar["agent_name"],
                "role": ar["agent_role"],
                "response": ar["agent_response"].response.message,
            } for ar in agents_responses
        ]

        user_context = agent_context.user_context

        system_prompt = f"""Вы — эксперт по составлению связных, естественных ответов для учеников платформы обучения 
английскому языку.
Ваша задача: собрать финальный ответ из компонентов, сгенерированных разными агентами.

Правила:
1. Сохраняйте СОДЕРЖАНИЕ основного ответа без искажений
2. Интегрируйте микро-успехи и примеры ПЛАВНО, без разрывов
3. Адаптируйте тон под эмоциональное состояние студента:
   - При фрустрации: поддерживающий, без давления
   - При высокой уверенности: более экспертный тон
4. Максимальная длина: {response_max_length} слов
5. Завершайте мягким призывом к действию (если есть в компонентах)

Формат ответа: ТОЛЬКО финальный текст, без мета-комментариев."""

        user_prompt = f"""Компоненты для агрегации:

Ответы агентов:
{agents_responses}

Контекст студента:
{user_context.to_prompt()}

Соберите единый связный ответ."""

        result = await self.llm.generate_text_response(
            system_prompt=system_prompt,
            user_message=user_prompt,
            temperature=0.1,  # Низкая креативность для сохранения смысла
            context= {
                   "user_id": user_context.user_id,
                    "request_type": request_type,
                    "agent": f"{self.__class__.__name__}: {self.name}",
            }
        )

        return result
