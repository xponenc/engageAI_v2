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
    lesson_content: str
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

    def to_dict(self) -> dict:
        """Сериализация для передачи в агенты"""
        return {
            "lesson_id": self.lesson_id,
            "lesson_title": self.lesson_title,
            "lesson_content": self.lesson_content,
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
            "next_lesson_id": self.next_lesson_id,
            "next_lesson_is_remedial": self.next_lesson_is_remedial,
        }

    def to_prompt(self) -> str:
        """
        Человекочитаемое представление контекста урока
        для включения в LLM-промпт.

        Правила:
        - включаются только непустые поля
        - значения 0 / False считаются валидными и включаются
        - без интерпретаций и бизнес-логики
        """
        lines = ["Lesson context:"]

        def add(label: str, value):
            if value is None:
                return
            if isinstance(value, list) and not value:
                return
            if isinstance(value, dict) and not value:
                return
            lines.append(f"- {label}: {value}")

        # Метаданные урока
        add("Lesson ID", self.lesson_id)
        add("Lesson title", self.lesson_title)
        add("Lesson type", self.lesson_type)
        add("Lesson content", self.lesson_content)
        add("Course", self.course_title)
        add("CEFR level", self.cefr_level)

        if self.professional_tags:
            add("Professional tags", ", ".join(self.professional_tags))

        if self.skill_focus:
            add("Skill focus", ", ".join(self.skill_focus))

        add("Duration (minutes)", self.duration_minutes)

        # Состояние и прогресс
        add("Lesson state", self.state)
        add("Progress (%)", self.progress_percent)

        add("Tasks completed", f"{self.completed_tasks} / {self.total_tasks}")
        add("Correct tasks", self.correct_tasks)
        add("Incorrect tasks", self.incorrect_tasks)

        if self.last_task_result:
            add("Last task result", self.last_task_result)

        # Ремедиация
        add("Needs remediation", self.needs_remediation)

        if self.remediation_reason:
            add("Remediation reason", self.remediation_reason)

        if self.next_lesson_id:
            add("Next lesson ID", self.next_lesson_id)

        add("Next lesson is remedial", self.next_lesson_is_remedial)

        # Адаптивные параметры (как есть, без интерпретации)
        if self.adaptive_parameters:
            add("Adaptive parameters", self.adaptive_parameters)

        return "\n".join(lines)
