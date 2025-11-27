# engageai_core/ai/agent_factory.py
import json
from typing import Dict, Any

from engageai_core.ai.prompts.system_prompts import get_agent_prompt
from engageai_core.ai.prompts.examples import DIAGNOSTIC_EXAMPLES, CURATOR_EXAMPLES
from engageai_core.ai.prompts.templates import format_platform_message


class AgentFactory:
    """
    Фабрика для создания ответов от AI-агентов
    """

    async def create_agent_response(self, agent_type: str, user_state: Dict[str, Any],
                                    user_message: str, platform: str = "web") -> Dict[str, Any]:
        """
        Генерирует ответ от агента на основе промпта и контекста

        Args:
            agent_type: Тип агента (diagnostic, curator, teacher)
            user_state: Текущее состояние пользователя
            user_message: Сообщение от пользователя
            platform: Платформа для форматирования ответа

        Returns:
            Структурированный ответ от агента
        """
        system_prompt = get_agent_prompt(agent_type, user_state)

        # Добавляем few-shot примеры для улучшения качества
        examples = self._get_examples(agent_type)
        if examples:
            system_prompt += "\n\nПримеры диалогов:\n" + self._format_examples(examples)

        # Формируем полный промпт с историей диалога
        conversation_history = self._format_history(user_state.get('history', []))

        full_prompt = f"""
{system_prompt}

История диалога:
{conversation_history}

Сообщение студента:
{user_message}

Ответь строго в формате JSON как указано в инструкции.
"""
        # Получаем ответ от LLM
        raw_response = await self._generate_llm_response(full_prompt)

        # Парсим структурированный ответ
        structured_response = self._parse_structured_response(raw_response)

        # Форматируем сообщение для конкретной платформы
        if "message" in structured_response:
            structured_response["message"] = format_platform_message(
                platform=platform,
                message_data=structured_response
            )

        return structured_response

    async def _generate_llm_response(self, prompt: str) -> str:
        """
        Генерирует ответ от LLM

        TODO: Интеграция с OpenAI API
        """
        # Для MVP используем mock-ответ
        mock_responses = {
            "diagnostic": {
                "message": "Здравствуйте! Я ваш персональный AI-репетитор по английскому языку. Чтобы создать идеальный план обучения, расскажите — для чего вам нужен английский: для работы, путешествий, общения или карьерного роста?",
                "agent_state": {
                    "estimated_level": None,
                    "confidence": 1,
                    "engagement_change": 1,
                    "next_question_type": "goals"
                }
            },
            "curator": {
                "message": "Отлично! На основе вашего уровня и целей я подготовил персональный план обучения. Готовы начать?",
                "agent_state": {
                    "engagement_change": 2
                }
            }
        }

        # В реальной реализации здесь будет вызов OpenAI API
        import random
        return json.dumps(random.choice(list(mock_responses.values())))

    def _get_examples(self, agent_type: str) -> list:
        """Возвращает примеры для конкретного типа агента"""
        if agent_type == 'diagnostic':
            return DIAGNOSTIC_EXAMPLES
        elif agent_type == 'curator':
            return CURATOR_EXAMPLES
        return []

    def _format_examples(self, examples: list) -> str:
        """Форматирует примеры для промпта"""
        formatted = ""
        for example in examples:
            formatted += f"Контекст: {example['context']}\n"
            formatted += f"Вход: {example['input']}\n"
            formatted += f"Выход: {json.dumps(example['output'], ensure_ascii=False)}\n\n"
        return formatted

    def _format_history(self, history: list) -> str:
        """Форматирует историю диалога для промпта"""
        if not history:
            return "Диалог только начинается."

        formatted = ""
        for entry in history[-5:]:  # последние 5 сообщений для контекста
            formatted += f"Студент: {entry['user_message']}\n"
            if isinstance(entry['agent_response'], dict):
                formatted += f"Репетитор: {entry['agent_response'].get('message', '...')}\n\n"
            else:
                formatted += f"Репетитор: {entry['agent_response']}\n\n"
        return formatted

    def _parse_structured_response(self, raw_response: str) -> Dict[str, Any]:
        """Парсит структурированный ответ от LLM"""
        try:
            # Извлекаем JSON из ответа
            start_idx = raw_response.find('{')
            end_idx = raw_response.rfind('}') + 1

            if start_idx == -1 or end_idx == 0:
                raise ValueError("No JSON structure found in LLM response")

            json_str = raw_response[start_idx:end_idx]
            return json.loads(json_str)

        except Exception as e:
            # Логируем ошибку и возвращаем фолбэк
            print(f"Error parsing LLM response: {e}")
            return {
                "message": "Извините, я не совсем понял ваш ответ. Можете повторить?",
                "agent_state": {
                    "engagement_change": -1
                }
            }