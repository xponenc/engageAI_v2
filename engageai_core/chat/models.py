from typing import Optional

from django.contrib.postgres.indexes import GinIndex
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from ai_assistant.models import AIAssistant

User = get_user_model()


class ChatPlatform(models.TextChoices):
    """Платформы/источники чатов"""
    WEB = 'web', _('Веб-интерфейс')
    TELEGRAM = 'telegram', _('Telegram')
    API = 'api', _('Внешний API')
    WHATSAPP = 'whatsapp', _('WhatsApp')


class ChatScope(models.TextChoices):
    """Тип/область чата"""
    PRIVATE = 'private', _('Персональный чат')
    GROUP = 'group', _('Групповой чат')
    SYSTEM = 'system', _('Системные уведомления')


class Chat(models.Model):
    """Модель чата с четким разделением понятий"""
    objects = models.Manager()

    # Основные характеристики
    title = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_('Название чата')
    )

    # 1. Платформа/источник
    platform = models.CharField(
        max_length=20,
        choices=ChatPlatform.choices,
        default=ChatPlatform.WEB,
        verbose_name=_('Платформа')
    )

    # 2. Тип/область
    scope = models.CharField(
        max_length=20,
        choices=ChatScope.choices,
        default=ChatScope.PRIVATE,
        verbose_name=_('Тип чата')
    )

    # Владелец для персональных чатов
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='personal_chats',
        null=True,
        blank=True,
        verbose_name=_('Владелец')
    )

    # Участники для групповых чатов
    participants = models.ManyToManyField(
        User,
        related_name='group_chats',
        verbose_name=_('Участники'),
        blank=True
    )

    # 3. AI-ассистент
    ai_assistant = models.ForeignKey(
        AIAssistant,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='chats',
        verbose_name=_('AI-ассистент')
    )

    # Флаги
    is_ai_enabled = models.BooleanField(
        default=True,
        verbose_name=_('AI активен'),
        help_text=_('Разрешить использование AI в чате')
    )

    # Синхронизация с внешними сервисами
    external_chat_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_('Внешний ID чата'),
        help_text=_('Используется для синхронизации с внешними API')
    )

    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _('Чат')
        verbose_name_plural = _('Чаты')
        indexes = [
            models.Index(fields=['owner', '-created_at']),
            models.Index(fields=['platform', 'scope']),
            models.Index(fields=['external_chat_id']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'ai_assistant', 'platform', 'scope'],
                name='unique_owner_ai_assistant_chat'
            )
        ]

    def __str__(self):
        return self.title or f"Chat #{self.id} ({self.get_platform_display()}/{self.get_scope_display()})"

    def save(self, *args, **kwargs):
        """Автоматическая логика при сохранении"""

        # Для персональных чатов добавляем владельца в участники если еще не добавлен
        super().save(*args, **kwargs)
        if self.scope == ChatScope.PRIVATE and self.owner and not self.participants.filter(id=self.owner.id).exists():
            self.participants.add(self.owner)

    @classmethod
    def get_or_create_ai_chat(
            cls,
            user: User,
            ai_assistant: AIAssistant,
            platform=ChatPlatform.WEB,
            title: Optional[str] = None
    ):
        """
        Получает или создаёт чат с конкретным AI-ассистентом
        """
        default_title = title or f"Чат с {ai_assistant.name}"

        chat, created = cls.objects.get_or_create(
            owner=user,
            ai_assistant=ai_assistant,
            platform=platform,
            defaults={
                'scope': ChatScope.PRIVATE,
                'is_ai_enabled': True,
                'title': default_title
            }
        )
        return chat, created


class MessageSource(models.TextChoices):
    """Источники сообщений для централизованной истории"""
    WEB = 'web', _('Веб-интерфейс')
    TELEGRAM = 'telegram', _('Telegram')
    API = 'api', _('Внешний API')
    SYSTEM = 'system', _('Системное сообщение')


class Message(models.Model):
    """Сообщение с поддержкой разных источников и метаданных"""
    objects = models.Manager()

    chat = models.ForeignKey(
        Chat,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name=_('Чат')
    )
    sender = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='sent_messages',
        verbose_name=_('Отправитель')
    )
    reply_to = models.ForeignKey(
        "Message",
        verbose_name=_("ответ на"),
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        related_name="answers"
    )
    content = models.TextField(
        verbose_name=_('Содержание сообщения')
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Время отправки')
    )
    is_ai = models.BooleanField(
        default=False,
        verbose_name=_('Сообщение от AI'),
        help_text=_('Помечает сообщение как сгенерированное AI')
    )
    is_read = models.BooleanField(
        default=False,
        verbose_name=_('Прочитано'),
        help_text=_('Статус прочтения для уведомлений и личных чатов')
    )

    is_user_deleted = models.BooleanField(
        default=False,
        verbose_name=_('сообщение удалено пользователем'),
    )
    source_type = models.CharField(
        max_length=20,
        choices=MessageSource.choices,
        default=MessageSource.WEB,
        verbose_name=_('Источник сообщения'),
        help_text=_('Откуда пришло сообщение: веб, Telegram, API и т.д.')
    )
    external_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_('Внешний ID сообщения'),
        help_text=_('ID сообщения в источнике (например, message_id в Telegram)')
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Дата создания')
    )
    edited_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Время последнего редактирования')
    )
    edit_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Количество редактирований')
    )
    score = models.SmallIntegerField(
        verbose_name=_('оценка'), null=True, blank=True,
        validators=[MinValueValidator(-2), MaxValueValidator(2)])

    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_('Метаданные'),
        help_text=_('Дополнительные данные от источника в формате JSON')
    )

    class Meta:
        verbose_name = _('Сообщение')
        verbose_name_plural = _('Сообщения')
        ordering = ['timestamp']
        indexes = [
            models.Index(fields=['chat', '-timestamp']),
            models.Index(fields=['is_read', 'timestamp']),
            models.Index(fields=['source_type', '-timestamp']),
            models.Index(fields=['external_id']),
            GinIndex(fields=["metadata"], name="message_metadata_gin_idx"),
        ]

    def __str__(self):
        sender = self.sender.username if self.sender else _('Система')
        return (f"[{self.get_source_type_display()}] {sender}:"
                f" {self.content[:50]}{'...' if len(self.content) > 50 else ''}")

    def get_telegram_data(self):
        """Получение данных специфичных для Telegram"""
        if self.source_type == MessageSource.TELEGRAM:
            return self.metadata.get('telegram', {})
        return {}

    def get_display_content(self):
        """Форматирование содержимого для отображения в интерфейсе"""
        content = self.content

        # Применяем Telegram-форматирование если есть entities
        if self.source_type == MessageSource.TELEGRAM:
            entities = self.get_telegram_data().get('entities', [])
            for entity in sorted(entities, key=lambda x: x['offset'], reverse=True):
                start = entity['offset']
                end = start + entity['length']

                if entity['type'] == 'mention':
                    content = content[:start] + f"@{content[start:end]}" + content[end:]
                elif entity['type'] == 'bot_command':
                    content = content[:start] + f"*{content[start:end]}*" + content[end:]

        return content

    def get_edit_history(self):
        """Получение истории редактирований"""
        return self.metadata.get('edit_history', [])

    def add_edit_history(self, old_content, editor_id, edit_time):
        """Добавление записи в историю редактирований"""
        history = self.get_edit_history()

        # Максимум 10 версий для экономии места
        if len(history) >= 10:
            history.pop(0)  # Удаляем самую старую версию

        history.append({
            'timestamp': edit_time.isoformat(),
            'content': old_content,
            'editor_id': editor_id,
            'version': len(history) + 1
        })

        self.metadata['edit_history'] = history
        return history
