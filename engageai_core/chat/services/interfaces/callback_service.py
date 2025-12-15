from typing import Optional, Union

from django.contrib.auth import get_user_model
from chat.models import Message, MessageSource, Chat
from chat.services.interfaces.base_service import BaseService
from chat.services.interfaces.exceptions import MessageCreationError
from chat.services.interfaces.message_service import MessageService
from utils.setup_logger import setup_logger

User = get_user_model()
logger = setup_logger(name=__name__, log_dir="logs/core_services", log_file="callback_service.log")


class CallbackService(BaseService):
    """Сервис для обработки callback-запросов от inline-кнопок"""

    def create_callback_message(
            self,
            chat: Chat,
            user: User,
            callback_data: dict,
            update_id: Union[str, int],
            original_message: Optional[Message] = None
    ) -> Message:
        """
        Создает сообщение для callback

        Raises:
            MessageCreationException: При ошибке создания сообщения
        """
        try:
            callback_id = callback_data.get("id")
            callback_data_value = callback_data.get("data", "")
            message_data = callback_data.get("message", {})

            # Формируем содержимое для callback-сообщения
            content = f"({callback_data_value})"
            button_text = self._get_button_text_from_dict(callback_data)
            if button_text:
                content = f"{button_text} {content}"

            # Создаем сообщение
            message_service = MessageService()

            message = message_service.create_user_message(
                chat=chat,
                sender=user,
                content=content,
                message_type="text",
                source_type=MessageSource.TELEGRAM,
                external_id=str(update_id),
                metadata={"telegram": {"callback": callback_data}},
                reply_to=original_message
            )

            logger.info(f"Создано callback-сообщение {message.pk} для update_id {update_id}")
            return message

        except Exception as e:
            logger.exception(f"Ошибка создания callback-сообщения для update_id {update_id}: {str(e)}")
            raise MessageCreationError(f"Ошибка создания callback-сообщения: {str(e)}")

    def _get_button_text_from_dict(self, callback: dict) -> Optional[str]:
        """Возвращает текст кнопки по callback_data из словаря апдейта."""
        data = callback.get("data")
        message = callback.get("message", {})
        reply_markup = message.get("reply_markup", {})
        keyboard = reply_markup.get("inline_keyboard", [])

        for row in keyboard:
            for button in row:
                if button.get("callback_data") == data:
                    return button.get("text")
        return None
