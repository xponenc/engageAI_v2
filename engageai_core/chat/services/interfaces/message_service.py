import os
from typing import Optional, Union

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.utils import timezone
from chat.models import Message, MessageSource, MessageType, Chat
from chat.services.interfaces.base_service import BaseService
from chat.services.interfaces.exceptions import MessageCreationError, MessageException, MessageNotFoundError

User = get_user_model()


class MessageService(BaseService):
    """Сервис для работы с сообщениями"""

    @transaction.atomic
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

    @transaction.atomic
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
        """
        Обновляет тип сообщения на основе прикрепленных медиафайлов
        """
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
            self.logger.debug(f"Обновлен тип сообщения {message.pk} на {message.message_type}")

    def get_ajax_response(self, user_message: Message, ai_message: Message) -> JsonResponse:
        """
        Формирует AJAX-ответ для чата с поддержкой медиа
        """

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

    @transaction.atomic
    def update_ai_message_metadata(
            self,
            message: Message,
            telegram_message_id: Union[str, int],
            content: str,
            metadata: dict

    ) -> Message:
        """Обновляет метаданные AI-сообщения из Telegram"""
        # Обновление контента
        if message.content != content:
            message.content = content

        # Обновление метаданных
        telegram_metadata = message.metadata.get("telegram", {}) if message.metadata else {}
        telegram_metadata["message_id"] = str(telegram_message_id)
        telegram_metadata["raw"] = metadata

        message.metadata = {"telegram": telegram_metadata}
        message.timestamp = timezone.now()

        fields_to_update = ["content", "metadata", "timestamp"] if message.content != content else ["metadata",
                                                                                                    "timestamp"]
        message.save(update_fields=fields_to_update)

        return message

    def update_message_content(
            self,
            message_id: Union[str, int],
            new_content: str,
            editor_id: int
    ) -> Message:
        """
        Обновляет содержимое сообщения с сохранением истории редактирования

        Raises:
            MessageNotFoundException: Если сообщение не найдено
            MessageException: При ошибках обновления
        """
        try:
            message = Message.objects.select_for_update().get(id=message_id)

            if message.is_ai:
                self.logger.warning(f"Попытка редактирования AI-сообщения {message_id} пользователем {editor_id}")
                raise MessageException("Редактирование AI-сообщений запрещено", status_code=403)

            # Сохраняем историю редактирования
            metadata = message.metadata or {}
            if "edit_history" not in metadata:
                metadata["edit_history"] = []

            metadata["edit_history"].append({
                "timestamp": timezone.now().isoformat(),
                "old_content": message.content,
                "new_content": new_content,
                "editor_id": editor_id
            })

            # Обновляем сообщение
            Message.objects.filter(pk=message.pk).update(
                content=new_content,
                edited_at=timezone.now(),
                edit_count=F('edit_count') + 1,
                metadata=metadata
            )

            # Обновляем объект для возврата
            message.refresh_from_db()
            self.logger.info(f"Обновлено сообщение {message_id}, версия {message.edit_count}")
            return message

        except Message.DoesNotExist:
            self.logger.error(f"Сообщение {message_id} не найдено для редактирования")
            raise MessageNotFoundError(message=f"Сообщение {message_id} не найдено для редактирования",
                                       message_id=message_id)
        except Exception as e:
            self.logger.exception(f"Ошибка обновления сообщения {message_id}: {str(e)}")
            raise MessageException(f"Ошибка обновления сообщения: {str(e)}")

    def get_telegram_message_by_id(
            self,
            chat: Chat,
            telegram_message_id: Union[str, int]
    ) -> Optional[Message]:
        """Находит сообщение по Telegram message_id в указанном чате"""
        return Message.objects.filter(
            source_type=MessageSource.TELEGRAM,
            metadata__telegram__message_id=str(telegram_message_id),
            chat=chat
        ).first()

    @transaction.atomic
    def create_telegram_ai_message(
            self,
            chat: Chat,
            content: str,
            telegram_message_id: Union[str, int],
            reply_to: Optional[Message] = None,
            metadata: dict = None

    ) -> Message:
        """Создает AI-сообщение для Telegram"""
        telegram_metadata = {
            "message_id": str(telegram_message_id),
            "raw": metadata or {}
        }

        return Message.objects.create(
            chat=chat,
            content=content,
            is_ai=True,
            sender=None,
            source_type=MessageSource.TELEGRAM,
            reply_to=reply_to,
            metadata={"telegram": telegram_metadata}
        )

    def find_message_by_telegram_id(self, chat: Chat, telegram_message_id: str) -> Optional[Message]:
        """
        Находит сообщение по Telegram ID

        Returns:
            Message или None, если не найдено
        """
        return Message.objects.filter(
            chat=chat,
            source_type=MessageSource.TELEGRAM,
            metadata__telegram__message_id=str(telegram_message_id)
        ).first()

    def get_album_message(self, chat: Chat, media_group_id: str) -> Optional[Message]:
        """
        Находит существующее сообщение для альбома

        Returns:
            Message или None, если не найдено
        """
        return Message.objects.filter(
            chat=chat,
            source_type=MessageSource.TELEGRAM,
            metadata__telegram__media_group_id=str(media_group_id),
            external_id__startswith="album_"
        ).first()

    def create_album_message(
            self,
            chat: Chat,
            user: User,
            media_group_id: str,
            caption: str,
            first_update_id: Union[str, int],
            message_data: dict
    ) -> Message:
        """
        Создает сообщение для альбома

        Raises:
            MessageCreationException: При ошибке создания сообщения
        """
        try:
            # Определяем тип альбома
            album_type = "image" if "photo" in message_data else "mixed"
            message_type = MessageType.IMAGE if album_type == "image" else MessageType.DOCUMENT

            # Формируем метаданные
            telegram_metadata = {
                "media_group_id": str(media_group_id),
                "is_album": True,
                "album_type": album_type,
                "album_created_at": timezone.now().isoformat(),
                "first_update_id": str(first_update_id),
                "raw": message_data
            }

            # Создаем сообщение
            message = self.create_user_message(
                chat=chat,
                sender=user,
                content=caption,
                message_type=message_type,
                source_type=MessageSource.TELEGRAM,
                external_id=f"album_{media_group_id}",
                metadata={"telegram": telegram_metadata}
            )

            self.logger.info(f"Создано сообщение для альбома media_group_id={media_group_id}")
            return message

        except Exception as e:
            self.logger.exception(f"Ошибка создания сообщения для альбома: {str(e)}")
            raise MessageCreationError(f"Ошибка создания альбома: {str(e)}")

    def determine_message_type(self, message_data: dict) -> str:
        """Определяет тип сообщения на основе данных из Telegram API"""
        if message_data.get("photo"):
            return MessageType.IMAGE
        elif message_data.get("document"):
            mime_type = message_data["document"].get("mime_type", "")
            if mime_type.startswith("image/"):
                return MessageType.IMAGE
            return MessageType.DOCUMENT
        elif message_data.get("audio") or message_data.get("voice"):
            return MessageType.AUDIO
        elif message_data.get("video") or message_data.get("animation"):
            return MessageType.VIDEO
        elif message_data.get("sticker"):
            return MessageType.IMAGE
        return MessageType.TEXT

    def get_default_content_for_media(self, media_type: str, message_data: dict) -> str:
        """Возвращает содержимое по умолчанию для сообщений с медиа"""
        captions = {
            MessageType.IMAGE: "📷 Изображение",
            MessageType.AUDIO: "🎵 Аудио",
            MessageType.VIDEO: "🎬 Видео",
            MessageType.DOCUMENT: "📎 Документ"
        }

        # Если есть подпись к медиа, используем ее
        if caption := message_data.get("caption"):
            return caption

        return captions.get(media_type, "Медиафайл")
