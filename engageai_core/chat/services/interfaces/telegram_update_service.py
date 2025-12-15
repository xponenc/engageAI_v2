from django.contrib.auth import get_user_model
from django.db import transaction

from chat.models import Message, ChatPlatform, MessageType, MessageSource, ChatScope, Chat
from chat.services.interfaces.base_service import BaseService
from chat.services.interfaces.callback_service import CallbackService
from chat.services.interfaces.chat_service import ChatService
from chat.services.interfaces.exceptions import TelegramAPIException, MessageNotFoundError, ServiceError
from chat.services.interfaces.media_service import MediaService
from chat.services.interfaces.message_service import MessageService

User = get_user_model()


class TelegramUpdateService(BaseService):
    """Сервис для обработки Telegram-апдейтов"""

    def __init__(self):
        super().__init__()
        self.chat_service = ChatService()
        self.message_service = MessageService()
        self.media_service = MediaService()
        self.callback_service = CallbackService()

    @transaction.atomic
    def process_update(
            self,
            update_data: dict,
            assistant_slug: str,
            user: 'User',
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
            dict: Результат обработки

        Raises:
            ServiceException: При ошибках обработки
        """
        update_id = update_data.get("update_id")
        if not update_id:
            self.logger.warning(f"{bot_tag} Отсутствует 'update_id' в апдейте")
            raise TelegramAPIException("Missing update data", status_code=400)

        # Проверка дубликата
        if Message.objects.filter(external_id=str(update_id), source_type=MessageSource.TELEGRAM).exists():
            self.logger.info(f"{bot_tag} Апдейт {update_id} уже обработан")
            return {"core_message_id": None, "duplicate": True}

        try:
            self.logger.debug(f"{bot_tag} Начало обработки апдейта {update_id}, типы: {list(update_data.keys())}")

            if "message" in update_data:
                return self._process_message(
                    update_data["message"],
                    update_id,
                    bot_tag,
                    assistant_slug,
                    user
                )
            elif "edited_message" in update_data:
                return self._process_edited_message(
                    update_data["edited_message"],
                    bot_tag,
                    assistant_slug,
                    user
                )
            elif "callback_query" in update_data:
                return self._process_callback(
                    update_data["callback_query"],
                    update_id,
                    bot_tag,
                    assistant_slug,
                    user
                )
            else:
                raise TelegramAPIException(f"Unsupported update type: {list(update_data.keys())}")

        except ServiceError:
            # Пробрасываем кастомные исключения дальше
            raise
        except Exception as e:
            self.logger.exception(f"{bot_tag} Непредвиденная ошибка при обработке апдейта {update_id}: {str(e)}")
            raise TelegramAPIException(f"Internal server error: {str(e)}")

    def _process_message(self, message_data: dict, update_id: int, bot_tag: str, assistant_slug: str,
                         user: User) -> dict:
        """Обработка обычного сообщения с поддержкой альбомов"""
        try:
            media_group_id = message_data.get("media_group_id")

            # Получаем чат через сервис
            chat = self.chat_service.get_or_create_chat(
                user=user,
                platform=ChatPlatform.TELEGRAM,
                scope=ChatScope.PRIVATE,
                assistant_slug=assistant_slug,
                api_tag=bot_tag
            )

            message = None
            if media_group_id:
                # Обработка альбома
                message = self._process_album(
                    chat,
                    user,
                    media_group_id,
                    update_id,
                    message_data,
                    bot_tag
                )
            else:
                # Обработка обычного сообщения
                message = self._process_single_message(
                    chat,
                    user,
                    message_data,
                    update_id,
                    bot_tag
                )

            return {"core_message_id": message.pk}

        except Exception as e:
            self.logger.exception(f"{bot_tag} Ошибка обработки сообщения: {str(e)}")
            raise

    def _process_album(self, chat: Chat, user: User, media_group_id: str, update_id: int, message_data: dict,
                       bot_tag: str) -> Message:
        """Обработка альбома медиафайлов"""
        try:
            # Пытаемся найти уже созданное сообщение для этого альбома
            album_message = self.message_service.get_album_message(chat, media_group_id)

            if album_message:
                # Если сообщение найдено, проверяем, нужно ли обновить подпись
                current_caption = message_data.get("caption") or message_data.get("text", "")
                if current_caption and not album_message.content:
                    # Обновляем подпись для всего альбома
                    album_message.content = current_caption
                    album_message.save()
                    self.logger.info(f"Обновлена подпись для альбома {media_group_id}")
                return album_message

            # Создаем новое сообщение для альбома
            caption = message_data.get("caption") or message_data.get("text", "")
            return self.message_service.create_album_message(
                chat=chat,
                user=user,
                media_group_id=media_group_id,
                caption=caption,
                first_update_id=update_id,
                message_data=message_data
            )

        except Exception as e:
            self.logger.exception(f"Ошибка обработки альбома {media_group_id}: {str(e)}")
            raise

    def _process_single_message(self, chat: 'Chat', user: 'User', message_data: dict, update_id: int,
                                bot_tag: str) -> 'Message':
        """Обработка обычного сообщения"""
        try:
            message_id = message_data.get("message_id")
            text = message_data.get("text", "")
            media_type = self.message_service.determine_message_type(message_data)

            # Если есть медиа, но нет текста - установить содержимое по умолчанию
            if not text and media_type != MessageType.TEXT:
                text = self.message_service.get_default_content_for_media(media_type, message_data)

            # Создаем сообщение
            message = self.message_service.create_user_message(
                chat=chat,
                sender=user,
                content=text,
                message_type=media_type,
                source_type=MessageSource.TELEGRAM,
                external_id=update_id,
                metadata={"telegram": {
                    "message_id": str(message_id) if message_id else None,
                    "update_id": str(update_id),
                    "raw": message_data
                }}
            )

            # Обрабатываем медиафайлы
            media_tasks = self.media_service.prepare_media_tasks(message_data)
            if media_tasks:
                self.media_service.process_media_for_message(message, media_tasks, bot_tag)

            return message

        except Exception as e:
            self.logger.exception(f"Ошибка обработки обычного сообщения: {str(e)}")
            raise

    def _process_edited_message(self, edited_data: dict, bot_tag: str, assistant_slug: str, user: 'User') -> dict:
        """Обработка отредактированного сообщения"""
        message_id = str(edited_data.get("message_id", ""))
        new_text = edited_data.get("text", "")

        # Получаем чат через сервис
        chat = self.chat_service.get_or_create_chat(
            user=user,
            assistant_slug=assistant_slug,
            platform=ChatPlatform.TELEGRAM,
            scope=ChatScope.PRIVATE,
            api_tag=bot_tag
        )

        # Находим сообщение по Telegram ID
        message = self.message_service.find_message_by_telegram_id(chat, message_id)
        if not message:
            self.logger.warning(f"{bot_tag} Редактирование несуществующего сообщения {message_id}")
            raise MessageNotFoundError(message_id=message_id)

        # Обновляем содержимое
        updated_message = self.message_service.update_message_content(
            message.pk,
            new_text,
            user.id
        )

        return {
            "core_message_id": updated_message.id,
            "edit_count": updated_message.edit_count
        }

    def _process_callback(self, callback_data: dict, update_id: int, bot_tag: str, assistant_slug: str,
                          user: 'User') -> dict:
        """Обработка callback query от inline-кнопок"""
        # Получаем чат через сервис
        chat = self.chat_service.get_or_create_platform_chat(
            user=user,
            assistant_slug=assistant_slug,
            platform=ChatPlatform.TELEGRAM,
            bot_tag=bot_tag
        )

        # Поиск исходного сообщения
        original_message = None
        message_data = callback_data.get("message", {})
        original_message_id = message_data.get("message_id")

        if original_message_id:
            original_message = self.message_service.find_message_by_telegram_id(chat, original_message_id)
            if not original_message:
                self.logger.warning(f"{bot_tag} Не найдено исходное сообщение {original_message_id} для callback")

        # Создаем callback-сообщение
        callback_message = self.callback_service.create_callback_message(
            chat=chat,
            user=user,
            callback_data=callback_data,
            update_id=update_id,
            original_message=original_message
        )

        return {
            "core_message_id": callback_message.pk,
            "callback_id": callback_data.get("id")
        }
