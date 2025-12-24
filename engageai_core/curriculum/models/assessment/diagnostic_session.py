from django.db import models
from django.utils.translation import gettext_lazy as _

from users.models import CEFRLevel, Student


class DiagnosticSession(models.Model):
    """
    Сессия адаптивной диагностики — охватывает все 8 блоков.

    Назначение:
    - Связывает студента, его ответы, итоговый уровень и профиль.
    - Используется для аналитики и повторной диагностики.
    """
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name=_("Student"))
    started_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Started At"))
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Completed At"))
    final_cefr = models.CharField(max_length=2, choices=CEFRLevel, null=True, blank=True,
                                  verbose_name=_("Final CEFR"))
    skill_profile = models.ForeignKey("CurrentSkillProfile", on_delete=models.SET_NULL, null=True, blank=True,
                                      verbose_name=_("Skill Profile"))

    class Meta:
        verbose_name = _("Diagnostic Session")
        verbose_name_plural = _("Diagnostic Sessions")
        indexes = [
            models.Index(fields=['student']),
            models.Index(fields=['completed_at']),
        ]

    def __str__(self):
        return f"Diagnostic for {self.student} ({self.final_cefr or 'in skills'})"