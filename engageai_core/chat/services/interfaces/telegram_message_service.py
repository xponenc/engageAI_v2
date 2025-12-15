from typing import Union, Dict, Optional, Any

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import status

from chat.models import Message, MessageSource, ChatPlatform
from chat.services.interfaces.base_service import BaseService
from chat.services.interfaces.chat_service import ChatService
from chat.services.interfaces.exceptions import AuthenticationError, UserNotFoundError, MessageNotFoundError
from chat.services.interfaces.message_service import MessageService

User = get_user_model()


class TelegramMessageService(BaseService):
    """Сервис для обработки сообщений Telegram через другие сервисы"""

    def __init__(self):
        super().__init__()
        self.chat_service = ChatService()
        self.message_service = MessageService()

    @transaction.atomic
    def process_message(
            self,
            payload: dict,
            user: User,
            bot_tag: str
    ) -> dict:
        """
        Обрабатывает AI-сообщение с использованием других сервисов
        """
        try:
            assistant_slug = payload.get("assistant_slug")
            core_message_id = payload.get("core_message_id")
            reply_to_message_id = payload.get("reply_to_message_id")
            telegram_message_id = payload.get("telegram_message_id")
            text = payload.get("text", "")
            metadata = payload.get("metadata", {})

            # Валидация обязательных полей
            if not telegram_message_id:
                raise AuthenticationError("Missing 'telegram_message_id' in request",
                                          status_code=status.HTTP_400_BAD_REQUEST)

            # Обновление существующего сообщения
            if core_message_id:
                return self._update_existing_message(
                    bot_tag=bot_tag,
                    core_message_id=core_message_id,
                    telegram_message_id=telegram_message_id,
                    content=text,
                    metadata=metadata,
                    reply_to_message_id=reply_to_message_id
                )

            # Создание нового сообщения
            if not assistant_slug:
                raise AuthenticationError("Missing 'assistant_slug' in request",
                                          status_code=status.HTTP_400_BAD_REQUEST)

            return self._create_new_message(
                bot_tag=bot_tag,
                telegram_message_id=telegram_message_id,
                text=text,
                metadata=metadata,
                assistant_slug=assistant_slug,
                user=user,
                reply_to_message_id=reply_to_message_id,
            )

        except AuthenticationError as e:
            self.logger.warning(f"{bot_tag} Authentication error: {str(e)}")
            return {
                "payload": {"detail": str(e)},
                "response_status": e.status_code
            }
        except UserNotFoundError as e:
            self.logger.warning(f"{bot_tag} User not found: {str(e)}")
            return {
                "payload": {"detail": str(e)},
                "response_status": e.status_code
            }
        except Exception as e:
            self.logger.exception(f"{bot_tag} Unexpected error: {str(e)}")
            return {
                "payload": {"detail": "Internal server error"},
                "response_status": status.HTTP_500_INTERNAL_SERVER_ERROR
            }

    def _update_existing_message(
            self,
            bot_tag: str,
            core_message_id: Union[int, str],
            telegram_message_id: Union[int, str],
            content: str,
            metadata: Dict[str, Any],
            reply_to_message_id: Optional[Union[int, str]],
    ) -> dict:
        """Обновляет существующее AI-сообщение через MessageService"""
        try:
            # Получаем сообщение через ORM
            message = Message.objects.select_related("chat").get(
                id=core_message_id,
                is_ai=True,
                sender=None,
                source_type=MessageSource.TELEGRAM,
            )

            # Обновляем метаданные и контент через сервис
            updated_message = self.message_service.update_ai_message_metadata(
                message=message,
                telegram_message_id=telegram_message_id,
                content=content,
                metadata=metadata
            )

            # Обновляем reply_to если нужно
            if reply_to_message_id:
                reply_to_message = self.message_service.get_telegram_message_by_id(
                    chat=updated_message.chat,
                    telegram_message_id=reply_to_message_id
                )
                if reply_to_message:
                    updated_message.reply_to = reply_to_message
                    updated_message.save(update_fields=["reply_to"])
                    self.logger.info(
                        f"{bot_tag} AI message core_id={core_message_id} set reply_to={reply_to_message.id}"
                    )

            self.logger.info(
                f"{bot_tag} Updated AI message: core_id={core_message_id}, telegram_id={telegram_message_id}"
            )

            return {
                "payload": {"core_message_id": updated_message.pk},
                "response_status": status.HTTP_200_OK,
            }

        except Message.DoesNotExist:
            raise MessageNotFoundError(f"AI message with ID {core_message_id} not found", core_message_id)
        except Exception as e:
            raise AuthenticationError(f"Error updating AI message: {str(e)}")

    def _create_new_message(
            self,
            bot_tag: str,
            telegram_message_id: Union[str, int],
            text: str,
            metadata: Dict[str, Any],
            assistant_slug: str,
            user: User,
            reply_to_message_id: str,
    ) -> dict:
        """Создает новое AI-сообщение через другие сервисы"""
        try:
            # 1. Получаем или создаем чат через ChatService
            chat = self.chat_service.get_or_create_chat(
                user=user,
                platform=ChatPlatform.TELEGRAM,
                assistant_slug=assistant_slug,
                api_tag=bot_tag
            )

            # 2. Проверяем на дубликаты
            existing_message = Message.objects.filter(
                source_type=MessageSource.TELEGRAM,
                metadata__telegram__message_id=str(telegram_message_id),
                chat=chat,
                is_ai=True
            ).first()

            if existing_message:
                self.logger.info(
                    f"{bot_tag} Duplicate AI message found: telegram_id={telegram_message_id}, "
                    f"Message id={existing_message.pk}"
                )
                return {
                    "payload": {
                        "core_message_id": existing_message.pk,
                        "chat_id": chat.id,
                        "duplicate": True
                    },
                    "response_status": status.HTTP_200_OK,
                }

            # 3. Находим сообщение для ответа
            reply_to_message = None
            if reply_to_message_id:
                reply_to_message = self.message_service.get_telegram_message_by_id(
                    chat=chat,
                    telegram_message_id=reply_to_message_id
                )

            # 4. Создаем сообщение через MessageService
            new_message = self.message_service.create_telegram_ai_message(
                chat=chat,
                content=text,
                telegram_message_id=telegram_message_id,
                reply_to=reply_to_message,
                metadata=metadata
            )

            self.logger.info(
                f"{bot_tag} Created new AI message: core_id={new_message.pk}, "
                f"telegram_id={telegram_message_id}, chat_id={chat.id}"
            )

            return {
                "payload": {
                    "core_message_id": new_message.pk,
                },
                "response_status": status.HTTP_201_CREATED,
            }

        except Exception as e:
            self.logger.exception(f"{bot_tag} Error creating AI message: {str(e)}")
            raise AuthenticationError(f"Error creating AI message: {str(e)}")
