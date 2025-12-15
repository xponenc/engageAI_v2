import logging
import os
import re
import uuid
from typing import Optional

from django.contrib.postgres.indexes import GinIndex
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ai_assistant.models import AIAssistant


User = get_user_model()
logger = logging.getLogger(__name__)


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
    # title = models.CharField(
    #     max_length=255,
    #     blank=True,
    #     verbose_name=_('Название чата')
    # )

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
        return f"Chat #{self.id} ({self.get_platform_display()}/{self.get_scope_display()})"

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


class MessageType(models.TextChoices):
    """Тип сообщения"""
    TEXT = 'text', 'Текст'
    IMAGE = 'image', 'Изображение'
    AUDIO = 'audio', 'Аудио'
    VIDEO = 'video', 'Видео'
    DOCUMENT = 'document', 'Документ'


def sanitize_filename(filename: str) -> str:
    """
    Очищает имя файла от недопустимых символов и ограничивает длину
    """
    # Удаляем недопустимые символы
    cleaned = re.sub(r'[<>:"/\\|?*]', '', filename)
    # Заменяем пробелы и специальные символы на подчёркивания
    cleaned = re.sub(r'[\s\W]+', '_', cleaned)
    # Ограничиваем длину имени файла (максимум 100 символов для имени + расширение)
    max_name_length = 100
    if len(cleaned) > max_name_length:
        name, ext = os.path.splitext(cleaned)
        cleaned = name[:max_name_length - len(ext) - 10] + "..." + ext
    # Приводим к нижнему регистру
    return cleaned.lower()


class MediaFile(models.Model):
    """Модель медиа-файла прикрепленного к сообщению Message"""

    THUMBNAIL_SIZE = 150, 150 # Размер миниатюр
    MAX_PROCESSING_SIZE = (4096, 4096) # Ограничиваем размеры для обработки больших изображений

    # def media_upload_path(instance, filename):
    #     """Динамический путь для медиафайлов"""
    #     return f'chat_media/{instance.message.chat.id}/{timezone.now().strftime("%Y/%m/%d")}/{filename}'
    #
    # def thumbnail_upload_path(instance, filename):
    #     """Динамический путь для миниатюр"""
    #     return f'chat_media/thumbnails/{instance.message.chat.id}/{timezone.now().strftime("%Y/%m/%d")}/{filename}'

    def media_upload_path(instance, filename):
        """Динамический путь для медиафайлов с сохранением оригинального имени"""
        # Извлекаем расширение файла
        ext = os.path.splitext(filename)[1].lower()

        # Генерируем временные метки и уникальный идентификатор
        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:6]  # Короткий уникальный ID

        # Получаем оригинальное имя файла из метаданных сообщения или используем filename
        original_name = "file"

        if hasattr(instance, 'message') and instance.message:
            # Пытаемся получить оригинальное имя из метаданных сообщения
            telegram_data = instance.message.get_telegram_data()
            raw_data = telegram_data.get('raw', {})

            # Ищем оригинальное имя в разных полях в зависимости от типа медиа
            if document := raw_data.get('document'):
                original_name = document.get('file_name', 'document')
            elif photo := raw_data.get('photo'):
                # Для фото берем caption или стандартное имя
                original_name = raw_data.get('caption', 'photo')
            elif video := raw_data.get('video'):
                original_name = video.get('file_name', 'video')
            elif audio := raw_data.get('audio'):
                original_name = audio.get('file_name', 'audio')
            elif voice := raw_data.get('voice'):
                original_name = 'voice_message'
            elif animation := raw_data.get('animation'):
                original_name = animation.get('file_name', 'animation')
            elif sticker := raw_data.get('sticker'):
                original_name = 'sticker'

        # Очищаем оригинальное имя файла
        clean_original_name = sanitize_filename(original_name)

        # Формируем окончательное имя файла
        # Формат: timestamp_uniqueid_originalname.ext
        file_name = f"{timestamp}_{unique_id}_{clean_original_name}{ext}"

        # Дополнительная защита от слишком длинных имён
        max_path_length = 255
        if len(file_name) > max_path_length:
            # Обрезаем оригинальную часть имени
            max_original_length = max_path_length - len(f"{timestamp}_{unique_id}__{ext}") - 1
            clean_original_name = clean_original_name[:max_original_length]
            file_name = f"{timestamp}_{unique_id}_{clean_original_name}{ext}"

        return f'chat_media/{instance.message.chat_id}/{timezone.now().strftime("%Y/%m/%d")}/{file_name}'

    def thumbnail_upload_path(instance, filename):
        """Динамический путь для миниатюр с сохранением связи с оригиналом"""
        # Аналогичная логика, но с пометкой "thumb"
        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:6]

        # Получаем оригинальное имя из связанного файла
        original_name = "image"
        if hasattr(instance, 'file') and instance.file:
            original_name = os.path.splitext(os.path.basename(instance.file.name))[0]

        clean_original_name = sanitize_filename(original_name)

        # Для миниатюр используем расширение jpg
        file_name = f"{timestamp}_{unique_id}_{clean_original_name}_thumb.jpg"

        return f'chat_media/thumbnails/{instance.message.chat_id}/{timezone.now().strftime("%Y/%m/%d")}/{file_name}'

    message = models.ForeignKey('Message', related_name='media_files', on_delete=models.CASCADE)
    file = models.FileField(upload_to=media_upload_path)
    thumbnail = models.ImageField(
        upload_to=thumbnail_upload_path,
        null=True,
        blank=True,
        verbose_name=_('Миниатюра')
    )
    external_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_('Внешний ID файла в Telegram')
    )
    file_type = models.CharField(max_length=20)  # image, audio, video, document
    mime_type = models.CharField(max_length=50)  # MIME type файла
    size = models.PositiveIntegerField()  # Размер в байтах
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    ai_generated = models.BooleanField(default=False)
    thumbnail_generated = models.BooleanField(default=False, verbose_name=_('Миниатюра сгенерирована'))


    def get_absolute_url(self):
        return self.file.url

    def should_generate_thumbnail(self):
        """Проверяет, нужно ли генерировать миниатюру для этого файла"""
        supported_types = ['image', 'photo']
        supported_mime_types = [
            'image/jpeg', 'image/png', 'image/gif', 'image/bmp',
            'image/webp', 'image/tiff', 'image/svg+xml'
        ]
        supported_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg']

        # Проверяем по типу файла
        if self.file_type in supported_types:
            return True

        # Проверяем по MIME-типу
        if any(mime in self.mime_type.lower() for mime in supported_mime_types):
            return True

        # Проверяем по расширению файла
        file_extension = os.path.splitext(self.file.name.lower())[1]
        if file_extension in supported_extensions:
            return True

        return False



    class Meta:
        # Добавляем уникальность для предотвращения дубликатов
        constraints = [
            models.UniqueConstraint(
                fields=['message', 'external_id'],
                name='unique_media_per_message'
            )
        ]
        indexes = [
            models.Index(fields=['thumbnail_generated']),
            models.Index(fields=['file_type', 'mime_type']),
        ]
        verbose_name = _('Медиафайл')
        verbose_name_plural = _('Медиафайлы')


@receiver(post_save, sender=MediaFile)
def handle_thumbnail_generation(sender, instance, created, **kwargs):
    """
    Обрабатывает генерацию миниатюр асинхронно через Celery
    """
    from .tasks import generate_thumbnail_async
    # Пропускаем если:
    # 1. Это не новое создание и миниатюра уже есть
    # 2. Модель уже имеет флаг thumbnail_generated
    if not created and (instance.thumbnail_generated or instance.thumbnail):
        return

    # Проверяем, нужно ли генерировать миниатюру
    if not instance.should_generate_thumbnail():
        # Атомарно обновляем флаг
        MediaFile.objects.filter(pk=instance.pk).update(thumbnail_generated=True)
        return

    # Ставим задачу в очередь Celery
    try:
        generate_thumbnail_async.delay(instance.pk)
        logger.info(f"Задача генерации миниатюры поставлена в очередь для MediaFile ID {instance.pk}")
    except Exception as e:
        logger.error(f"Ошибка постановки задачи генерации миниатюры для MediaFile ID {instance.pk}: {str(e)}")
        # В случае ошибки ставим задачу синхронно (fallback)
        try:

            generate_thumbnail_async(instance.pk)
        except Exception as sync_e:
            logger.error(f"Синхронная генерация миниатюры также не удалась: {str(sync_e)}")


@receiver(post_delete, sender=MediaFile)
def delete_media_files_on_delete(sender, instance, **kwargs):
    """
    Удаляет физические файлы при удалении объекта MediaFile
    """

    def safe_delete(file_field):
        """Безопасное удаление файла"""
        if not file_field:
            return

        file_path = file_field.path
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Файл удален: {file_path}")
            except Exception as e:
                logger.error(f"Ошибка удаления файла {file_path}: {str(e)}")

    # Удаляем основной файл
    safe_delete(instance.file)

    # Удаляем миниатюру
    safe_delete(instance.thumbnail)


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

    message_type = models.CharField(
        max_length=20,
        choices=MessageType.choices,
        default=MessageType.TEXT,
        verbose_name=_('Тип сообщения')
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
