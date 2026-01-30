from django.db import models
from django.utils.translation import gettext_lazy as _


class LLMRequestType(models.TextChoices):
    """Типы запроса к LLM"""
    COURSE_GENERATION = ('COURSE_GEN', 'Генерация курса')
    LESSON_GENERATION = ('LESSON_GEN', 'Генерация урока')
    LESSON_REVIEW = ('LESSON_REVIEW', 'Оценка урока')
    TASK_GENERATION = ('TASK_GEN', 'Генерация задания')
    TASK_REVIEW = ('TASK_REVIEW', 'Оценка задания')
    CHAT = ('CHAT', 'Чат с AI')
    DIAGNOSTIC = ('DIAGNOSTIC', 'Диагностика')
    FEEDBACK = ('FEEDBACK', 'Фидбэк студенту')
    OTHER = ('OTHER', 'Другое')

class LogLLMRequest(models.Model):
    """
    Лог запроса к LLM.
    Хранит полный контекст: запрос, ответ, стоимость, модель, привязку к пользователю/курсу/уроку.
    """
    request_time = models.DateTimeField(auto_now_add=True, verbose_name=_("Время запроса"))
    model_name = models.CharField(max_length=50, verbose_name=_("Имя модели"), help_text=_("e.g., 'gpt-4o-mini'"))
    prompt = models.JSONField(verbose_name=_("Промпт запроса"), help_text=_("Полный текст запроса к LLM"))
    response = models.TextField(verbose_name=_("Ответ LLM (текстовый)"), blank=True, null=True, help_text=_("Текстовый ответ от LLM"))
    response_json = models.JSONField(verbose_name="Ответ LLM (структура)", blank=True, null=True, help_text=_("Структурированный JSON ответ от LLM"),)
    tokens_in = models.PositiveIntegerField(default=0, verbose_name=_("Токены на вход"))
    tokens_out = models.PositiveIntegerField(default=0, verbose_name=_("Токены на выход"))
    cost_in = models.DecimalField(max_digits=10, decimal_places=5, default=0, verbose_name=_("Стоимость входа"))
    cost_out = models.DecimalField(max_digits=10, decimal_places=5, default=0, verbose_name=_("Стоимость выхода"))
    cost_total = models.DecimalField(max_digits=10, decimal_places=5, default=0, verbose_name=_("Общая стоимость"))
    duration_sec = models.FloatField(null=True, blank=True, verbose_name=_("Длительность генерации, сек") )
    request_type = models.CharField(max_length=50, choices=LLMRequestType.choices, default=LLMRequestType.OTHER,
                                    verbose_name=_("Тип запроса"), help_text=_("Классификация запроса для аналитики"))

    error_message = models.TextField(blank=True, verbose_name=_("Сообщение об ошибке"))
    metadata = models.JSONField(default=dict, blank=True, verbose_name=_("Метаданные"), help_text=_("Дополнительный контекст запроса"))
    user = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("Пользователь"), related_name='llm_logs')
    course = models.ForeignKey('curriculum.Course', on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("Курс"), related_name='llm_logs')
    lesson = models.ForeignKey('curriculum.Lesson', on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("Урок"), related_name='llm_logs')
    task = models.ForeignKey('curriculum.Task', on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("Задание"), related_name='llm_logs')
    status = models.CharField(max_length=20, default='SUCCESS', choices=[
        ('SUCCESS', 'Успех'),
        ('ERROR', 'Ошибка'),
        ('TIMEOUT', 'Таймаут'),
    ], verbose_name=_("Статус"))

    class Meta:
        verbose_name = _("LLM Log")
        verbose_name_plural = _("LLM Logs")
        ordering = ['-request_time']
        indexes = [
            # Основные индексы для фильтрации
            models.Index(fields=['request_time'], name='llm_request_time_idx'),
            models.Index(fields=['request_type'], name='llm_request_type_idx'),
            models.Index(fields=['model_name'], name='llm_model_name_idx'),
            models.Index(fields=['status'], name='llm_status_idx'),

            # Композитные индексы для частых запросов
            models.Index(fields=['request_type', '-request_time'], name='llm_type_time_idx'),
            models.Index(fields=['model_name', '-request_time'], name='llm_model_time_idx'),
            models.Index(fields=['status', '-request_time'], name='llm_status_time_idx'),
            models.Index(fields=['user', '-request_time'], name='llm_user_time_idx'),

            # Для аналитики по учебному контенту
            models.Index(fields=['course', '-request_time'], name='llm_course_time_idx'),
            models.Index(fields=['lesson', '-request_time'], name='llm_lesson_time_idx'),
            models.Index(fields=['task', '-request_time'], name='llm_task_time_idx'),

            # Для агрегаций по стоимости
            models.Index(fields=['cost_total'], name='llm_cost_total_idx'),

            # JSON индекс для метаданных (PostgreSQL)
            models.Index(fields=['metadata'], name='llm_metadata_idx'),  # GIN index in migration
        ]

    def __str__(self):
        return f"LLM Log #{self.id} ({self.model_name}) at {self.request_time}"