from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.contrib.auth import get_user_model
from django.db.models import Q
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
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='ai_chats',
        null=True,
        blank=True,
        verbose_name=_('Пользователь'),
        help_text=_('Владелец персонального AI-чата')
    )
    participants = models.ManyToManyField(
        User,
        related_name='chats',
        verbose_name=_('Участники'),
        help_text=_('Пользователи, имеющие доступ к чату')
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

    is_ai_enabled = models.BooleanField(
        default=False,
        verbose_name=_('AI активен'),
        help_text=_('Разрешить использование AI в групповом чате')
    )

    is_primary_ai_chat = models.BooleanField(
        default=False,
        verbose_name=_('Основной AI-чат'),
        help_text=_('Только один основной AI-чат на пользователя')
    )

    class Meta:
        verbose_name = _('Чат')
        verbose_name_plural = _('Чаты')
        indexes = [
            models.Index(fields=['type', '-created_at']),
            models.Index(fields=['telegram_chat_id']),
            models.Index(fields=['user', 'is_primary_ai_chat']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'is_primary_ai_chat'],
                condition=models.Q(type=ChatType.AI, is_primary_ai_chat=True),
                name='unique_primary_ai_chat_per_user'
            )
        ]

    def save(self, *args, **kwargs):
        """Автогенерация названия и логика основного AI-чата"""
        if self.type == ChatType.AI:
            # Если это первый AI-чат для пользователя, делаем его основным
            if self.user and not Chat.objects.filter(user=self.user, type=ChatType.AI).exists():
                self.is_primary_ai_chat = True

            # Автоназвание для основного AI-чата
            if self.is_primary_ai_chat and not self.title:
                self.title = "Ваш нейро-репетитор по английскому"

            # Или обновляем название при смене статуса основного
            if self.is_primary_ai_chat and self.title != "Ваш нейро-репетитор по английскому":
                self.title = "Ваш нейро-репетитор по английскому"

        # Гарантируем только один основной AI-чат
        if self.is_primary_ai_chat and self.user and self.type == ChatType.AI:
            Chat.objects.filter(
                user=self.user,
                type=ChatType.AI,
                is_primary_ai_chat=True
            ).exclude(id=self.id).update(is_primary_ai_chat=False)

        super().save(*args, **kwargs)

    def __str__(self):
        return self.title or f"Chat #{self.id} ({self.get_type_display()})"

    @classmethod
    def get_or_create_primary_ai_chat(cls, user):
        """
        Получает или создаёт основной AI-чат для пользователя
        """
        # Пытаемся найти существующий основной AI-чат
        chat = cls.objects.filter(
            user=user,
            type=ChatType.AI,
            is_primary_ai_chat=True
        ).first()

        if chat:
            return chat

        # Создаём новый чат
        chat = cls.objects.create(
            type=ChatType.AI,
            user=user,
            is_primary_ai_chat=True,
            is_ai_enabled=True
        )

        # Добавляем пользователя в участники
        chat.participants.add(user)

        return chat

    @classmethod
    def create_secondary_ai_chat(cls, user, title=None, chat_type='specialized'):
        """
        Создаёт дополнительный AI-чат для специализированных целей
        (бизнес-английский, разговорная практика и т.д.)
        """
        title = title or f"Дополнительный AI-чат ({chat_type})"

        chat = cls.objects.create(
            type=ChatType.AI,
            user=user,
            is_primary_ai_chat=False,
            is_ai_enabled=True,
            title=title
        )

        chat.participants.add(user)
        return chat


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

    is_user_deleted = models.BooleanField(
        default=False,
        verbose_name=_('сообщение удалено пользователем'),
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
