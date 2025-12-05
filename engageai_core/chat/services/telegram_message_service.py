from typing import Optional, Dict, Any, Tuple, Union

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import F
from django.db.models.expressions import CombinedExpression
from django.utils import timezone
from rest_framework import status

from ai_assistant.models import AIAssistant
from engageai_core.chat.models import Message, MessageSource, Chat, ChatPlatform
from utils.setup_logger import setup_logger

User = get_user_model()


core_api_logger = setup_logger(name=__file__, log_dir="logs/core_api", log_file="core_api.log")


class TelegramUpdateService:
    """Сервис для обработки Telegram-апдейтов"""

    @transaction.atomic
    def process_update(
            self,
            update_data: dict,
            assistant_slug: str,
            user: User,
            bot_tag: str
    ) -> dict:
        """
        Обрабатывает Telegram-апдейт и возвращает результат

        Args:
            update_data: Данные апдейта от Telegram
            assistant_slug: Slug AI-ассистента
            user: Объект пользователя
            bot_tag: Идентификатор бота для логирования

        Returns:
            Tuple[bool, Union[dict, str]]: (успех, результат или сообщение об ошибке)
        """
        update_id = update_data.get("update_id")
        if not update_id:
            core_api_logger.warning(f"{bot_tag} Отсутствует update_id в апдейте")
            return {
                "success": False,
                "payload": {
                    "detail": "Missing update data"
                },
                "response_status": status.HTTP_400_BAD_REQUEST
            }

        # Проверка дубликата
        if Message.objects.filter(external_id=str(update_id), source_type=MessageSource.TELEGRAM).exists():
            core_api_logger.info(f"{bot_tag} Апдейт {update_id} уже обработан")
            return {
                "success": True,
                "payload": {
                    "detail": "Update already processed"
                },
                "response_status": status.HTTP_400_BAD_REQUEST
            }

        # Определение типа апдейта и делегирование обработки
        try:
            core_api_logger.debug(
                f"{bot_tag} Начало обработки апдейта {update_id}, типы: {list(update_data.keys())}")
            if "message" in update_data:
                return self._process_message(update_data["message"], update_id, bot_tag, assistant_slug, user)
            elif "edited_message" in update_data:
                return self._process_edited_message(update_data["edited_message"], bot_tag, assistant_slug, user)
            elif "callback_query" in update_data:
                return self._process_callback(update_data["callback_query"], update_id, bot_tag, assistant_slug, user)

        except ObjectDoesNotExist as e:
            core_api_logger.error(f"{bot_tag} Ошибка поиска объекта при обработке апдейта {update_id}: {str(e)}")
            return {
                "success": False,
                "payload": {
                    "detail": "Required object not found: {str(e)}"
                },
                "response_status": status.HTTP_400_BAD_REQUEST
            }
        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Непредвиденная ошибка при обработке апдейта {update_id}: {str(e)}")
            return {
                "success": False,
                "payload": {
                    "detail": "Internal server error"
                },
                "response_status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            }

    def _process_message(self, message_data: dict, update_id: int, bot_tag: str, assistant_slug: str, user: User):
        """Обработка обычного сообщения"""
        try:
            message_id = message_data.get("message_id")
            text = message_data.get("text", "")

            chat = self._get_or_create_chat(user, assistant_slug, bot_tag)
            if isinstance(chat, dict):
                return chat

            message = TelegramMessageService.create_message_from_update(
                chat=chat,
                sender=user,
                content=text,
                update_id=update_id,
                message_id=message_id,
                extra_metadata=message_data
            )

            core_api_logger.info(f"{bot_tag} Создано сообщение ID {message.id} из апдейта {update_id}")
            return {
                "success": True,
                "payload": {
                    "core_message_id": message.id,
                },
                "response_status": status.HTTP_201_CREATED,
            }

        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Ошибка создания сообщения: {str(e)}")
            return {
                "success": False,
                "payload": {
                    "detail": f"Error creating message: {str(e)}"
                },
                "response_status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            }

    def _process_edited_message(self, edited_data: dict, bot_tag: str, assistant_slug: str, user: User):
        """Обработка отредактированного сообщения"""
        """Обрабатывает отредактированное сообщение"""
        message_id = str(edited_data.get("message_id", ""))
        new_text = edited_data.get("text", "")

        # Получение чата
        chat = self._get_or_create_chat(user=user, assistant_slug=assistant_slug, bot_tag=bot_tag)
        if isinstance(chat, dict):
            return chat

        try:
            # Поиск сообщения по message_id
            message = Message.objects.get(
                metadata__telegram__message_id=str(message_id),
                chat=chat,
                source_type=MessageSource.TELEGRAM
            )

            # Обновление содержимого и метаданных
            old_content = message.content
            message.content = new_text
            message.edited_at = timezone.now()

            # Обновляем метаданные с информацией о редактировании
            metadata = message.metadata or {}
            if "edit_history" not in metadata:
                metadata["edit_history"] = []

            metadata["edit_history"].append({
                "timestamp": timezone.now().isoformat(),
                "old_content": old_content,
                "new_content": new_text,
                "editor_id": user.id
            })

            # Обновляем счётчик редактирований
            message.edit_count = F("edit_count") + 1
            message.metadata = metadata
            message.save(update_fields=["content", "edited_at", "edit_count", "metadata"])

            core_api_logger.info(f"{bot_tag} Обновлено сообщение ID {message.id}, версия {message.edit_count + 1}")
            return {
                "success": True,
                "payload": {
                    "message_id": message.id,
                    "chat_id": chat.id,
                    "edit_count": message.edit_count + 1
                },
                "response_status": status.HTTP_200_OK
            }

        except Message.DoesNotExist:
            core_api_logger.warning(f"{bot_tag} Редактирование несуществующего сообщения {message_id}")
            return {
                "success": False,
                "payload": {
                    "detail": f"Message with ID {message_id} not found"
                },
                "response_status": status.HTTP_404_NOT_FOUND
            }
        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Ошибка редактирования сообщения {message_id}: {str(e)}")
            return {
                "success": False,
                "payload": {
                    "detail": f"Error editing message: {str(e)}"
                },
                "response_status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            }

    def _process_callback(self, callback_data: dict, update_id: int, bot_tag: str, assistant_slug: str, user: User):
        """Обрабатывает callback query от inline-кнопок"""
        message_data = callback_data.get("message")
        callback_id = callback_data.get("id")
        callback_data_value = callback_data.get("data")

        # Получение чата
        chat = self._get_or_create_chat(user=user, assistant_slug=assistant_slug, bot_tag=bot_tag)
        if isinstance(chat, dict):
            return chat

        # Поиск исходного сообщения
        original_message = None
        if message_data:
            original_message_id = message_data.get("message_id")
            if not original_message_id:
                core_api_logger.error(f"{bot_tag} Callback query не содержит message_id: {callback_data}")
                return {
                    "success": False,
                    "payload": {
                         "detail": "Missing message_id in callback query"
                    },
                    "response_status": status.HTTP_400_BAD_REQUEST,
                }
            try:
                original_message = Message.objects.get(
                    metadata__telegram__message_id=str(original_message_id),
                    chat=chat,
                    source_type=MessageSource.TELEGRAM
                )
            except Message.DoesNotExist:
                core_api_logger.warning(
                    f"{bot_tag} Не найдено исходное сообщение {original_message_id} для callback {callback_id}")

        # Создание сообщения для callback
        try:
            content = f"[Callback: {callback_data_value}]"

            callback_message = TelegramMessageService.create_message_from_update(
                chat=chat,
                sender=user,
                content=content,
                update_id=update_id,
                message_id=callback_id,
                extra_metadata=callback_data,
                reply_to=original_message
            )

            core_api_logger.info(
                f"{bot_tag} Создан callback-сообщение ID {callback_message.id} для update_id {update_id}")

            return {
                "success": True,
                "payload": {
                    "message_id": callback_message.id,
                    "chat_id": chat.id,
                    "callback_id": callback_id
                },
                "response_status": status.HTTP_201_CREATED,
            }

        except Exception as e:
            core_api_logger.exception(
                f"{bot_tag} Ошибка создания callback-сообщения для update_id {update_id}: {str(e)}")
            return {
                "success": False,
                "payload": {
                    "detail": f"Error creating callback message: {str(e)}"
                },
                "response_status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            }


    def _get_or_create_chat(self, user: User, assistant_slug: str, bot_tag: str) -> Union[Chat, dict]:
        """Получение или создание чата для пользователя"""
        try:
            assistant = AIAssistant.objects.get(slug=assistant_slug, is_active=True)
            chat, created = Chat.get_or_create_ai_chat(
                user=user,
                ai_assistant=assistant,
                platform=ChatPlatform.TELEGRAM,
                title=f"Telegram Чат с {assistant.name}",
            )

            if created:
                chat.participants.add(user)
                core_api_logger.info(f"{bot_tag} Создан новый AI-чат {chat.id} для пользователя {user.id}")

            return chat

        except AIAssistant.DoesNotExist:
            core_api_logger.error(f"{bot_tag} Ассистент с slug {assistant_slug} не найден")
            return {
                "success": False,
                "payload": {
                     "detail": f"Assistant with slug '{assistant_slug}' not found"
                },
                "response_status": status.HTTP_404_NOT_FOUND
            }

        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Ошибка при получении/создании чата: {str(e)}")
            return {
                "success": False,
                "payload": {
                    "detail": f"Error getting/creating chat: {str(e)}"
                },
                "response_status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            }


class TelegramMessageService:
    """
     Сервис для работы с сообщениями Telegram в core-системе.

    """

    @staticmethod
    def create_ai_message(
        chat: Chat,
        content: str,
        message_id: Optional[str, int] = None,
        reply_to: Optional[Message] = None,
        extra_metadata: Optional[Dict[str, Any]] = None
    ) -> Message:
        """
        Создаёт по telegram сообщению объект chat.models.Message от AI в базе core с metadata.

        Args:
            chat: Объект Chat, в который добавляется сообщение
            content: Текст сообщения
            message_id: ID сообщения в Telegram (optional)
            reply_to: Объект Message, на который отвечает это сообщение (optional)
            extra_metadata: Дополнительные метаданные от Telegram API (optional)

        Returns:
            Message: созданное сообщение с типом source_type=MessageSource.TELEGRAM и  is_ai=True
        """
        telegram_metadata = {}
        if message_id:
            telegram_metadata["message_id"] = str(message_id)

        # Добавляем raw-данные от Telegram, если они есть
        if extra_metadata and "raw" in extra_metadata:
            telegram_metadata["raw"] = extra_metadata["raw"]

        # Другие метаданные Telegram
        telegram_keys = ["entities", "chat", "user", "callback_query_id", "callback_data"]
        for key in telegram_keys:
            if extra_metadata and key in extra_metadata:
                telegram_metadata[key] = extra_metadata[key]


        return Message.objects.create(
            chat=chat,
            content=content,
            is_ai=True,
            sender=None,
            source_type=MessageSource.TELEGRAM,
            reply_to=reply_to,
            metadata={
                "telegram": telegram_metadata
            }
        )

    @staticmethod
    def update_ai_message_metadata(
        message: Message,
        message_id: Optional[str, int],
        extra_metadata: dict = None
    ) -> Message:
        """
        Обновляет metadata объекта chat.models.Message AI-сообщения после ботом сообщения пользователю
        и получения данных о нем на api.

        Args:
            message: объект Message для обновления
            message_id: Telegram message_id (если есть)
            extra_metadata: дополнительные данные для вложения в metadata["telegram"]

        Returns:
            Message: обновлённое сообщение
        """
        telegram_metadata = message.metadata.get("telegram", {}) if message.metadata else {}

        if message_id:
            telegram_metadata["message_id"] = str(message_id)

        if extra_metadata:
            telegram_metadata["raw"] = extra_metadata

            telegram_keys = ["entities", "chat", "user", "callback_query_id", "callback_data"]
            for key in telegram_keys:
                if extra_metadata and key in extra_metadata:
                    telegram_metadata[key] = extra_metadata[key]

        message.metadata["telegram"] = telegram_metadata
        message.save(update_fields=["metadata"])
        return message


    @staticmethod
    def create_message_from_update(
            chat: Chat,
            sender: User,
            content: str,
            update_id: Optional[str, int],
            message_id: Optional[str, int],
            extra_metadata: Optional[Dict[str, Any]],
            reply_to: Optional[Message] = None,
    ) -> Message:
        """
        Создаёт объект chat.models.Message из Telegram-апдейта, полученного по webhook.

        Args:
            chat: Чат, в который добавляется сообщение
            sender: Пользователь, отправивший сообщение
            content: Текст сообщения
            update_id: ID обновления в Telegram
            message_id: ID сообщения в Telegram
            extra_metadata: Сырые данные от Telegram API (включая "raw")
            reply_to: Объект Message, на который отвечает это сообщение (optional)

        Returns:
            Message: Созданное сообщение от пользователя
        """


        # Формируем метаданные
        telegram_metadata = {
            "message_id": str(message_id),
            "update_id": str(update_id)
        }

        # Добавляем raw-данные от Telegram, если они есть
        if "raw" in extra_metadata:
            telegram_metadata["raw"] = extra_metadata["raw"]

        # Другие метаданные Telegram
        telegram_keys = ["entities", "chat", "user", "callback_query_id", "callback_data"]
        for key in telegram_keys:
            if extra_metadata and key in extra_metadata:
                telegram_metadata[key] = extra_metadata[key]

        return Message.objects.create(
            chat=chat,
            content=content,
            sender=sender,
            source_type=MessageSource.TELEGRAM,
            external_id=update_id,
            reply_to=reply_to,
            metadata={
                "telegram": telegram_metadata
            }
        )
