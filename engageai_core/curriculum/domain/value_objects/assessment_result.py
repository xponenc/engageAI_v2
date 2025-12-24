from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from enum import Enum


class AssessmentGrade(Enum):
    EXCELLENT = "excellent"  # 90-100%
    GOOD = "good"  # 70-89%
    SATISFACTORY = "satisfactory"  # 50-69%
    POOR = "poor"  # <50%


@dataclass(frozen=True)
class AssessmentResult:
    """
    Чистый доменный объект результата оценки.
    Не зависит от Django или базы данных!
    """
    score: float  # 0.0 - 1.0
    is_correct: Optional[bool] = None  # None для открытых заданий
    grade: AssessmentGrade = AssessmentGrade.POOR
    error_tags: List[str] = None
    feedback: Dict[str, Any] = None
    confidence: float = 1.0  # Для LLM-оценок

    def __post_init__(self):
        # Автоматический расчет grade на основе score
        object.__setattr__(self, 'grade', self._calculate_grade())

        # Защита от некорректных значений
        if not (0.0 <= self.score <= 1.0):
            raise ValueError("Score must be between 0.0 and 1.0")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("Confidence must be between 0.0 and 1.0")

        # Инициализация пустых списков/словарей
        if self.error_tags is None:
            object.__setattr__(self, 'error_tags', [])
        if self.feedback is None:
            object.__setattr__(self, 'feedback', {})

    def _calculate_grade(self) -> AssessmentGrade:
        if self.score >= 0.9:
            return AssessmentGrade.EXCELLENT
        elif self.score >= 0.7:
            return AssessmentGrade.GOOD
        elif self.score >= 0.5:
            return AssessmentGrade.SATISFACTORY
        return AssessmentGrade.POOR

    def to_persistence_dict(self) -> dict:
        """Конвертация в формат для сохранения в Django-модель"""
        return {
            'score': self.score,
            'is_correct': self.is_correct,
            'grade': self.grade.value,
            'error_tags': self.error_tags,
            'feedback': self.feedback,
            'confidence': self.confidence
        }