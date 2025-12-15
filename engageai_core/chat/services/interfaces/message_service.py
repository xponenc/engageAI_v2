import json
from typing import Optional

from django.http import JsonResponse
from django.urls import reverse_lazy
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist
from rest_framework import status
from chat.models import Message, MessageSource, MessageType, Chat
from chat.services.interfaces.base_service import BaseService


class MessageService(BaseService):
    """Сервис для работы с сообщениями"""

    def create_user_message(
            self,
            chat: Chat,
            sender,
            content: str = "",
            message_type: str = MessageType.TEXT,
            source_type: str = MessageSource.WEB,
            reply_to: Optional[Message] = None
    ) -> Message:
        """Создает сообщение пользователя"""
        try:
            message = Message.objects.create(
                chat=chat,
                content=content,
                sender=sender,
                message_type=message_type,
                source_type=source_type,
                reply_to=reply_to,
                timestamp=timezone.now(),
                is_ai=False
            )
            return message
        except Exception as e:
            self.logger.exception(f"Ошибка создания сообщения пользователя: {str(e)}")
            raise

    def create_ai_message(
            self,
            chat: Chat,
            content: str = "",
            reply_to: Optional[Message] = None,
            source_type: str = MessageSource.WEB,
            message_type: str = MessageType.TEXT
    ) -> Message:
        """Создает сообщение от AI"""
        try:
            message = Message.objects.create(
                chat=chat,
                content=content,
                sender=None,
                is_ai=True,
                message_type=message_type,
                source_type=source_type,
                reply_to=reply_to,
                timestamp=timezone.now()
            )
            return message
        except Exception as e:
            self.logger.exception(f"Ошибка создания AI-сообщения: {str(e)}")
            raise

    def update_message_type_from_media(self, message: Message) -> None:
        """Обновляет тип сообщения на основе прикрепленных медиафайлов"""
        if message.media_files.exists():
            first_media = message.media_files.first()
            file_type = first_media.file_type

            type_mapping = {
                'image': MessageType.IMAGE,
                'audio': MessageType.AUDIO,
                'video': MessageType.VIDEO,
                'document': MessageType.DOCUMENT
            }

            message.message_type = type_mapping.get(file_type, MessageType.TEXT)
            message.save(update_fields=['message_type'])
            self.logger.debug(f"Обновлен тип сообщения {message.id} на {message.message_type}")

    def get_ajax_response(self, user_message: Message, ai_message: Message) -> JsonResponse:
        """Формирует AJAX-ответ для чата с поддержкой медиа"""

        def serialize_media(media_files):
            return [{
                "id": media.pk,
                "url": media.get_absolute_url(),
                "type": media.file_type,
                "mime_type": media.mime_type,
                "name": os.path.basename(media.file.name),
                "thumbnail": media.thumbnail.url if media.thumbnail else None,
                "size": media.size
            } for media in media_files.all()]

        response_data = {
            'user_message': {
                "id": user_message.pk,
                "text": user_message.content,
                "message_type": user_message.message_type,
                "media_files": serialize_media(user_message.media_files)
            },
            'ai_response': {
                "id": ai_message.pk,
                "score": ai_message.score,
                "request_url": reverse_lazy("chat:ai-message-score", kwargs={"message_pk": ai_message.pk}),
                "text": ai_message.content,
                "message_type": ai_message.message_type,
                "media_files": serialize_media(ai_message.media_files)
            },
        }
        return JsonResponse(response_data)