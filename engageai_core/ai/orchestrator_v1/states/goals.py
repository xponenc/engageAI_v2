from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict


class GoalType(str, Enum):
    """Ключевые цели обучения"""
    PROFILE_BUILDING = "prf"  # Профиль студента
    ENGAGEMENT = "eng"  # Вовлечённость
    GAP_ANALYSIS = "gap"  # Анализ пробелов
    TUTORING = "tut"  # Обучение
    PROGRESSION = "prg"  # Прогресс по плану


@dataclass
class GoalState:
    """Состояние цели с оценкой 1-10 и доказательствами"""
    goal_type: GoalType
    score: int = 3  # Стартовый уровень (не 0 — даём шанс на рост)
    evidence: List[str] = field(default_factory=list)

    @property
    def is_achieved(self) -> bool:
        """Цель достигнута при оценке ≥7 с конкретными фактами"""
        return self.score >= 7 and len(self.evidence) >= 2

    def update(self, delta: int, evidence: Optional[str] = None):
        """Обновление цели с ограничением 1-10"""
        self.score = max(1, min(10, self.score + delta))
        if evidence:
            self.evidence.append(evidence)


class GoalManager:
    """Управление всеми целями студента"""

    def __init__(self):
        self.goals = {
            GoalType.PROFILE_BUILDING: GoalState(GoalType.PROFILE_BUILDING, score=3),
            GoalType.GAP_ANALYSIS: GoalState(GoalType.GAP_ANALYSIS, score=2),
            GoalType.TUTORING: GoalState(GoalType.TUTORING, score=2),
            GoalType.PROGRESSION: GoalState(GoalType.PROGRESSION, score=1),
        }

    def update_from_message(self, message: str, lesson_context: 'LessonContext') -> Dict[GoalType, int]:
        """
        Анализ сообщения и обновление целей на основе контекста.
        Соответствует ТЗ Задача 1.1: "квалификация пользователя".
        """
        # 1. PROFILE_BUILDING: выявление уровня/профессии/целей
        if any(kw in message.lower() for kw in ["уровень", "начинаю", "цель", "профессия", "работаю"]):
            # Если студент сам назвал уровень/профессию — +2 к цели
            if any(cefr in message.lower() for cefr in ["a1", "a2", "b1", "b2", "c1", "c2"]):
                self.goals[GoalType.PROFILE_BUILDING].update(2, f"Упомянул уровень: {message}")
            if any(tag in message.lower() for tag in ["backend", "qa", "data", "marketing"]):
                self.goals[GoalType.PROFILE_BUILDING].update(2, f"Упомянул профессию: {message}")

        # 2. GAP_ANALYSIS: выявление слабых мест через ошибки
        if lesson_context.last_task_result == "incorrect" and "почему" in message.lower():
            self.goals[GoalType.GAP_ANALYSIS].update(3, f"Запрос анализа ошибки: {message}")

        # 3. TUTORING: запрос помощи с контентом
        if any(kw in message.lower() for kw in ["объясни", "почему так", "правило", "пример"]):
            self.goals[GoalType.TUTORING].update(2, f"Запрос объяснения: {message}")

        # 4. PROGRESSION: запрос о следующих шагах
        if any(kw in message.lower() for kw in ["дальше", "следующий", "что делать", "план"]):
            self.goals[GoalType.PROGRESSION].update(3, f"Запрос навигации: {message}")

        return {gt: g.score for gt, g in self.goals.items()}

    def get_priority_goal(self) -> GoalType:
        """Определение приоритетной цели для выбора агента"""
        # Правило: сначала профиль, потом анализ пробелов, потом обучение, потом прогресс
        priority_order = [
            GoalType.PROFILE_BUILDING,
            GoalType.GAP_ANALYSIS,
            GoalType.TUTORING,
            GoalType.PROGRESSION
        ]

        for goal_type in priority_order:
            if not self.goals[goal_type].is_achieved:
                return goal_type

        # Все цели достигнуты → фокус на прогрессе
        return GoalType.PROGRESSION

    def to_dict(self) -> Dict:
        """Сериализация для логирования (Задача 2.3 ТЗ)"""
        return {
            "prf": self.goals[GoalType.PROFILE_BUILDING].score,
            "gap": self.goals[GoalType.GAP_ANALYSIS].score,
            "tut": self.goals[GoalType.TUTORING].score,
            "prg": self.goals[GoalType.PROGRESSION].score,
            "priority": self.get_priority_goal().value
        }
