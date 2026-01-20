from django.db import models
from django.utils.translation import gettext_lazy as _

from curriculum.models.systematization.learning_objective import LearningObjective
from users.models import CEFRLevel


class Course(models.Model):
    """
    Учебный курс — структурированная последовательность уроков.
    Может быть диагностическим (is_diagnostic=True) или обучающим.

    Назначение:
    - Диагностический курс: содержит 8 блоков из плана.
    - Обучающий курс: тематический путь (например, "English for Backend Engineers").

    Поля:
    - title: название курса
    - target_cefr_from/to: диапазон CEFR
    - estimated_duration: общая длительность в минутах
    - learning_objectives: цели, которые покрывает курс
    - required_skills: список навыков/уровней, необходимых для старта (JSON)
    """
    objects = models.Manager()

    title = models.CharField(max_length=200, verbose_name=_("Title"))
    description = models.TextField(verbose_name=_("Description"))
    target_cefr_from = models.CharField(max_length=2, choices=CEFRLevel, verbose_name=_("From CEFR"))
    target_cefr_to = models.CharField(max_length=2, choices=CEFRLevel, verbose_name=_("To CEFR"))
    estimated_duration = models.PositiveIntegerField(
        verbose_name=_("Estimated Duration (minutes)"),
        help_text=_("Total estimated time to complete the course")
    )
    learning_objectives = models.ManyToManyField(LearningObjective, verbose_name=_("Learning Objectives"))
    required_skills = models.JSONField(
        default=list,
        verbose_name=_("Required Skills"),
        help_text=_("e.g., ['grammar:B1', 'listening:A2']")
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, verbose_name=_("Is Active"))

    class Meta:
        verbose_name = _("Course")
        verbose_name_plural = _("Courses")

    def __str__(self):
        return f"{self.title} ({self.get_target_cefr_from_display()} → {self.get_target_cefr_to_display()})"
