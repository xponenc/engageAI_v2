from django.db import models
from django.utils.translation import gettext_lazy as _

from curriculum.models.assessment.student_response import StudentTaskResponse


class Assessment(models.Model):
    """
    Результат оценки LLM для открытого задания.

    Назначение:
    - Хранит структурированную обратную связь по writing/speaking.
    - Используется для обновления SkillProfile и ErrorLog.

    Поля:
    - raw_output: полный ответ LLM (для аудита)
    - structured_feedback: нормализованный JSON

    """
    objects = models.Manager()

    task_response = models.OneToOneField(StudentTaskResponse, on_delete=models.CASCADE, verbose_name=_("Task Response"))
    llm_version = models.CharField(max_length=50, blank=True, verbose_name=_("LLM Version"))
    raw_output = models.JSONField(verbose_name=_("Raw LLM Output"))
    structured_feedback = models.JSONField(verbose_name=_("Structured Feedback"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))

    class Meta:
        verbose_name = _("Assessment")
        verbose_name_plural = _("Assessments")
        indexes = [models.Index(fields=['task_response'])]

    def __str__(self):
        return f"Assessment for {self.task_response}"
