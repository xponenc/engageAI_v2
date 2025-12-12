import logging
import os
import uuid
import requests
from urllib.parse import urlparse
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.conf import settings

from ..models import MediaFile, MessageType
from ..tasks import process_ai_generated_media_async






class UserMediaService:
    """Сервис для обработки медиафайлов, загруженных пользователем"""

    MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB
    ALLOWED_MIME_TYPES = {
        'image': ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/bmp'],
        'audio': ['audio/mpeg', 'audio/wav', 'audio/ogg', 'audio/x-m4a'],
        'video': ['video/mp4', 'video/webm', 'video/quicktime'],
        'document': [
            'application/pdf', 'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.ms-excel',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'application/vnd.ms-powerpoint',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'application/zip', 'application/x-rar-compressed'
        ]
    }

    def __init__(self, user):
        self.user = user

    def validate_file(self, uploaded_file):
        """Валидация загружаемого файла"""
        # Проверка размера
        if uploaded_file.size > self.MAX_FILE_SIZE:
            max_mb = self.MAX_FILE_SIZE // 1024 // 1024
            raise ValueError(f"Размер файла превышает максимально допустимый ({max_mb}MB)")

        # Проверка типа файла
        mime_type = uploaded_file.content_type.lower()
        file_ext = os.path.splitext(uploaded_file.name)[1].lower()

        # Определяем тип файла
        file_type = self._determine_file_type(mime_type, file_ext)
        if not file_type:
            raise ValueError("Недопустимый тип файла")

        # Дополнительная проверка безопасности
        if not self._is_mime_type_allowed(mime_type, file_type):
            raise ValueError("Недопустимый MIME-тип файла")

        return file_type

    def handle_uploaded_file(self, uploaded_file, message):
        """Обрабатывает загруженный файл и создает MediaFile"""
        try:
            with transaction.atomic():
                # Валидация файла
                file_type = self.validate_file(uploaded_file)

                # Создаем объект MediaFile (миниатюра будет сгенерирована автоматически)
                media_obj = MediaFile.objects.create(
                    message=message,
                    file=uploaded_file,
                    file_type=file_type,
                    mime_type=uploaded_file.content_type,
                    size=uploaded_file.size,
                    created_by=self.user,
                    ai_generated=False
                )

                # Обновляем тип сообщения
                self._update_message_type(message, file_type)

                return media_obj

        except Exception as e:
            # Логируем ошибку, но не прерываем транзакцию
            logger.error(f"Ошибка при сохранении файла: {str(e)}")
            raise

    def _determine_file_type(self, mime_type, file_ext):
        """Определяет тип файла по MIME-типу и расширению"""
        mime_type = mime_type.lower()
        file_ext = file_ext.lower().strip('.')

        # Проверяем по MIME-типу
        for file_type, mime_types in self.ALLOWED_MIME_TYPES.items():
            if any(mime_type.startswith(allowed) for allowed in mime_types):
                return file_type

        # Проверяем по расширению
        if file_ext in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg', 'ico']:
            return 'image'
        elif file_ext in ['mp3', 'wav', 'ogg', 'm4a', 'aac', 'flac', 'wma']:
            return 'audio'
        elif file_ext in ['mp4', 'avi', 'mov', 'wmv', 'mkv', 'webm', 'flv']:
            return 'video'

        return 'document'

    def _is_mime_type_allowed(self, mime_type, file_type):
        """Проверяет, разрешен ли MIME-тип для данного типа файла"""
        allowed_types = self.ALLOWED_MIME_TYPES.get(file_type, [])
        return any(mime_type.startswith(allowed) for allowed in allowed_types)

    def _update_message_type(self, message, file_type):
        """Обновляет тип сообщения на основе типа файла"""
        type_mapping = {
            'image': MessageType.IMAGE,
            'audio': MessageType.AUDIO,
            'video': MessageType.VIDEO,
            'document': MessageType.DOCUMENT
        }
        message.message_type = type_mapping.get(file_type, MessageType.TEXT)
        message.save(update_fields=['message_type'])

