# engageai_core/ai/orchestrator.py
import json
import os
from typing import Dict, Any
from openai import AsyncOpenAI

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
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

    async def _get_llm_response(self, agent_type: str, message: str) -> Dict[str, Any]:
        """
        Получает и парсит ответ от LLM
        """
        user_state = self.state_manager.get_current_state()
        response = await self.agent_factory.create_agent_response(
            agent_type=agent_type,
            user_state=user_state,
            user_message=message,
            platform=self.platform
        )
        return response

    def process_message(self, message_text: str) -> Dict[str, Any]:
        """
        Основной метод обработки сообщения
        """
        current_agent = self._determine_current_agent()

        # Асинхронный вызов LLM
        import asyncio
        result = asyncio.run(self._get_llm_response(current_agent, message_text))

        # Обновление состояния пользователя
        self.state_manager.update_state(
            user_message=message_text,
            agent_response=result
        )

        return result