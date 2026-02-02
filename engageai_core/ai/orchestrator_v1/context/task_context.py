from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class TaskContext:
    """
    Пассивный контейнер данных о задаче.

    Правила:
    - НЕ содержит методов доступа к БД
    - НЕ содержит бизнес-логики
    - ТОЛЬКО хранит данные и предоставляет методы сериализации
    """

    # Основная информация о задаче
    task_id: int
    task_title: Optional[str]
    task_type: str  # "grammar", "vocabulary", "reading", "listening", "writing", "speaking"
    response_format: str  # "single_choice", "multiple_choice", "short_text", "free_text", "audio"
    difficulty_cefr: str  # "A1", "A2", "B1", "B2", "C1", "C2"

    # Справочная информация об уроке (для персонализации)
    lesson_id: int
    lesson_title: str
    lesson_type: str  # "grammar", "vocabulary", "professional_scenario" и т.д.
    course_id: int
    course_title: str
    lesson_cefr_level: str
    lesson_professional_tags: List[str]  # ["backend", "data_science", "marketing"]
    lesson_skill_focus: List[str]  # ["grammar", "vocabulary", "speaking"]

    # Состояние задачи
    task_state: str  # "NOT_STARTED", "IN_PROGRESS", "COMPLETED", "FAILED"
    is_completed: bool
    is_correct: Optional[bool]  # None = не оценено
    score: Optional[float]  # 0.0 - 1.0
    attempts_count: int

    # Оценка и фидбэк (только данные, без логики)
    last_feedback: Optional[str]
    common_errors: List[str]  # Паттерны ошибок из фидбэка
    improvement_suggestions: List[str]  # Рекомендации из фидбэка

    # Контекст для агентов
    content_schema: str  # "scq_v1", "mcq_v1", "short_text_v1" и т.д.
    professional_context: str  # Строковое представление профессионального контекста
    learning_objectives: List[str]  # Цели обучения задачи

    # Метаданные
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """
        Сериализация для передачи в агенты.

        Возвращает структурированный словарь с полным контекстом задачи.
        """
        return {
            "task": {
                "id": self.task_id,
                "title": self.task_title,
                "type": self.task_type,
                "response_format": self.response_format,
                "difficulty": self.difficulty_cefr,
                "state": self.task_state,
                "completed": self.is_completed,
                "correct": self.is_correct,
                "score": self.score,
                "attempts": self.attempts_count,
            },
            "lesson": {
                "id": self.lesson_id,
                "title": self.lesson_title,
                "type": self.lesson_type,
                "course_id": self.course_id,
                "course_title": self.course_title,
                "cefr_level": self.lesson_cefr_level,
                "professional_tags": self.lesson_professional_tags,
                "skill_focus": self.lesson_skill_focus,
            },
            "assessment": {
                "feedback": self.last_feedback,
                "errors": self.common_errors,
                "suggestions": self.improvement_suggestions,
            },
            "context": {
                "content_schema": self.content_schema,
                "professional_context": self.professional_context,
                "learning_objectives": self.learning_objectives,
            },
            "metadata": self.metadata,
        }

    def to_prompt(self) -> str:
        """
        Преобразует TaskContext в человеко-читаемый промпт для LLM.

        Правила:
        - Включает только непустые поля
        - Значения 0 / 0.0 / False считаются валидными и включаются
        - Формат — структурированный текст, удобный для LLM
        """

        def is_present(value: Any) -> bool:
            """
            Определяет, нужно ли включать поле в промпт.
            None, пустые строки, пустые списки и словари — исключаются.
            """
            if value is None:
                return False
            if isinstance(value, str) and value.strip() == "":
                return False
            if isinstance(value, (list, dict)) and len(value) == 0:
                return False
            return True

        lines: List[str] = []

        # --- Task ---
        lines.append("TASK")
        task_fields = {
            "ID": self.task_id,
            "Title": self.task_title,
            "Type": self.task_type,
            "Response format": self.response_format,
            "Difficulty (CEFR)": self.difficulty_cefr,
            "State": self.task_state,
            "Completed": self.is_completed,
            "Correct": self.is_correct,
            "Score": self.score,
            "Attempts count": self.attempts_count,
        }

        for label, value in task_fields.items():
            if is_present(value):
                lines.append(f"- {label}: {value}")

        # --- Lesson ---
        lines.append("\nLESSON")
        lesson_fields = {
            "Lesson ID": self.lesson_id,
            "Lesson title": self.lesson_title,
            "Lesson type": self.lesson_type,
            "Course ID": self.course_id,
            "Course title": self.course_title,
            "Lesson CEFR level": self.lesson_cefr_level,
            "Professional tags": ", ".join(self.lesson_professional_tags),
            "Skill focus": ", ".join(self.lesson_skill_focus),
        }

        for label, value in lesson_fields.items():
            if is_present(value):
                lines.append(f"- {label}: {value}")

        # --- Assessment ---
        if any(
                is_present(v)
                for v in (
                        self.last_feedback,
                        self.common_errors,
                        self.improvement_suggestions,
                )
        ):
            lines.append("\nASSESSMENT")

            if is_present(self.last_feedback):
                lines.append(f"- Feedback: {self.last_feedback}")

            if is_present(self.common_errors):
                lines.append("- Common errors:")
                for error in self.common_errors:
                    lines.append(f"  • {error}")

            if is_present(self.improvement_suggestions):
                lines.append("- Improvement suggestions:")
                for suggestion in self.improvement_suggestions:
                    lines.append(f"  • {suggestion}")

        # --- Context ---
        lines.append("\nCONTEXT")
        context_fields = {
            "Content schema": self.content_schema,
            "Professional context": self.professional_context,
            "Learning objectives": "; ".join(self.learning_objectives),
        }

        for label, value in context_fields.items():
            if is_present(value):
                lines.append(f"- {label}: {value}")

        # --- Metadata ---
        if is_present(self.metadata):
            lines.append("\nMETADATA")
            for key, value in self.metadata.items():
                if is_present(value):
                    lines.append(f"- {key}: {value}")

        return "\n".join(lines)

