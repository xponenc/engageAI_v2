from django.db import models
from django.utils.translation import gettext_lazy as _

from curriculum.models.content.lesson import Lesson
from users.models import Teacher, Student


class TeacherOverride(models.Model):
    """
    Ручное вмешательство преподавателя в решение системы.

    Назначение:
    - Фиксирует факт переопределения
    - Хранит причину
    - Используется для аналитики и обучения системы
    """

    objects = models.Manager()

    teacher = models.ForeignKey(
        Teacher,
        on_delete=models.CASCADE,
        related_name="overrides"
    )

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="teacher_overrides"
    )

    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE
    )

    original_decision = models.CharField(
        max_length=32
    )

    overridden_decision = models.CharField(
        max_length=32
    )

    reason = models.TextField(
        help_text="Объяснение преподавателя"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Teacher Override"
        verbose_name_plural = "Teacher Overrides"
        indexes = [
            models.Index(fields=["student"]),
            models.Index(fields=["lesson"]),
        ]

    def __str__(self):
        return (
            f"{self.teacher} override "
            f"{self.original_decision} → {self.overridden_decision}"
        )
