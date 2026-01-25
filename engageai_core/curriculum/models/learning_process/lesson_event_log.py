from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model

from curriculum.models.content.lesson import Lesson
from curriculum.models.student.enrollment import Enrollment
from users.models import Student

User = get_user_model()


class LessonEventType(models.TextChoices):
    """
    Типы событий урока — основа для событийного подхода.
    Расширяемо под будущие сценарии (PAUSE, RESUME, ABANDON).
    """
    START = "START", _("Начало урока")
    COMPLETE = "COMPLETE", _("Завершение урока")
    PAUSE = "PAUSE", _("Пауза в уроке")
    RESUME = "RESUME", _("Возобновление урока")
    ABANDON = "ABANDON", _("Покинул урок без завершения")
    ASSESSMENT_START = "ASSESSMENT_START", _("Начало оценки урока")
    ASSESSMENT_COMPLETE = "ASSESSMENT_COMPLETE", _("Завершение оценки урока")
    ASSESSMENT_ERROR = "ASSESSMENT_ERROR", _("Ошибка оценки урока")


class LessonEventLog(models.Model):
    """
    Лог событий урока для конкретного студента в рамках зачисления.

    Ключевые возможности:
    - Фиксация точного времени начала/завершения урока
    - Расчёт длительности занятия (duration_minutes)
    - Основа для streaks, геймификации (баллы за timely completion)
    - Аналитика вовлечённости (drop-off на PAUSE/ABANDON)
    - Синхронизация между веб и Telegram-ботом
    - Интеграция с AI: триггер для генерации nudges при ABANDON > 24h
    """

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        verbose_name=_("Студент"),
        related_name="lesson_events",
        help_text=_("Ссылка на профиль студента с уровнем, целями и профессией")
    )

    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.CASCADE,
        verbose_name=_("Зачисление"),
        related_name="lesson_events",
        help_text=_("Контекст курса и текущего прогресса")
    )

    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        verbose_name=_("Урок"),
        related_name="events",
        null=True,
        blank=True,
        help_text=_("Конкретный урок, к которому относится событие")
    )

    event_type = models.CharField(
        max_length=32,
        choices=LessonEventType.choices,
        verbose_name=_("Тип события")
    )

    timestamp = models.DateTimeField(
        default=timezone.now,
        verbose_name=_("Время события"),
        db_index=True  # Для быстрой аналитики по времени
    )

    channel = models.CharField(
        max_length=20,
        choices=[
            ("WEB", _("Веб-приложение")),
            ("BOT", _("Telegram-бот")),
            ("API", _("Внешний API")),
        ],
        default="WEB",
        verbose_name=_("Канал"),
        help_text=_("Откуда пришло событие — для кросс-канальной аналитики")
    )

    duration_minutes = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Длительность (мин)"),
        help_text=_("Автоматически рассчитывается для COMPLETE по разнице с START")
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Метаданные"),
        help_text=_("Дополнительные данные: e.g., {'completed_tasks': 8, 'total_tasks': 10, 'score': 0.92}")
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Событие урока")
        verbose_name_plural = _("События уроков")
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["student", "-timestamp"]),
            models.Index(fields=["enrollment", "lesson"]),
            models.Index(fields=["event_type", "timestamp"]),
            models.Index(fields=["channel"]),
        ]

    def __str__(self):
        return f"{self.student} — {self.get_event_type_display()} — {self.lesson.title} [{self.timestamp:%Y-%m-%d %H:%M}]"

    def save(self, *args, **kwargs):
        """
        Автоматический расчёт duration_minutes при COMPLETE.
        """
        if self.event_type == LessonEventType.COMPLETE and not self.duration_minutes:
            start_event = LessonEventLog.objects.filter(
                student=self.student,
                enrollment=self.enrollment,
                lesson=self.lesson,
                event_type=LessonEventType.START
            ).order_by("-timestamp").first()

            if start_event:
                duration = (self.timestamp - start_event.timestamp).total_seconds() / 60
                self.duration_minutes = round(duration, 2)

        super().save(*args, **kwargs)

    @staticmethod
    def create_event(student, enrollment, lesson, event_type, channel="WEB", metadata=None):
        return LessonEventLog.objects.create(
            student=student,
            enrollment=enrollment,
            lesson=lesson,
            event_type=event_type,
            channel=channel,
            metadata=metadata or {}
        )