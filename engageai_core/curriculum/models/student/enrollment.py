from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from curriculum.models.content.course import Course
from curriculum.models.content.lesson import Lesson
from curriculum.models.learning_process.learning_path import LearningPath

from curriculum.services.path_generation_service import PathGenerationService
from users.models import Student


class LessonStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', _('Active')
    COMPLETED_TASKS = 'COMPLETED_TASKS', _('All tasks completed')
    PENDING_ASSESSMENT = 'PENDING_ASSESSMENT', _('Pending assessment')
    ASSESSMENT_ERROR = 'ASSESSMENT_ERROR', _('Assessment error')
    COMPLETED = 'COMPLETED', _('Lesson completed')


class Enrollment(models.Model):
    """
    Зачисление студента на курс с полным отслеживанием прогресса.
    """
    objects = models.Manager()

    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name=_("Student"))
    course = models.ForeignKey(Course, on_delete=models.CASCADE, verbose_name=_("Course"))
    adaptive_path_enabled = models.BooleanField(default=False, verbose_name=_("Адаптивный путь активен"))

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

    lesson_status = models.CharField(
        max_length=20,
        choices=LessonStatus.choices,
        default=LessonStatus.ACTIVE,
        verbose_name=_("Lesson Status"),
    )
    assessment_job_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Assessment Job ID")
    )
    assessment_started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Assessment Started At")
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
            models.Index(fields=['lesson_status']),
            models.Index(fields=['assessment_job_id'])
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
