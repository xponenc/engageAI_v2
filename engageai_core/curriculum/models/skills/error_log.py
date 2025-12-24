from django.db import models
from django.utils.translation import gettext_lazy as _

from curriculum.models.content.task import Task
from users.models import Student


class ErrorLog(models.Model):
    """
    Журнал типичных ошибок — для цели №3: «Выявить типичные ошибки».

    Назначение:
    - Формирует Error Profile студента.
    - Используется для рекомендаций и подбора практики.

    Примеры:
    - error_type: "tense"
    - example: "I have went to the meeting"
    - correction: "I went to the meeting"
    """
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name=_("Student"))
    error_type = models.CharField(max_length=30, verbose_name=_("Error Type"))
    example = models.TextField(verbose_name=_("Example"))
    correction = models.TextField(blank=True, verbose_name=_("Correction"))
    context_task = models.ForeignKey(Task, on_delete=models.SET_NULL, null=True, blank=True,
                                     verbose_name=_("Context Task"))
    detected_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Detected At"))
    resolved = models.BooleanField(default=False, verbose_name=_("Resolved"))

    class Meta:
        verbose_name = _("Error Log")
        verbose_name_plural = _("Error Logs")
        indexes = [
            models.Index(fields=['student']),
            models.Index(fields=['error_type']),
            models.Index(fields=['resolved']),
        ]

    def __str__(self):
        return f"{self.error_type} — {self.student}"