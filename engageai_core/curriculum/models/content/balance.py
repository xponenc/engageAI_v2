from django.core.exceptions import ValidationError
from django.db import models

from curriculum.models.content.course import Course

DEFAULT_COURSE_BALANCE = {
    "levels": {
        "A2": 0.25,
        "B1": 0.30,
        "B2": 0.25,
        "C1": 0.15,
        "C2": 0.05,
    },
    "skills": {
        "grammar": 0.2,
        "vocabulary": 0.2,
        "reading": 0.15,
        "listening": 0.15,
        "writing": 0.15,
        "speaking": 0.15,
    },
    "total_lessons": 60
}


class CourseBalance(models.Model):
    """
    Контракт баланса базовой генерации курса.
    """
    course = models.OneToOneField(Course, on_delete=models.CASCADE)

    total_lessons = models.PositiveIntegerField(default=120)

    level_distribution = models.JSONField(
        default=dict,
        help_text="Процентное распределение уровней"
    )

    skill_distribution = models.JSONField(
        default=dict,
        help_text="Баланс навыков"
    )

    frozen = models.BooleanField(
        default=True,
        help_text="Запрещает изменение после инициализации"
    )

    class Meta:
        verbose_name = "Course balance"
        verbose_name_plural = "Course balances"

    def clean(self):
        if self.frozen and self.pk:
            raise ValidationError("Frozen CourseBalance cannot be modified")

    def __str__(self):
        return f"CourseBalance<{self.code}>"
