from ai.orchestrator_v1.agents.base import BaseAgent, AgentResponse
from ai.orchestrator_v1.context.agent_context import AgentContext


class ContentAgent(BaseAgent):
    name = "ContentAgent"
    description = "Объяснение грамматики и лексики"
    supported_intents = ["EXPLAIN_GRAMMAR", "PRACTICE_VOCABULARY"]

    async def handle(self, context: AgentContext) -> AgentResponse:
        """
        Промпт уже включает контекст для персонализации:
        - Уровень студента (CEFR)
        - Профессиональные теги
        - Слабые места
        - Эмоциональное состояние (для адаптации ТОНА, а не содержания)

        Пример промпта:
        "Вы — эксперт по грамматике. Студент: уровень B1, backend-разработчик,
        слабое место — past tenses, текущее состояние — фрустрация (3 ошибки подряд).
        Объясните правило Past Perfect КРАТКО (макс 150 слов),
        используйте пример из сферы программирования,
        тон — поддерживающий, без сложных терминов."
        """
        system_prompt = self._build_system_prompt(context)
        user_message = context.user_message

        print(system_prompt)
        print(user_message)

        result = await self.llm.generate_text_response(
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=300,  # ← Контроль длины ЧЕРЕЗ ПРОМПТ, не постобработку
            temperature=0.3,
            context={"agent": self.name, "user_id": context.user_context.user_id}
        )

        print(f"ContentAgent {result=}")

        return AgentResponse(
            response=result,
        )

    def _build_system_prompt(self, context: AgentContext) -> str:
        """Формирование промпта с полным контекстом для персонализации"""
        user_context = context.user_context

        # Мягкая адаптация по уровню фрустрации (0–10)
        if user_context.frustration_signals >= 7:
            emotional_tone = "максимально поддерживающий, очень бережный"
        elif user_context.frustration_signals >= 3:
            emotional_tone = "поддерживающий, без давления"
        else:
            emotional_tone = "нейтральный, экспертный"

        critical_note = ""
        if user_context.is_critically_frustrated:
            critical_note = (
                "\n- Дополнительно: студент сейчас в состоянии высокой фрустрации, "
                "избегайте оценочных суждений, делайте акцент на поддержке и маленьких шагах."
            )
        complexity = "максимально просто, без терминов" if user_context.confidence_level <= 4 else "стандартная сложность"

        return f"""Вы — эксперт по грамматике английского языка.
Контекст студента:
- Уровень: {user_context.cefr_level}
- Эмоциональное состояние: {emotional_tone} {critical_note}
- Требования к ответу: {complexity}, максимум 150 слов

Ваша задача: дать точный, полезный ТЕКСТОВЫЙ ответ на вопрос студента."""
