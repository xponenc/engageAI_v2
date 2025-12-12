import logging
import os
import uuid
from urllib.parse import urlparse

import requests
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from chat.models import MessageType, MediaFile


logger = logging.getLogger(__name__)


class AiMediaService:
    """Сервис для обработки медиафайлов, сгенерированных AI"""

    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB для AI-сгенерированных файлов
    MAX_DOWNLOAD_TIME = 30  # секунд

    def __init__(self, chat):
        self.chat = chat
        self.user = chat.user

    def process_ai_media(self, ai_media_data, ai_message):
        """
        Асинхронно обрабатывает медиафайлы, сгенерированные AI
        """
        from ..tasks import process_ai_generated_media_async

        if not ai_media_data:
            return

        # Ставим задачи в очередь для каждого медиафайла
        for item in ai_media_data:
            process_ai_generated_media_async.delay(
                ai_message_id=ai_message.pk,
                media_data=item,
                user_id=self.user.pk if self.user else None
            )

    def _process_single_media(self, media_data, ai_message):
        """Синхронная обработка одного медиафайла (для отладки)""" # TODO потом переделать на асинхронную или таски
        try:
            # Скачиваем файл
            response = requests.get(
                media_data['url'],
                timeout=self.MAX_DOWNLOAD_TIME,
                headers={'User-Agent': 'Mozilla/5.0 (compatible; AI-Bot/1.0)'}
            )
            response.raise_for_status()

            # Проверяем размер
            if len(response.content) > self.MAX_FILE_SIZE:
                logger.warning(f"AI-сгенерированный файл слишком большой: {len(response.content)} байт")
                return None

            # Определяем параметры файла
            file_url = media_data['url']
            file_ext = os.path.splitext(urlparse(file_url).path)[1].lower() or '.bin'
            mime_type = media_data.get('mime_type', response.headers.get('content-type', 'application/octet-stream'))

            # Генерируем уникальное имя
            filename = f"ai_generated/{uuid.uuid4()}{file_ext}"

            # Сохраняем файл
            file_content = ContentFile(response.content)
            file_path = default_storage.save(filename, file_content)

            # Определяем тип файла
            file_type = AiMediaService._determine_file_type(mime_type, file_ext)

            # Создаем объект MediaFile (миниатюра будет сгенерирована автоматически)
            media_obj = MediaFile.objects.create(
                message=ai_message,
                file=file_path,
                file_type=file_type,
                mime_type=mime_type,
                size=len(response.content),
                created_by=self.user,
                ai_generated=True
            )

            return media_obj

        except Exception as e:
            logger.error(f"Ошибка при обработке AI-медиа: {str(e)}")
            return None

    @staticmethod
    def _determine_file_type(mime_type, file_ext):
        """Определяет тип файла для AI-сгенерированных медиа"""
        mime_type = mime_type.lower()
        file_ext = file_ext.lower().strip('.')

        if mime_type.startswith('image/') or file_ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']:
            return 'image'
        elif mime_type.startswith('audio/') or file_ext in ['mp3', 'wav', 'ogg', 'm4a']:
            return 'audio'
        elif mime_type.startswith('video/') or file_ext in ['mp4', 'webm', 'mov']:
            return 'video'

        return 'document'

    @staticmethod
    def _get_message_type_for_media(file_type):
        """Возвращает тип сообщения для данного типа файла"""
        mapping = {
            'image': MessageType.IMAGE,
            'audio': MessageType.AUDIO,
            'video': MessageType.VIDEO,
            'document': MessageType.DOCUMENT
        }
        return mapping.get(file_type, MessageType.TEXT)