from typing import Optional

from ai.agents.assessor_agent import AutoAssessor
from curriculum.models import Task, StudentTaskResponse, Student, Enrollment, Lesson


class LearningAgent:
    """
    MVP agent.
    Controls linear learning flow:
    Course → Lesson → Task → Response → Assessment → Next Action
    """

    def __init__(self, student: Student):
        self.student = student
        self.enrollment = self._get_enrollment()

    def _get_enrollment(self) -> Enrollment:
        enrollment = Enrollment.objects.filter(
            student=self.student,
            is_active=True
        ).select_related("course", "current_lesson").first()

        if not enrollment:
            raise RuntimeError("Student is not enrolled in any course")

        return enrollment

    def get_current_lesson(self) -> Optional[Lesson]:
        return self.enrollment.current_lesson

    def get_next_task(self) -> Optional[Task]:
        lesson = self.get_current_lesson()
        if not lesson:
            return None

        completed_task_ids = StudentTaskResponse.objects.filter(
            student=self.student,
            task__lesson=lesson
        ).values_list("task_id", flat=True)

        next_task = Task.objects.filter(
            lesson=lesson
        ).exclude(
            id__in=completed_task_ids
        ).order_by("order").first()

        return next_task

    def submit_task_response(self, task: Task, response_data: dict):
        response = StudentTaskResponse.objects.create(
            student=self.student,
            task=task,
            response_text=response_data.get("response_text", ""),
            audio_file=response_data.get("audio_file"),
        )

        if task.response_format in ("single_choice", "multiple_choice", "short_text"):
            assessor = AutoAssessor()
            response.is_correct = assessor.assess(task, response)
            response.save(update_fields=["is_correct"])

        return response

    def is_lesson_completed(self) -> bool:
        lesson = self.get_current_lesson()
        if not lesson:
            return False

        total_tasks = Task.objects.filter(lesson=lesson).count()
        completed = StudentTaskResponse.objects.filter(
            student=self.student,
            task__lesson=lesson
        ).count()

        return completed >= total_tasks

    def advance_lesson(self) -> Optional[Lesson]:
        current = self.get_current_lesson()

        next_lesson = Lesson.objects.filter(
            course=self.enrollment.course,
            order__gt=current.order
        ).order_by("order").first()

        self.enrollment.current_lesson = next_lesson
        self.enrollment.save(update_fields=["current_lesson"])

        return next_lesson

    def next_action(self):
        """
        Returns:
        - Task → show task
        - None → lesson or course completed
        """

        task = self.get_next_task()
        if task:
            return task

        if self.is_lesson_completed():
            next_lesson = self.advance_lesson()
            if next_lesson:
                return self.get_next_task()

        return None
