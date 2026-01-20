from django.db import models

from curriculum.validators import SkillDomain
from users.models import Student


class CurrentSkill(models.Model):
    """
    Текущее состояние конкретного навыка студента.

    Используется для:
    - адаптивных решений
    - выбора сложности
    - маршрутизации по курсу
    """
    objects = models.Manager()

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="current_skills"
    )

    skill = models.CharField(
        max_length=32,
        choices=SkillDomain.choices
    )

    score = models.FloatField(default=0.0)
    confidence = models.FloatField(default=0.0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("student", "skill")
