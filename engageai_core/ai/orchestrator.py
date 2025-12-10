# engageai_core/ai/orchestrator.py
import json
import os
from typing import Dict, Any
from openai import AsyncOpenAI

from ai.llm.llm_factory import llm_factory
from engageai_core.ai.state_manager import UserStateManager
from engageai_core.ai.agent_factory import AgentFactory


class Orchestrator:
    """
    Оркестратор для управления AI-агентами через LLM
    """

    def __init__(self, user_id: str, user_context: Dict[str, Any] = None, platform: str = "web"):
        """
        Инициализация оркестратора

        Args:
            user_id: Уникальный идентификатор пользователя в системе
            user_context: Контекст пользователя из состояния
            platform: Платформа (web, telegram, etc.)
        """
        self.user_id = str(user_id)  # Универсальный user_id вместо telegram_id
        self.user_context = user_context or {}
        self.platform = platform
        self.state_manager = UserStateManager(self.user_id)
        self.agent_factory = AgentFactory()
        # self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def _determine_current_agent(self) -> str:
        """
        Определяет текущего агента на основе состояния пользователя
        """
        user_state = self.state_manager.get_current_state()

        # Если нет данных о пользователе - диагност
        if not user_state.get('profile') or not user_state['profile'].get('english_level'):
            return 'diagnostic'

        # Если есть профиль, но нет учебного плана - куратор
        if not user_state.get('learning_plan'):
            return 'curator'

        # Если есть план и engagement высокий - преподаватель
        engagement = user_state.get('metrics', {}).get('engagement', 5)
        if engagement >= 7:
            return 'teacher'

        return 'curator'

    async def _get_llm_response(self, agent_type: str, message: str, media_files=None) -> Dict[str, Any]:
        """
        Получает и парсит ответ от LLM с использованием LLMFactory
        """
        user_state = self.state_manager.get_current_state()

        # Формируем системный промпт
        system_prompt = self.agent_factory._get_agent_prompt(agent_type, user_state)

        # Генерируем ответ с использованием LLMFactory
        generation_result = await llm_factory.generate_json_response(
            system_prompt=system_prompt,
            user_message=message,
            conversation_history=user_state.get('history', []),
            media_context=media_files
        )

        # Возвращаем структурированный ответ
        return {
            "message": generation_result.response.message,
            "agent_state": generation_result.response.agent_state,
            "metadata": {
                "token_usage": generation_result.token_usage,
                "cost": generation_result.cost,
                "model_used": generation_result.model_used,
                "generation_time": generation_result.generation_time
            }
        }

    def process_message(self, user_context) -> Dict[str, Any]:
        """
        Основной метод обработки сообщения с поддержкой медиа
        """
        # Определяем тип входных данных
        if isinstance(user_context, dict):
            message_text = user_context.get('text', '')
            media_files = user_context.get('media', [])
        else:
            message_text = user_context
            media_files = []

        current_agent = self._determine_current_agent()

        # Асинхронный вызов LLM
        import asyncio
        result = asyncio.run(self._get_llm_response(current_agent, message_text, media_files))

        # Обновление состояния пользователя
        self.state_manager.update_state(
            user_message=message_text,
            agent_response=result
        )

        return result

        # Обновление состояния пользователя
        self.state_manager.update_state(
            user_message=message_text,
            agent_response=result
        )

        return result