# engageai_core/learning/metrics.py

from dataclasses import dataclass

from curriculum.models import (
    Lesson,
    Task,
    StudentTaskResponse,
    Student
)


@dataclass
class LessonMetrics:
    success_ratio: float
    completion_ratio: float
    has_open_tasks: bool


class LessonMetricsCalculator:
    """
    Calculates objective metrics for a lesson.
    """

    CLOSED_FORMATS = {
        "single_choice",
        "multiple_choice",
        "short_text",
    }

    OPEN_FORMATS = {
        "free_text",
        "audio",
    }

    def calculate(self, student: Student, lesson: Lesson) -> LessonMetrics:
        tasks = Task.objects.filter(lesson=lesson)
        total_tasks = tasks.count()

        if total_tasks == 0:
            return LessonMetrics(
                success_ratio=0.0,
                completion_ratio=0.0,
                has_open_tasks=False
            )

        responses = StudentTaskResponse.objects.filter(
            student=student,
            task__lesson=lesson
        )

        completed_tasks = responses.count()
        completion_ratio = completed_tasks / total_tasks

        # --- closed tasks ---
        closed_tasks = tasks.filter(
            response_format__in=self.CLOSED_FORMATS
        )

        closed_task_ids = closed_tasks.values_list("id", flat=True)

        closed_responses = responses.filter(
            task_id__in=closed_task_ids,
            is_correct__isnull=False
        )

        correct_closed = closed_responses.filter(is_correct=True).count()
        total_closed = closed_tasks.count()

        success_ratio = (
            correct_closed / total_closed
            if total_closed > 0 else 1.0
        )

        # --- open tasks ---
        has_open_tasks = tasks.filter(
            response_format__in=self.OPEN_FORMATS
        ).exists()

        return LessonMetrics(
            success_ratio=round(success_ratio, 2),
            completion_ratio=round(completion_ratio, 2),
            has_open_tasks=has_open_tasks
        )
