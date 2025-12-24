from django.db import models

from curriculum.models.assessment.assessment import Assessment
from curriculum.models.content.lesson import Lesson
from curriculum.models.content.task import Task
from curriculum.models.skills.skill_snapshot import SkillSnapshot
from curriculum.models.student.enrollment import Enrollment


class LessonTransition(models.Model):
    """
    LessonTransition — неизменяемый факт перехода в учебном процессе.

    Создаётся TransitionRecorder.
    Используется:
    - explainability
    - аналитикой
    - отладкой решений
    """
    objects = models.Manager()

    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.CASCADE,
        related_name="lesson_transitions",
    )

    from_lesson = models.ForeignKey(
        Lesson,
        on_delete=models.PROTECT,
        related_name="outgoing_transitions",
    )

    to_lesson = models.ForeignKey(
        Lesson,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="incoming_transitions",
    )

    task = models.ForeignKey(
        Task,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lesson_transitions",
        help_text="Task, на основании которого было принято решение (если применимо)",
    )

    assessment = models.ForeignKey(
        Assessment,
        on_delete=models.PROTECT,
        related_name="lesson_transitions",
    )

    skill_snapshot = models.ForeignKey(
        SkillSnapshot,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lesson_transitions",
    )

    decision_code = models.CharField(
        max_length=128,
        help_text="Код решения decision engine (advance, repeat, remedial, etc.)",
    )

    teacher_override = models.BooleanField(
        default=False,
        help_text="Было ли решение переопределено преподавателем",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return (
            f"LessonTransition("
            f"enrollment={self.enrollment_id}, "
            f"{self.from_lesson_id} → {self.to_lesson_id}, "
            f"decision={self.decision_code}"
            f")"
        )

    # --- DOMAIN CONTRACT ---
    # ПИШЕТ:
    #   - TransitionRecorder
    #
    # ЧИТАЕТ:
    #   - LessonExplainer
    #   - ExplainabilityEngine
    #   - Analytics / Admin
    #
    # ИНВАРИАНТЫ:
    #   - объект НЕ редактируется после создания
    #   - assessment всегда есть
    #   - decision_code обязателен
