from django.db import models
from django.utils.translation import gettext_lazy as _


class AIAssistantType(models.TextChoices):
    """Типы AI-ассистентов"""
    NEURO_TUTOR = 'neuro_tutor', _('Нейро-репетитор')
    TECHNICAL_EXPERT = 'tech_expert', _('Технический эксперт')
    CAREER_COACH = 'career_coach', _('Карьерный коуч')
    CONVERSATION_PARTNER = 'conversation_partner', _('Партнер для разговорной практики')


class AIAssistant(models.Model):
    """Модель AI-ассистента с параметрами и настройками"""
    objects = models.Manager()

    name = models.CharField(max_length=100, verbose_name=_('Название'))
    slug = models.SlugField(unique=True, verbose_name=_('Слаг'))

    assistant_type = models.CharField(
        max_length=50,
        choices=AIAssistantType.choices,
        verbose_name=_('Тип ассистента')
    )

    # Параметры работы
    system_prompt = models.TextField(verbose_name=_('Системный промпт'))
    temperature = models.FloatField(default=0.7, verbose_name=_('Температура'))
    max_tokens = models.IntegerField(default=1000, verbose_name=_('Макс. токены'))

    # Специализация
    specialization = models.CharField(max_length=100, blank=True, verbose_name=_('Специализация'))
    target_audience = models.CharField(max_length=100, blank=True, verbose_name=_('Целевая аудитория'))

    # Настройки обучения
    learning_goals = models.JSONField(default=list, verbose_name=_('Цели обучения'), blank=True, null=True)
    teaching_methods = models.JSONField(default=list, verbose_name=_('Методы обучения'), blank=True, null=True)

    # Статус
    is_active = models.BooleanField(default=True, verbose_name=_('Активен'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('AI-ассистент')
        verbose_name_plural = _('AI-ассистенты')
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['assistant_type']),
        ]

    def __str__(self):
        return self.name

    # @property
    # def agent_class(self):
    #     """Возвращает класс агента для этого ассистента"""
    #     from engageai_core.ai.agents import get_agent_class
    #     return get_agent_class(self.assistant_type)

    def get_system_prompt(self, user_context):
        """Возвращает промпт с подстановкой контекста пользователя"""
        return self.system_prompt.format(**user_context)
