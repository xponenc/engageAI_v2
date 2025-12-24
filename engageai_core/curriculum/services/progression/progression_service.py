from dataclasses import dataclass
from typing import Optional

from django.db.models import OuterRef
from sqlalchemy import Exists

from curriculum.models import Task, StudentTaskResponse
from curriculum.models.student.enrollment import Enrollment
from curriculum.services.curriculum_query import CurriculumQueryService
from curriculum.services.decisions.decision_service import Decision


@dataclass
class ProgressionResult:
    """
    Результат применения решения к Enrollment.

    Используется:
    - LearningService
    - Orchestrator
    """

    next_action: str
    next_task_id: Optional[int] = None
    next_lesson_id: Optional[int] = None


class ProgressionService:
    """
    ProgressionService применяет решение к состоянию Enrollment.

    Он:
    - НЕ принимает решений
    - НЕ анализирует данные
    - только обновляет состояние

    TODO (ProgressionService):

    1. Поддержка branching lessons
    2. Partial lesson completion
    3. Rollback progression (teacher override)
    4. Soft reset vs hard reset lesson
    """

    def __init__(
        self,
        curriculum_query: CurriculumQueryService | None = None,
    ):
        self.curriculum_query = curriculum_query or CurriculumQueryService()

    def apply_decision(
        self,
        enrollment: Enrollment,
        decision: Decision,
    ) -> ProgressionResult:
        """
        Применяет decision к Enrollment.

        Возможные сценарии:
        - ADVANCE_TASK
        - ADVANCE_LESSON
        - REPEAT_TASK
        - REPEAT_LESSON
        - STOP
        """

        if decision.code == "ADVANCE_TASK":
            return self._advance_task(enrollment)

        if decision.code == "ADVANCE_LESSON":
            return self._advance_lesson(enrollment)

        if decision.code == "REPEAT_TASK":
            return self._repeat_task(enrollment)

        if decision.code == "REPEAT_LESSON":
            return self._repeat_lesson(enrollment)

        if decision.code == "STOP":
            return ProgressionResult(
                next_action="STOP"
            )

        raise ValueError(f"Unknown decision code: {decision.code}")

    # ------------------------------------------------------------------
    # Decision handlers
    # ------------------------------------------------------------------

    def _advance_task(self, enrollment: Enrollment) -> ProgressionResult:
        """
        Переход к следующему заданию в рамках текущего урока.
        """

        next_task = self.curriculum_query.get_next_task(enrollment)

        if not next_task:
            # Задания закончились → пусть decision engine решает дальше
            return ProgressionResult(
                next_action="NO_MORE_TASKS"
            )

        return ProgressionResult(
            next_action="NEXT_TASK",
            next_task_id=next_task.pk,
        )

    def _advance_lesson(self, enrollment: Enrollment) -> ProgressionResult:
        """
        Переход к следующему уроку курса.
        """

        current_lesson = enrollment.current_lesson

        next_lesson = (
            current_lesson.course.lessons
            .filter(order__gt=current_lesson.order, is_active=True)
            .order_by("order")
            .first()
        )

        if not next_lesson:
            enrollment.is_completed = True
            enrollment.save(update_fields=["is_completed"])

            return ProgressionResult(
                next_action="COURSE_COMPLETED"
            )

        enrollment.current_lesson = next_lesson
        enrollment.save(update_fields=["current_lesson", ])

        first_task = self.curriculum_query.get_first_task(next_lesson)

        return ProgressionResult(
            next_action="NEXT_LESSON",
            next_lesson_id=next_lesson.id,
            next_task_id=first_task.pk if first_task else None,
        )

    def _repeat_task(self, enrollment: Enrollment) -> ProgressionResult:
        """
        Повтор текущего задания.
        """

        student_responses = StudentTaskResponse.objects.filter(
            student=enrollment.student,
            task=OuterRef('pk'),
        )
        current_task = (
            Task.objects
            .filter(
                lesson=enrollment.current_lesson,
                is_active=True,
            )
            .annotate(
                has_response=Exists(student_responses)
            )
            .filter(has_response=False)
            .order_by('order')
            .first()
        )

        return ProgressionResult(
            next_action="RETRY_TASK",
            next_task_id=current_task.pk,
        )

    def _repeat_lesson(self, enrollment: Enrollment) -> ProgressionResult:
        """
        Повтор текущего урока (сброс task).
        """

        first_task = self.curriculum_query.get_next_task(
            enrollment.current_lesson
        )

        return ProgressionResult(
            next_action="RESTART_LESSON",
            next_task_id=first_task.pk if first_task else None,
        )
