from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.serializers.json import DjangoJSONEncoder


class LessonTransition(models.Model):
    """
    Фиксация факта перехода между уроками/заданиями.

    Поддерживает два типа переходов:
    1. TASK_LEVEL - переход между заданиями в уроке
    2. LESSON_LEVEL - переход между уроками

    Инварианты:
    - transition_type неизменяем после создания
    - для TASK_LEVEL обязательно task_id
    - для LESSON_LEVEL обязательно skill_snapshot_id
    """

    TRANSITION_TYPES = [
        ('TASK_LEVEL', _('Task Level Transition')),
        ('LESSON_LEVEL', _('Lesson Level Transition')),
    ]

    enrollment = models.ForeignKey(
        "Enrollment",
        on_delete=models.CASCADE,
        related_name='transitions'
    )

    from_lesson = models.ForeignKey(
        "Lesson",
        on_delete=models.PROTECT,
        related_name='+'
    )

    to_lesson = models.ForeignKey(
        "Lesson",
        on_delete=models.PROTECT,
        related_name='+'
    )

    task = models.ForeignKey(
        "Task",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transitions'
    )

    decision_code = models.CharField(max_length=32)
    decision_confidence = models.FloatField(default=0.0)
    decision_rationale = models.JSONField(encoder=DjangoJSONEncoder, default=dict)

    assessment = models.ForeignKey(
        "Assessment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transitions'
    )

    skill_snapshot = models.ForeignKey(
        "SkillSnapshot",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transitions'
    )

    skill_trajectory = models.ForeignKey(
        "SkillTrajectory",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transitions'
    )

    teacher_override = models.BooleanField(default=False)
    teacher_override_id = models.BigIntegerField(null=True, blank=True)
    override_reason = models.TextField(null=True, blank=True)

    transition_type = models.CharField(
        max_length=20,
        choices=TRANSITION_TYPES,
        default='TASK_LEVEL'
    )

    transition_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Lesson Transition')
        verbose_name_plural = _('Lesson Transitions')
        indexes = [
            models.Index(fields=['enrollment', 'transition_at']),
            models.Index(fields=['from_lesson', 'to_lesson']),
            models.Index(fields=['transition_type']),
            models.Index(fields=['teacher_override']),
        ]

    def __str__(self):
        return (
            f"Transition {self.id}: "
            f"{self.from_lesson} → {self.to_lesson} "
            f"({self.decision_code})"
        )

    def clean(self):
        """
        Валидация инвариантов перед сохранением.
        """
        if self.transition_type == 'TASK_LEVEL' and not self.task:
            raise ValueError("Task is required for TASK_LEVEL transitions")

        if self.transition_type == 'LESSON_LEVEL' and not self.skill_snapshot:
            raise ValueError("Skill snapshot is required for LESSON_LEVEL transitions")