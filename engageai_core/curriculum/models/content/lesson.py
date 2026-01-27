from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from curriculum.models.content.course import Course
from curriculum.models.systematization.learning_objective import LearningObjective

from curriculum.validators import validate_skill_focus
from users.models import CEFRLevel


class Lesson(models.Model):
    """
    Урок — логическая единица внутри курса (например, "Listening: Stand-up Meetings").

    Назначение:
    - Соответствует одному из 8 блоков диагностики или теме в обучении.
    - Содержит задания (Tasks).

    Поля:
    - duration_minutes: сколько времени займёт
    - skill_focus: навыки, на которые направлен (["listening", "vocabulary"])
    - adaptive_parameters: правила адаптации (например, пороги для усложнения)
    """
    objects = models.Manager()

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='lessons', verbose_name=_("Course"))
    title = models.CharField(max_length=200, verbose_name=_("Title"))
    description = models.TextField(verbose_name=_("Description"))
    order = models.PositiveIntegerField(verbose_name=_("Order"))
    content = models.TextField(verbose_name=_("Content"),
                               help_text=_("Optional structured lesson instructions or narrative for AI"))
    content_ru = models.TextField(verbose_name=_("Content"),
                               help_text=_("Field 'content' in Russian lang"), blank=True)
    theory_content = models.TextField(verbose_name=_("Theory Content"), blank=True,
                                      help_text=_("HTML content with theory and explanations"))
    duration_minutes = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(120)],
                                                   verbose_name=_("Duration (minutes)"))
    required_cefr = models.CharField(max_length=2, choices=CEFRLevel, verbose_name=_("Required CEFR"))
    learning_objectives = models.ManyToManyField(LearningObjective, verbose_name=_("Learning Objectives"))
    skill_focus = models.JSONField(default=list, validators=[validate_skill_focus], verbose_name=_("Skill Focus"),
                                   help_text=_("e.g., ['listening', 'vocabulary']")
                                   )
    adaptive_parameters = models.JSONField(default=dict, verbose_name=_("Adaptive Parameters"),
                                           help_text=_("e.g., {'min_correct_ratio': 0.7, 'max_items': 10}")
                                           )
    is_remedial = models.BooleanField(verbose_name="дополнительные, корректирующие уроки", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, verbose_name=_("Is Active"))

    class Meta:
        verbose_name = _("Lesson")
        verbose_name_plural = _("Lessons")
        ordering = ['course', 'order']
        indexes = [models.Index(fields=['course', 'order'])]

    def __str__(self):
        return f"{self.course.title} → {self.title}"
