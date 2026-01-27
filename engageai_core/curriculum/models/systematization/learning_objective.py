from django.db import models
from django.utils.translation import gettext_lazy as _

from users.models import CEFRLevel


class LearningObjective(models.Model):
    """
    Учебная цель — педагогически сформулированное умение, которое должен развить студент.

    Вместо ручного кода (например, "B1-G-01") используется структурированное описание:
    - CEFR-уровень,
    - область навыка (грамматика, лексика и т.д.),
    - порядковый номер в рамках уровня и области.

    Идентификатор (`identifier`) генерируется автоматически и гарантирует уникальность.

    Примеры:
    - "Use Past Simple and Present Perfect correctly in work contexts" → grammar, B1, order=1 → identifier="grammar-B1-01"
    - "Understand technical stand-up meetings" → listening, B1, order=1 → identifier="listening-B1-01"
    """

    # === Структурированные поля ===
    cefr_level = models.CharField(
        max_length=2,
        choices=CEFRLevel,
        verbose_name=_("CEFR Level"),
        help_text=_("Уровень CEFR, на котором эта цель актуальна")
    )
    skill_domain = models.CharField(
        max_length=20,
        choices=[
            ('grammar', _('Grammar')),
            ('vocabulary', _('Vocabulary')),
            ('listening', _('Listening')),
            ('reading', _('Reading')),
            ('writing', _('Writing')),
            ('speaking', _('Speaking')),
        ],
        verbose_name=_("Skill Domain"),
        help_text=_("Область языкового навыка")
    )
    order_in_level = models.PositiveSmallIntegerField(
        default=1,
        verbose_name=_("Order within level and domain"),
        help_text=_("Порядковый номер цели в рамках уровня и области (для сортировки)")
    )

    # === Человекочитаемые поля ===
    name = models.CharField(
        max_length=200,
        verbose_name=_("Name"),
        help_text=_("Clear, actionable objective — e.g., 'Use Past Simple correctly in work emails'")
    )
    description = models.TextField(
        blank=True,
        verbose_name=_("Description"),
        help_text=_("Optional detailed explanation for methodologists")
    )

    # === Автоматически генерируемый идентификатор (для API, логики, LLM) ===
    identifier = models.SlugField(
        max_length=50,
        unique=True,
        editable=False,
        verbose_name=_("Machine Identifier"),
        help_text=_("Auto-generated unique ID like 'grammar-B1-01'")
    )

    # === Служебные поля ===
    is_active = models.BooleanField(default=True, verbose_name=_("Is Active"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Learning Objective")
        verbose_name_plural = _("Learning Objectives")
        unique_together = [
            ['cefr_level', 'skill_domain', 'order_in_level']
        ]
        ordering = ['cefr_level', 'skill_domain', 'order_in_level']
        indexes = [
            models.Index(fields=['cefr_level', 'skill_domain']),
            models.Index(fields=['identifier']),
        ]

    def save(self, *args, **kwargs):
        # Генерируем идентификатор вида: grammar-B1-01
        self.identifier = f"{self.skill_domain}-{self.cefr_level}-{self.order_in_level:02d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"[{self.identifier}] {self.name}"