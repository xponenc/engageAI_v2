from django.db import models
from django.utils.translation import gettext_lazy as _


class ProfessionalTag(models.Model):
    """
    Профессиональный тег — обозначает сферу или тип задач, релевантных заданию.
    Примеры: "backend", "qa", "incident-response", "technical-writing".

    Назначение:
    - Позволяет персонализировать диагностику и обучение под роль студента (из мини-анкеты).
    - Используется для фильтрации заданий по релевантности.

    Примеры наполнения:
    - "backend"
    - "qa"
    - "devops"
    - "product-interviews"
    - "api-documentation"
    - "standup-meetings"
    - "ticket-writing"

    Рекомендация:
    - Теги создаются кураторами/методистами.
    - Студент выбирает 1–3 тега при регистрации или в мини-анкете.
    """
    name = models.CharField(
        max_length=50,
        unique=True,
        verbose_name=_("Tag Name"),
        help_text=_("Short, machine-readable name (e.g., 'backend', 'standup-meetings')")
    )
    description = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("Description"),
        help_text=_("Human-readable explanation for admins")
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Is Active"))

    class Meta:
        verbose_name = _("Professional Tag")
        verbose_name_plural = _("Professional Tags")
        indexes = [models.Index(fields=['name'])]

    def __str__(self):
        return self.name
