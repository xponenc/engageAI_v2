from django.db import models
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class ChatType(models.TextChoices):
    """Типы чатов с поддержкой локализации"""
    AI = 'ai', _('Чат с AI')
    GROUP = 'group', _('Групповой чат')
    NOTIFICATION = 'notification', _('Уведомления')
    TELEGRAM = 'telegram', _('Telegram чат')


class Chat(models.Model):
    """Модель чата, поддерживающая разные типы источников"""
    objects = models.Manager()

    type = models.CharField(
        max_length=20,
        choices=ChatType.choices,
        default=ChatType.AI,
        verbose_name=_('Тип чата'),
        help_text=_('Определяет логику работы чата и доступные функции')
    )
    title = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_('Название чата'),
        help_text=_('Отображается в интерфейсе пользователя')
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Дата создания')
    )
    participants = models.ManyToManyField(
        User,
        related_name='chats',
        verbose_name=_('Участники'),
        help_text=_('Пользователи, имеющие доступ к чату')
    )
    is_ai_enabled = models.BooleanField(
        default=False,
        verbose_name=_('AI активен'),
        help_text=_('Разрешить использование AI в групповом чате')
    )
    notification_recipient = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='notification_chats',
        verbose_name=_('Получатель уведомлений')
    )
    telegram_chat_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name=_('ID чата в Telegram'),
        help_text=_('Используется для синхронизации с Telegram API')
    )

    class Meta:
        verbose_name = _('Чат')
        verbose_name_plural = _('Чаты')
        indexes = [
            models.Index(fields=['type', '-created_at']),
            models.Index(fields=['telegram_chat_id']),
        ]

    def save(self, *args, **kwargs):
        """Автогенерация названия для AI-чатов"""
        if self.type == ChatType.AI and not self.title:
            self.title = f"AI Chat {self.id or _('новый')}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title or f"Chat #{self.id} ({self.get_type_display()})"


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
    source_type = models.CharField(  # Ключевое поле для мультиисточников
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
    edited_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Время последнего редактирования')
    )
    edit_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Количество редактирований')
    )
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

