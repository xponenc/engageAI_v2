import json
from typing import Optional, Dict, Any, Tuple, Union

import django
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction, IntegrityError
from django.db.models import F
from django.utils import timezone
from rest_framework import status

from ai_assistant.models import AIAssistant
from chat.models import Message, MessageSource, Chat, ChatPlatform
from utils.setup_logger import setup_logger

User = get_user_model()

core_api_logger = setup_logger(name=__file__, log_dir="logs/core_api", log_file="core_api.log")

# TODO Вадидация входящих данных
"""
def _process_message(...):
    try:
        self._validate_update_data({"message": message_data})
        # ... основная логика
    except ValueError as e:
        return {
            "payload": {"detail": str(e)},
            "response_status": status.HTTP_400_BAD_REQUEST
        }
"""

# TODO Санитизация metadata

from django.utils.html import escape


def _sanitize_metadata(metadata: dict) -> dict:
    """Санитизация метаданных перед сохранением"""
    sanitized = {}
    for key, value in metadata.items():
        # Экранирование HTML в текстовых полях
        if isinstance(value, str):
            sanitized[key] = escape(value)
        # Рекурсивная санитизация для вложенных структур
        elif isinstance(value, dict):
            sanitized[key] = _sanitize_metadata(value)
        elif isinstance(value, list):
            sanitized[key] = [_sanitize_metadata(item) if isinstance(item, dict) else escape(str(item)) for item in
                              value]
        else:
            sanitized[key] = value

    # Проверка валидности JSON
    try:
        json.dumps(sanitized)
    except (TypeError, ValueError):
        raise ValueError("Invalid metadata structure")

    return sanitized


def _validate_update_data(update_data: dict) -> None:
    """Валидация данных апдейта"""
    if not update_data:
        raise ValueError("Update data is empty")

    if not isinstance(update_data.get("update_id"), (int, str)):
        raise ValueError(f"Invalid update_id type: {type(update_data.get('update_id'))}")

    # Проверка формата message_id
    message_data = update_data.get("message")
    if message_data:
        msg_id = message_data.get("message_id")
        if msg_id is not None and not isinstance(msg_id, (int, str)):
            raise ValueError(f"Invalid message_id type: {type(msg_id)}")

        # Проверка текста
        text = message_data.get("text")
        if text is not None and not isinstance(text, str):
            raise ValueError(f"Invalid text type: {type(text)}")
        if text and len(text) > 4096:  # Максимум для Telegram
            raise ValueError("Message text exceeds Telegram limit (4096 characters)")


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
            core_api_logger.warning(f"{bot_tag} Отсутствует 'update_id' в апдейте")
            return {
                "payload": {
                    "detail": "Missing update data"
                },
                "response_status": status.HTTP_400_BAD_REQUEST
            }

        # Проверка дубликата
        if Message.objects.filter(external_id=str(update_id), source_type=MessageSource.TELEGRAM).exists():
            core_api_logger.info(f"{bot_tag} Апдейт {update_id} уже обработан")
            return {
                "payload": {
                    "detail": "Update already processed"
                },
                "response_status": status.HTTP_200_OK
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
                "payload": {
                    "detail": "Required object not found: {str(e)}"
                },
                "response_status": status.HTTP_400_BAD_REQUEST
            }
        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Непредвиденная ошибка при обработке апдейта {update_id}: {str(e)}")
            return {
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

            message = self._create_message_from_update(
                chat=chat,
                sender=user,
                content=text,
                update_id=update_id,
                message_id=message_id,
                extra_metadata=message_data
            )

            core_api_logger.info(f"{bot_tag} Создано сообщение ID {message.pk} из апдейта {update_id}")
            return {
                "payload": {
                    "core_message_id": message.pk,
                },
                "response_status": status.HTTP_201_CREATED,
            }

        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Ошибка создания сообщения: {str(e)}")
            return {
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

            if message.is_ai:
                core_api_logger.warning(
                    f"{bot_tag} Попытка редактирования AI-сообщения ID {message_id} пользователем {user.id}"
                )
                return {
                    "payload": {"detail": "Editing AI messages is not allowed"},
                    "response_status": status.HTTP_403_FORBIDDEN
                }

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

            Message.objects.filter(pk=message.pk).update(
                edit_count=F('edit_count') + 1,
                edited_at=timezone.now(),
                content=new_text,
                metadata=metadata
            )
            message.refresh_from_db(fields=['edit_count', ])

            core_api_logger.info(f"{bot_tag} Обновлено сообщение ID {message.pk}, версия {message.edit_count}")
            return {
                "payload": {
                    "core_message_id": message.pk,
                    "edit_count": message.edit_count + 1
                },
                "response_status": status.HTTP_200_OK
            }

        except ObjectDoesNotExist:
            core_api_logger.warning(f"{bot_tag} Редактирование несуществующего сообщения {message_id}")
            return {
                "payload": {
                    "detail": f"Message with ID {message_id} not found"
                },
                "response_status": status.HTTP_404_NOT_FOUND
            }
        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Ошибка редактирования сообщения {message_id}: {str(e)}")
            return {
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
                core_api_logger.error(f"{bot_tag} Callback query не содержит 'message_id': {callback_data}")
                return {
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
            except ObjectDoesNotExist:
                core_api_logger.warning(
                    f"{bot_tag} Не найдено исходное сообщение {original_message_id} для callback {callback_id}")

        # Создание сообщения для callback
        try:
            content = f"[Callback: {callback_data_value}]"

            callback_message = self._create_message_from_update(
                chat=chat,
                sender=user,
                content=content,
                update_id=update_id,
                message_id=callback_id,
                extra_metadata=callback_data,
                reply_to=original_message
            )
            if not isinstance(callback_message, Message):
                return {
                    "payload": {
                        "detail": callback_message,
                    },
                    "response_status": status.HTTP_500_INTERNAL_SERVER_ERROR,
                }

            core_api_logger.info(
                f"{bot_tag} Создан callback-сообщение ID {callback_message.pk} для update_id {update_id}")

            return {
                "payload": {
                    "core_message_id": callback_message.pk,
                    "callback_id": callback_id
                },
                "response_status": status.HTTP_201_CREATED,
            }

        except Exception as e:
            core_api_logger.exception(
                f"{bot_tag} Ошибка создания callback-сообщения для update_id {update_id}: {str(e)}")
            return {
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
                "payload": {
                    "detail": f"Assistant with slug '{assistant_slug}' not found"
                },
                "response_status": status.HTTP_404_NOT_FOUND
            }

        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Ошибка при получении/создании чата: {str(e)}")
            return {
                "payload": {
                    "detail": f"Error getting/creating chat: {str(e)}"
                },
                "response_status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            }

    @staticmethod
    def _create_message_from_update(
            chat: Chat,
            sender: User,
            content: str,
            update_id: Union[str, int],
            message_id: Union[str, int],
            extra_metadata: Dict[str, Any],
            reply_to: Optional[Message] = None,
    ) -> str | Any:
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
        telegram_metadata = {"message_id": str(message_id), "update_id": str(update_id), "raw": extra_metadata}
        # Добавляем raw-данные от Telegram, если они есть

        try:
            message = Message.objects.create(
                chat=chat,
                content=content,
                sender=sender,
                source_type=MessageSource.TELEGRAM,
                external_id=update_id,
                reply_to=None,  # Сохраняются Update от пользователя - они не считаются ответами
                metadata={
                    "telegram": telegram_metadata
                }
            )
            return message
        except django.db.utils.IntegrityError as e:
            core_api_logger.exception(e)
            return str(e)


class TelegramMessageService:
    """
     Сервис для работы с сообщениями Telegram в core-системе.

    """

    @transaction.atomic
    def process_message(
            self,
            payload: dict,
            user: User,
            bot_tag: str
    ) -> dict:
        """
        Обрабатывает AI-сообщение и возвращает результат

        Args:
            payload: Данные сообщения
            user: Объект пользователя
            bot_tag: Идентификатор бота для логирования

        Returns:
            dict
        """
        assistant_slug = payload.get("assistant_slug")
        core_message_id = payload.get("core_message_id")
        reply_to_message_id = payload.get("reply_to_message_id")
        telegram_message_id = payload.get("telegram_message_id")
        text = payload.get("text", "")
        metadata = payload.get("metadata", {})

        if not telegram_message_id:
            core_api_logger.warning(f"{bot_tag} Missing 'telegram_message_id' in request")
            return {
                "payload": {
                    "detail": f"Missing 'telegram_message_id' in request"
                },
                "response_status": status.HTTP_400_BAD_REQUEST,
            }

        if core_message_id:
            return self._update_existing_message(
                bot_tag=bot_tag,
                core_message_id=core_message_id,
                telegram_message_id=telegram_message_id,
                content=text,
                metadata=metadata,
                reply_to_message_id=reply_to_message_id
            )
        else:
            if not assistant_slug:
                core_api_logger.warning(f"{bot_tag} Missing 'assistant_slug' in request")
                return {
                    "payload": {
                        "detail": f"Missing 'assistant_slug' in request"
                    },
                    "response_status": status.HTTP_400_BAD_REQUEST,
                }

            return self._create_new_message(
                bot_tag=bot_tag,
                telegram_message_id=telegram_message_id,
                text=text,
                metadata=metadata,
                assistant_slug=assistant_slug,
                user=user,
                reply_to_message_id=reply_to_message_id,
            )

    # def _update_existing_message(
    #         self,
    #         bot_tag: str,
    #         core_message_id: str,
    #         telegram_message_id: str,
    #         content: str,
    #         metadata: Dict[str, Any],
    #         reply_to_message_id: str,
    # ):
    #     """Обновляет существующее AI-сообщение в core с привязкой к Telegram"""
    #
    #     try:
    #         try:
    #             message = Message.objects.get(
    #                 id=core_message_id,
    #                 is_ai=True,
    #                 sender=None,
    #                 source_type=MessageSource.TELEGRAM
    #             )
    #
    #         except ObjectDoesNotExist:
    #             core_api_logger.error(f"{bot_tag} AI message not found: core_id={core_message_id}")
    #             return {
    #                 "payload": {
    #                     "detail": f"AI message with ID {core_message_id} not found"
    #                 },
    #                 "response_status": status.HTTP_404_NOT_FOUND,
    #             }
    #
    #         # Обновление метаданных Telegram для AI-сообщения
    #         updated_message = self._update_ai_message_metadata(
    #             message=message,
    #             message_id=telegram_message_id,
    #             extra_metadata=metadata
    #         )
    #         if updated_message.content != content:
    #             updated_message.content = content
    #             updated_message.save(update_fields=["content", ])
    #
    #         core_api_logger.info(
    #             f"{bot_tag} Updated AI message: core_id={core_message_id}, telegram_id={telegram_message_id}"
    #         )
    #
    #         if reply_to_message_id:
    #             reply_to = Message.objects.filter(
    #                 source_type=MessageSource.TELEGRAM,
    #                 metadata__telegram__message_id=str(reply_to_message_id),
    #                 chat=message.chat,
    #             ).first()
    #             if reply_to:
    #                 message.reply_to = reply_to
    #                 message.save(update_fields=["reply_to", ])
    #                 core_api_logger.info(
    #                     f"{bot_tag} AI message: core_id={core_message_id}, telegram_id={telegram_message_id}"
    #                     f" set reply_to={reply_to.id}"
    #                 )
    #
    #         return {
    #             "payload": {
    #                 "core_message_id": updated_message.pk,
    #             },
    #             "response_status": status.HTTP_200_OK,
    #         }
    #
    #     except Exception as e:
    #         core_api_logger.exception(f"{bot_tag} Error updating AI message {core_message_id}: {str(e)}")
    #         return {
    #             "payload": {
    #                 "detail": f"Error updating AI message: {str(e)}"
    #             },
    #             "response_status": status.HTTP_500_INTERNAL_SERVER_ERROR,
    #         }

    def _update_existing_message(
            self,
            bot_tag: str,
            core_message_id: Union[int, str],
            telegram_message_id: Union[int, str],
            content: str,
            metadata: Dict[str, Any],
            reply_to_message_id: Optional[Union[int, str]],
    ):
        """
        Обновляет существующее AI-сообщение.
        Предполагается, что гонок нет — сообщение обновляется один раз после отправки Telegram-ботом.
        """

        try:
            try:
                message = (
                    Message.objects
                    .select_related("chat")
                    .get(
                        id=core_message_id,
                        is_ai=True,
                        sender=None,
                        source_type=MessageSource.TELEGRAM,
                    )
                )
            except ObjectDoesNotExist:
                core_api_logger.error(f"{bot_tag} AI message not found: core_id={core_message_id}")
                return {
                    "payload": {"detail": f"AI message with ID {core_message_id} not found"},
                    "response_status": status.HTTP_404_NOT_FOUND,
                }

            # --- Обновление metadata ---
            metadata_telegram = message.metadata.get("telegram", {}) if message.metadata else {}
            metadata_telegram["message_id"] = str(telegram_message_id)
            metadata_telegram["raw"] = metadata

            message.metadata["telegram"] = metadata_telegram
            message.timestamp = timezone.now()

            fields_to_update = ["metadata", "timestamp"]

            # обновляем только если изменилось
            if message.content != content:
                message.content = content
                fields_to_update.append("content")

            # --- Установка reply_to, если есть ---
            if reply_to_message_id:
                reply_to_id = (
                    Message.objects
                    .filter(
                        source_type=MessageSource.TELEGRAM,
                        metadata__telegram__message_id=str(reply_to_message_id),
                        chat=message.chat,
                    )
                    .only("id")
                    .values_list("id", flat=True)
                    .first()
                )

                if reply_to_id:
                    message.reply_to_id = reply_to_id
                    fields_to_update.append("reply_to")
                    core_api_logger.info(
                        f"{bot_tag} AI message core_id={core_message_id} set reply_to={reply_to_id}"
                    )

            message.save(update_fields=fields_to_update)

            core_api_logger.info(
                f"{bot_tag} Updated AI message: core_id={core_message_id}, telegram_id={telegram_message_id}"
            )

            return {
                "payload": {"core_message_id": message.pk},
                "response_status": status.HTTP_200_OK,
            }

        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Error updating AI message {core_message_id}: {str(e)}")
            return {
                "payload": {"detail": f"Error updating AI message: {str(e)}"},
                "response_status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            }

    def _create_new_message(
            self,
            bot_tag: str,
            telegram_message_id: Union[str, int],
            text: str,
            metadata: Dict[str, Any],
            assistant_slug: str,
            user: User,
            reply_to_message_id: str,
    ):
        """Создает новое AI-сообщение в core и связывает его с Telegram"""
        try:
            chat = self._get_or_create_chat(user=user, assistant_slug=assistant_slug, bot_tag=bot_tag)

            if telegram_message_id:
                existing_message = Message.objects.filter(
                    source_type=MessageSource.TELEGRAM,
                    metadata__telegram__message_id=str(telegram_message_id),
                    chat=chat,
                    is_ai=True
                ).first()

                if existing_message:
                    core_api_logger.info(
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

            if reply_to_message_id:
                reply_to = Message.objects.filter(
                    source_type=MessageSource.TELEGRAM,
                    metadata__telegram__message_id=str(reply_to_message_id),
                    chat=chat,
                ).first()
            else:
                reply_to = None

            new_message = self._create_ai_message(
                chat=chat,
                content=text,
                message_id=telegram_message_id,
                reply_to=reply_to,
                extra_metadata=metadata
            )

            core_api_logger.info(
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
            core_api_logger.exception(f"{bot_tag} Error creating AI message: {str(e)}")
            return {
                "payload": {
                    "detail": f"Error creating AI message: {str(e)}"
                },
                "response_status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            }

    def _create_ai_message(
            self,
            chat: Chat,
            content: str,
            message_id: Optional[Union[str, int]] = None,
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
        if extra_metadata:
            telegram_metadata["raw"] = extra_metadata

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

    # @staticmethod
    # def _update_ai_message_metadata(
    #         message: Message,
    #         message_id: Union[str, int],
    #         extra_metadata: Optional[dict] = None
    # ) -> Message:
    #     """
    #     Обновляет metadata объекта chat.models.Message AI-сообщения после ботом сообщения пользователю
    #     и получения данных о нем на api.
    #
    #     Args:
    #         message: объект Message для обновления
    #         message_id: Telegram message_id (если есть)
    #         extra_metadata: дополнительные данные для вложения в metadata["telegram"]
    #
    #     Returns:
    #         Message: обновлённое сообщение
    #     """
    #     telegram_metadata = message.metadata.get("telegram", {}) if message.metadata else {}
    #
    #     telegram_metadata["message_id"] = str(message_id)
    #     telegram_metadata["raw"] = extra_metadata
    #
    #     message.timestamp = timezone.now()
    #     message.metadata["telegram"] = telegram_metadata
    #     message.save(update_fields=["metadata", "timestamp"])
    #     return message

    @staticmethod
    def _get_or_create_chat(
            user: User,
            assistant_slug: str,
            bot_tag: str,
    ):
        """Получает или создает чат для пользователя с указанным ассистентом"""
        try:
            assistant = AIAssistant.objects.get(slug=assistant_slug, is_active=True)

            chat, created = Chat.get_or_create_ai_chat(
                user=user,
                ai_assistant=assistant,
                platform=ChatPlatform.TELEGRAM,
                title=f"Telegram Чат с {assistant.name}",
            )

            # Добавление пользователя в участники, если чат новый
            if created:
                chat.participants.add(user)
                core_api_logger.info(
                    f"{bot_tag} Создан новый AI-чат {chat.id} для пользователя {user.id} с ассистентом {assistant.slug}")
            else:
                core_api_logger.debug(f"{bot_tag} Найден существующий AI-чат {chat.id} для пользователя {user.id}")

            return chat

        except AIAssistant.DoesNotExist:
            core_api_logger.error(f"{bot_tag} Ассистент с slug {assistant_slug} не найден")
            return {
                "payload": {
                    "detail": f"Assistant with slug '{assistant_slug}' not found"
                },
                "response_status": status.HTTP_404_NOT_FOUND,
            }
        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Ошибка при получении/создании чата: {str(e)}")
            return {
                "payload": {
                    "detail": f"Error getting/creating chat: {str(e)}"
                },
                "response_status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            }
