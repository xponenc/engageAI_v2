from curriculum.chat.goals import GoalManager, GoalType
from curriculum.chat.confidence import ConfidenceManager
from curriculum.chat.agents import (
    DiagnosticAgent, TutorAgent, ProgressAgent,
    SupportAgent, FallbackAgent
)


class EducationalOrchestrator:
    """
    Оркестратор с системой целей и доверия.
    Соответствует ТЗ Задача 1.1: "Центральный Умный Чат-Помощник должен вести за руку".
    """

    def __init__(self):
        self.goal_manager = GoalManager()
        self.confidence_manager = ConfidenceManager()
        self.llm = llm_factory  # Для резервной классификации намерений

    async def route_message(
            self,
            user_message: str,
            user_profile: Dict,
            lesson_context: 'LessonContext',
            conversation_history: List[Dict] = None
    ) -> Dict:
        """
        Полный цикл маршрутизации с учётом целей и уверенности.
        """
        # 1. Анализ намерения (упрощённая версия для старта)
        intent = self._detect_intent_simple(user_message, lesson_context)

        # 2. Обновление целей на основе сообщения
        goals_state = self.goal_manager.update_from_message(
            user_message,
            lesson_context
        )

        # 3. Обновление уверенности на основе состояния урока
        if lesson_context.last_task_result == "correct":
            self.confidence_manager.on_success(streak=lesson_context.consecutive_successes)
        elif lesson_context.last_task_result == "incorrect":
            self.confidence_manager.on_failure()

        # 4. Выбор агента на основе приоритетной цели + уверенности
        agent = self._select_agent(
            priority_goal=self.goal_manager.get_priority_goal(),
            confidence_level=self.confidence_manager.level,
            needs_support=self.confidence_manager.needs_support(),
            lesson_state=lesson_context.state
        )

        # 5. Формирование контекста для агента
        agent_context = {
            "user_message": user_message,
            "intent": intent,
            "user_profile": user_profile,
            "lesson_context": lesson_context,
            "goals": self.goal_manager.to_dict(),
            "confidence": self.confidence_manager.to_dict(),
            "conversation_history": conversation_history or []
        }

        # 6. Вызов агента
        try:
            response = await agent.handle(agent_context)
        except Exception as e:
            logger.error(f"Ошибка агента {agent.name}: {e}", exc_info=True)
            response = await FallbackAgent().handle(agent_context)

        # 7. Логирование для аналитики (Задача 2.3 ТЗ)
        await self._log_orchestration_event(
            user_id=user_profile.get("user_id"),
            intent=intent,
            goals=self.goal_manager.to_dict(),
            confidence=self.confidence_manager.to_dict(),
            agent=agent.name,
            lesson_state=lesson_context.state.value
        )

        return {
            "response": response.get("text", ""),
            "agent": agent.name,
            "goals": self.goal_manager.to_dict(),
            "confidence": self.confidence_manager.to_dict(),
            "next_action_hint": self._get_next_action_hint(lesson_context)
        }

    def _detect_intent_simple(self, message: str, lesson_context: 'LessonContext') -> str:
        """Упрощённая классификация намерений для старта (без LLM)"""
        msg_lower = message.lower()

        # Анализ ошибок в контексте урока
        if lesson_context.last_task_result == "incorrect" and "почему" in msg_lower:
            return "ANALYZE_ERROR"

        # Профилирование
        if any(kw in msg_lower for kw in ["уровень", "начинаю", "цель"]):
            return "PROFILE_BUILDING"

        # Обучение
        if any(kw in msg_lower for kw in ["объясни", "правило", "пример"]):
            return "TUTORING"

        # Навигация
        if any(kw in msg_lower for kw in ["дальше", "следующий", "план"]):
            return "PROGRESSION"

        return "GENERAL_CHAT"

    def _select_agent(
            self,
            priority_goal: GoalType,
            confidence_level: int,
            needs_support: bool,
            lesson_state: 'LessonState'
    ) -> 'BaseAgent':
        """
        Выбор агента по правилам (адаптировано из продажника).
        Соответствует ТЗ: "вести за руку" через правильную последовательность.
        """
        # Правило 1: При фрустрации → всегда SupportAgent
        if needs_support:
            return SupportAgent()

        # Правило 2: Если профиль не построен → DiagnosticAgent
        if priority_goal == GoalType.PROFILE_BUILDING and not self.goal_manager.goals[priority_goal].is_achieved:
            return DiagnosticAgent()

        # Правило 3: Если анализ пробелов не завершён → DiagnosticAgent
        if priority_goal == GoalType.GAP_ANALYSIS and not self.goal_manager.goals[priority_goal].is_achieved:
            return DiagnosticAgent()

        # Правило 4: Если обучение активно → TutorAgent
        if priority_goal in [GoalType.TUTORING, GoalType.GAP_ANALYSIS]:
            return TutorAgent()

        # Правило 5: Если урок завершён → ProgressAgent
        if lesson_state == LessonState.COMPLETED:
            return ProgressAgent()

        # По умолчанию → TutorAgent
        return TutorAgent()

    def _get_next_action_hint(self, lesson_context: 'LessonContext') -> str:
        """Подсказка о следующем действии (для дашборда Задачи 2.2)"""
        if lesson_context.state == LessonState.OPEN:
            remaining = lesson_context.total_tasks - lesson_context.completed_tasks
            if remaining > 0:
                return f"Осталось {remaining} заданий для завершения урока"
            else:
                return "Все задания выполнены! Ожидайте финальной оценки"

        elif lesson_context.state == LessonState.IN_REVIEW:
            if lesson_context.needs_remediation:
                return "Рекомендуется повторить слабые темы"
            else:
                return "Урок успешно завершён! Следующий шаг будет открыт автоматически"

        elif lesson_context.state == LessonState.COMPLETED:
            if lesson_context.next_lesson_id:
                return f"Следующий урок уже открыт: {lesson_context.next_lesson_title}"
            else:
                return "Поздравляем! Вы завершили модуль. Что дальше?"

        return "Продолжайте обучение"

    async def _log_orchestration_event(self, **kwargs):
        """Логирование для административного дашборда (Задача 2.3)"""
        # Сохранение в модель аналитики

        await LogLLMRequest.objects.acreate(
            request_type="CHAT",
            model_name="orchestrator_v2",
            prompt=kwargs.get("user_message", "")[:500],
            response=kwargs.get("response", "")[:500],
            cost_total=0,  # Оркестратор не тратит токены
            status="SUCCESS",
            metadata={
                "intent": kwargs.get("intent"),
                "goals": kwargs.get("goals"),
                "confidence": kwargs.get("confidence"),
                "agent": kwargs.get("agent"),
                "lesson_state": kwargs.get("lesson_state")
            },
            user_id=kwargs.get("user_id")
        )