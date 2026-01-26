from django.db import models
from django.utils.translation import gettext_lazy as _


class LogLLMRequest(models.Model):
    """
    Лог запроса к LLM.
    Хранит полный контекст: запрос, ответ, стоимость, модель, привязку к пользователю/курсу/уроку.
    """
    request_time = models.DateTimeField(auto_now_add=True, verbose_name=_("Время запроса"))
    model_name = models.CharField(max_length=50, verbose_name=_("Имя модели"), help_text=_("e.g., 'gpt-4o-mini'"))
    prompt = models.TextField(verbose_name=_("Промпт запроса"), help_text=_("Полный текст запроса к LLM"))
    response = models.TextField(verbose_name=_("Ответ LLM"), blank=True, help_text=_("Полный ответ, включая JSON"))
    tokens_in = models.PositiveIntegerField(default=0, verbose_name=_("Токены на вход"))
    tokens_out = models.PositiveIntegerField(default=0, verbose_name=_("Токены на выход"))
    cost_in = models.DecimalField(max_digits=10, decimal_places=5, default=0, verbose_name=_("Стоимость входа"))
    cost_out = models.DecimalField(max_digits=10, decimal_places=5, default=0, verbose_name=_("Стоимость выхода"))
    cost_total = models.DecimalField(max_digits=10, decimal_places=5, default=0, verbose_name=_("Общая стоимость"))
    duration_sec = models.FloatField(null=True, blank=True, verbose_name=_("Длительность генерации, сек") )

    error_message = models.TextField(blank=True, verbose_name=_("Сообщение об ошибке"))
    metadata = models.JSONField(default=dict, blank=True, verbose_name=_("Метаданные"), help_text=_("Дополнительный контекст запроса"))
    user = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("Пользователь"), related_name='llm_logs')
    course = models.ForeignKey('curriculum.Course', on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("Курс"), related_name='llm_logs')
    lesson = models.ForeignKey('curriculum.Lesson', on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("Урок"), related_name='llm_logs')
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
            models.Index(fields=['request_time']),
            models.Index(fields=['model_name']),
            models.Index(fields=['status']),
            models.Index(fields=['user', 'course', 'lesson']),
        ]

    def __str__(self):
        return f"LLM Log #{self.id} ({self.model_name}) at {self.request_time}"