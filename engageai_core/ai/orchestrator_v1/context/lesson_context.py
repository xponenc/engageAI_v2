from dataclasses import dataclass
from typing import List, Optional, Set


@dataclass
class LessonContext:
    """
    Контекст текущего урока для чат-оркестратора.

    Правила:
    - НЕ содержит методов доступа к БД
    - НЕ содержит бизнес-логики
    - ТОЛЬКО хранит данные и предоставляет методы сериализации
    """
    # Метаданные урока
    lesson_id: int
    lesson_title: str
    lesson_type: str  # "grammar", "vocabulary", "professional_scenario" и т.д.
    course_id: int
    course_title: str
    cefr_level: str  # "A1", "A2", "B1"...
    professional_tags: List[str]
    skill_focus: List[str]  # ["listening", "vocabulary"]
    duration_minutes: int

    # Состояние урока
    state: str  # "OPEN", "IN_PROGRESS", "COMPLETED"
    progress_percent: float  # 0.0 - 100.0

    # Прогресс по заданиям
    total_tasks: int
    completed_tasks: int
    correct_tasks: int
    incorrect_tasks: int
    last_task_result: Optional[str]  # "correct", "incorrect", None

    # Ремедиация
    needs_remediation: bool
    remediation_reason: Optional[str]  # "weak_grammar", "vocabulary_gap"
    next_lesson_id: Optional[int]
    next_lesson_is_remedial: bool

    # Адаптивные параметры
    adaptive_parameters: dict

    # Поведенческие сигналы (агрегированные из заданий)
    frustration_signals: int = 0  # 0-10 (из анализа ошибок в заданиях урока)
    is_critically_frustrated: bool = False

    def to_dict(self) -> dict:
        """Сериализация для передачи в агенты"""
        return {
            "lesson_id": self.lesson_id,
            "lesson_title": self.lesson_title,
            "lesson_type": self.lesson_type,
            "course_title": self.course_title,
            "cefr_level": self.cefr_level,
            "professional_tags": self.professional_tags,
            "skill_focus": self.skill_focus,
            "state": self.state,
            "progress_percent": self.progress_percent,
            "completed_tasks": self.completed_tasks,
            "total_tasks": self.total_tasks,
            "last_task_result": self.last_task_result,
            "needs_remediation": self.needs_remediation,
            "frustration_signals": self.frustration_signals,
            "is_critically_frustrated": self.is_critically_frustrated,
            "next_lesson_id": self.next_lesson_id,
            "next_lesson_is_remedial": self.next_lesson_is_remedial,
        }