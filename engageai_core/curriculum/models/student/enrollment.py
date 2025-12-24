from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from curriculum.models.content.course import Course
from curriculum.models.content.lesson import Lesson
from curriculum.models.content.task import Task
from curriculum.models.skills.skill_snapshot import SkillSnapshot
from users.models import Student


class Enrollment(models.Model):
    """
    Зачисление студента на курс с полным отслеживанием прогресса.
    """
    objects = models.Manager()

    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name=_("Student"))
    course = models.ForeignKey(Course, on_delete=models.CASCADE, verbose_name=_("Course"))
    started_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Started At"))
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Completed At"))

    # Текущее состояние обучения
    current_lesson = models.ForeignKey(
        Lesson,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Current Lesson"),
        related_name="active_enrollments"
    )

    # Прогресс и состояние
    progress_snapshot = models.ForeignKey(
        SkillSnapshot,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Progress Snapshot"),
        help_text=_("Последний зафиксированный снимок навыков")
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Is Active"))
    last_activity = models.DateTimeField(auto_now=True, verbose_name=_("Last Activity"))

    class Meta:
        verbose_name = _("Enrollment")
        verbose_name_plural = _("Enrollments")
        indexes = [
            models.Index(fields=['student', 'course']),
            models.Index(fields=['is_active']),
            models.Index(fields=['last_activity']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'course', 'is_active'],
                condition=models.Q(is_active=True),
                name='unique_active_enrollment'
            )
        ]

    def __str__(self):
        status = "active" if self.is_active else "completed"
        return f"{self.student} → {self.course} ({status})"

    def complete(self):
        """Завершает зачисление"""
        self.is_active = False
        self.completed_at = timezone.now()
        self.save(update_fields=['is_active', 'completed_at'])

    def get_current_skills(self):
        """Возвращает текущее состояние навыков"""
        if self.progress_snapshot:
            return self.progress_snapshot.to_dict()
        # Создаем базовый snapshot если нет
        from curriculum.services.skills.skill_snapshot_creator import SkillSnapshotCreator
        snapshot = SkillSnapshotCreator().create(student=self.student)
        self.progress_snapshot = snapshot
        self.save(update_fields=['progress_snapshot'])
        return snapshot.to_dict()
