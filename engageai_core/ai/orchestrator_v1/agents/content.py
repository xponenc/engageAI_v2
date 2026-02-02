from ai.llm_service.dtos import GenerationResult
from ai.orchestrator_v1.agents.base import BaseAgent
from ai.orchestrator_v1.context.agent_context import AgentContext


class ContentAgent(BaseAgent):
    name = "ContentAgent"
    description = "Объяснение грамматики и лексики"
    supported_intents = ["EXPLAIN_GRAMMAR", "PRACTICE_VOCABULARY"]
    response_max_length = 300 # максимальная длина ответа
    fallback_agent = True

    async def handle(self, context: AgentContext, response_max_length: int = None) -> GenerationResult:
        """
        Промпт уже включает контекст для персонализации:
        - Уровень студента (CEFR)
        - Профессиональные теги
        - Слабые места
        - Эмоциональное состояние (для адаптации ТОНА, а не содержания)
        """

        system_prompt = self._build_system_prompt(context)
        user_message = self._build_user_prompt(context)

        result = await self.llm.generate_text_response(
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=response_max_length or self.response_max_length,
            temperature=0.3,
            context={"agent": self.name, "user_id": context.user_context.user_id}
        )
        return result

    def _build_system_prompt(self, context: AgentContext, response_max_length: int = None) -> str:
        """Формирование промпта с полным контекстом для персонализации"""
        user_context = context.user_context
        response_max_length = response_max_length or self.response_max_length
        prompt = f"""
Вы учитель английского языка высочайшего класса с огромным опытом. Вы умеете найти правильный подход и слова для 
любого ученика.

Контекст ученика:
{user_context.to_prompt()}

Ваша задача: дать ТЕКСТОВЫЙ ответ на вопрос студента делая акцент на объяснении английского языка. 
Профессиональные направления ученика и профессиональный контекст занятий учитывайте только для создания примеров. 

Требования к ответу:
- максимум {response_max_length} слов на языке вопроса.
- Ответ должен быть сформирован в рамках дополнительного контекста 
о ученике и учебных материалах, так что бы он был максимально понятен ученику и был адаптирован под него.
- Отвечайте только на вопросы связанные с обучением студента английскому языку, вопросы на другие темы вежливо 
отклоняйте с предложением вернуться в теме английского языка.

        """
        return prompt

    def _build_user_prompt(self, context: AgentContext) -> str:
            """Формирование промпта с полным контекстом для персонализации"""
            user_message = context.user_message
            action_message = context.action_message
            lesson_context = context.lesson_context
            task_context = context.task_context

            prompt = ("ВОПРОС СТУДЕНТА ЗАДАН В РАМКАХ ДАННОГО КОНТЕКСТА:\n" if action_message
                else "Вопрос студента поступил со страницы сайта и возможно связан со следующим контекстом: \n")

            if task_context:
                prompt += task_context.to_prompt()
            if not task_context and lesson_context:
                prompt += lesson_context.to_prompt()

            prompt += f"""
ВОПРОС СТУДЕНТА:
{user_message}
"""
            return prompt
