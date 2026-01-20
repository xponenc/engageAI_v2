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


class Enrollment(models.Model):
    """
    Зачисление студента на курс с полным отслеживанием прогресса.
    """
    objects = models.Manager()

    LESSON_STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('COMPLETED_TASKS', 'All tasks completed'),
        ('PENDING_ASSESSMENT', 'Pending assessment'),
        ('ASSESSMENT_ERROR', 'Assessment error'),
        ('COMPLETED', 'Lesson completed')
    ]

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

    # # Прогресс и состояние
    # progress_snapshot = models.ForeignKey(
    #     SkillSnapshot,
    #     on_delete=models.SET_NULL,
    #     null=True,
    #     blank=True,
    #     verbose_name=_("Progress Snapshot"),
    #     help_text=_("Последний зафиксированный снимок навыков")
    # )

    lesson_status = models.CharField(
        max_length=20,
        choices=LESSON_STATUS_CHOICES,
        default='ACTIVE',
        verbose_name=_("Lesson Status")
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

    def complete(self):
        """Завершает зачисление"""
        self.is_active = False
        self.completed_at = timezone.now()
        self.save(update_fields=['is_active', 'completed_at'])

    @receiver(post_save, sender="curriculum.Enrollment")
    def generate_initial_learning_path(sender, instance, created, **kwargs):
        """
        Сигнал: после создания нового Enrollment генерируем персонализированный путь.
        Полностью независим от current_lesson — вся маршрутизация через LearningPath.
        """
        if not created:
            return  # Только при создании

        # Создаём или получаем LearningPath
        path, created_path = LearningPath.objects.get_or_create(enrollment=instance)

        # Пытаемся сгенерировать персонализированный путь через AI
        try:
            updated_path = PathGenerationService.generate_personalized_path(instance)
            path_type = updated_path.path_type
        except Exception as e:
            # Fallback на линейный путь при любой ошибке (LLM недоступен, таймаут и т.д.)
            updated_path = PathGenerationService.generate_linear_fallback(instance)
            path_type = "LINEAR (fallback)"

        # Убеждаемся, что первый узел — in_progress
        if updated_path.nodes:
            updated_path.nodes[0]["status"] = "in_progress"
            updated_path.current_node_index = 0
            updated_path.save()

        # Логируем в метаданные для аналитики
        path.metadata.update({
            "initial_generation": timezone.now().isoformat(),
            "path_type": path_type,
            "nodes_count": len(updated_path.nodes),
            "fallback_used": path_type.startswith("LINEAR")
        })
        path.save()
