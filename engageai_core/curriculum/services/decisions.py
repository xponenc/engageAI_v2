from .metrics import LessonMetrics
from curriculum.models import Lesson
from enum import Enum


class LessonOutcome(Enum):
    ADVANCE = "advance"
    REPEAT = "repeat"
    SIMPLIFY = "simplify"
    BRANCH = "branch"


class AdaptiveDecisionEngine:
    """
    Decides what to do after a lesson based on metrics and adaptive parameters.
    """

    def decide(self, lesson: Lesson, metrics: LessonMetrics) -> LessonOutcome:
        params = lesson.adaptive_parameters or {}

        min_ratio = params.get("min_correct_ratio", 0.7)
        retry = params.get("retry_on_fail", True)

        # 1. урок не завершён
        if metrics.completion_ratio < 1.0:
            return LessonOutcome.REPEAT

        # 2. есть незакрытые open tasks → ждём оценки
        if metrics.has_open_tasks:
            return LessonOutcome.REPEAT

        # 3. успешно
        if metrics.success_ratio >= min_ratio:
            return LessonOutcome.ADVANCE

        # 4. неуспешно
        if retry:
            return LessonOutcome.SIMPLIFY

        return LessonOutcome.BRANCH
