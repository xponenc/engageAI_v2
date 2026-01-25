from django.db import models
from django.utils.translation import gettext_lazy as _


class Course(models.Model):
    """
    Учебный курс — структурированная последовательность уроков.
    Может быть диагностическим (is_diagnostic=True) или обучающим.

    Назначение:
    - Диагностический курс: содержит 8 блоков из плана.
    - Обучающий курс: тематический путь (например, "English for Backend Engineers").

    Поля:
    - title: название курса
    - estimated_duration: общая длительность в минутах
    - learning_objectives: цели, которые покрывает курс
    - required_skills: список навыков/уровней, необходимых для старта (JSON)
    """
    objects = models.Manager()

    title = models.CharField(max_length=200, verbose_name=_("Title"))
    description = models.TextField(verbose_name=_("Description"))
    professional_tags = models.ManyToManyField(
        "curriculum.ProfessionalTag",
        blank=True,
        verbose_name=_("Professional Tags"),
        help_text=_("Теги профессий, для которых курс релевантен (e.g., 'backend', 'qa')")
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, verbose_name=_("Is Active"))

    class Meta:
        verbose_name = _("Course")
        verbose_name_plural = _("Courses")

    def __str__(self):
        return f"{self.title}"
