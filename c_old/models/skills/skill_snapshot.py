from django.db import models

from users.models import Student

from django.utils.translation import gettext_lazy as _


class SkillSnapshot(models.Model):
    """
    Снимок навыков студента на определённый момент времени.
    """
    objects = models.Manager()

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="skill_snapshots",
        verbose_name=_("Студент")
    )

    enrollment = models.ForeignKey(
        "Enrollment",
        on_delete=models.CASCADE,
        related_name="skill_snapshots",
        verbose_name=_("Зачисление"),
        help_text=_("Контекст курса для адаптивных маршрутов"),
    )

    associated_lesson = models.ForeignKey(
        "Lesson",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="skill_snapshots",
        verbose_name=_("Связанный урок"),
        help_text="Урок, после завершения которого сделан снимок (POST). Для PRE используем урок,"
                  " который студент собирается начать."
    )

    snapshot_context = models.CharField(
        max_length=20,
        choices=[
            ("POST_LESSON", _("После завершения урока")),
            ("PLACEMENT", _("Результат placement test")),
            ("WEEKLY_SUMMARY", _("Еженедельный")),
            ("MANUAL", _("Ручной")),
        ],
        default="POST_LESSON",
        verbose_name=_("Контекст снимка")
    )
    grammar = models.FloatField(default=0.0)
    vocabulary = models.FloatField(default=0.0)
    listening = models.FloatField(default=0.0)
    reading = models.FloatField(default=0.0)
    writing = models.FloatField(default=0.0)
    speaking = models.FloatField(default=0.0)

    skills = models.JSONField(
        verbose_name=_("Навыки"),
        default=dict,
        help_text=_("{'grammar': 0.85, 'vocabulary': 0.78, 'speaking': 0.65, 'listening': 0.82, ...} — 0.0–1.0")

    )

    snapshot_at = models.DateTimeField(auto_now_add=True)

    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Метаданные"),
        help_text=_("e.g., {'source': 'assessment', 'lesson_score': 0.92, 'tasks_completed': 10}")
    )

    class Meta:
        verbose_name = _("Снимок навыков")
        verbose_name_plural = _("Снимки навыков")
        ordering = ["-snapshot_at"]
        indexes = [
            models.Index(fields=["student", "-snapshot_at"]),
            models.Index(fields=["enrollment", "associated_lesson"]),
            models.Index(fields=["snapshot_context"]),
        ]
        unique_together = ["enrollment", "associated_lesson"]  # Один POST-снимок на урок

    def to_dict(self):
        return {
            'grammar': self.grammar,
            'vocabulary': self.vocabulary,
            'listening': self.listening,
            'reading': self.reading,
            'writing': self.writing,
            'speaking': self.speaking,
            'metadata': self.metadata,
        }

    def __str__(self) -> str:
        return f"SkillSnapshot({self.student}, {self.snapshot_at})"
