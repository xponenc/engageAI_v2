# curriculum/models/content/learning_plan.py
from django.db import models
from django.core.exceptions import ValidationError
from curriculum.models.content.course import Course


class MethodologicalPlan(models.Model):
    """
    Кэш методологического плана для курса + состояние генерации.
    Позволяет восстановить генерацию после сбоев.
    """
    course = models.OneToOneField(
        Course,
        on_delete=models.CASCADE,
        related_name='learning_plan'
    )

    # Методплан
    plan_data = models.JSONField()  # Полная структура {level: {skill: [units]}}
    total_units = models.PositiveIntegerField()
    generated_units = models.PositiveIntegerField(default=0)

    # Статистика
    levels = models.JSONField(default=dict)  # {level: unit_count}
    skills = models.JSONField(default=dict)  # {skill: unit_count}

    # Состояние
    is_complete = models.BooleanField(default=False)
    last_lesson_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Learning plan"
        verbose_name_plural = "Learning plans"

    def clean(self):
        if self.total_units > 0 and self.generated_units > self.total_units:
            raise ValidationError("Generated units cannot exceed total")

    def __str__(self):
        return f"LearningPlan({self.course.title}): {self.generated_units}/{self.total_units}"
