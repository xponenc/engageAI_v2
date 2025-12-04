from typing import Optional

from engageai_core.chat.models import Message, MessageSource


class TelegramMessageService:
    """
    Сервис для работы с AI-сообщениями на стороне core.

    Обеспечивает единый формат metadata, аналогичный Telegram Update,
    хранит reply_to и source_core_db_id для связи с бизнес-логикой.
    """

    @staticmethod
    def create_ai_message(chat, content: str, reply_to: Optional[Message] = None,
                          source_core_db_id: Optional[int] = None, sender=None) -> Message:
        """
        Создаёт AI-сообщение в базе core с минимальным metadata.

        Args:
            chat: объект Chat, куда относится сообщение
            content: текст сообщения
            reply_to: объект Message, на который это сообщение отвечает
            source_core_db_id: ID объекта в core (например, вопрос)
            sender: пользователь, отправитель (может быть None для AI)

        Returns:
            Message: созданное сообщение
        """
        return Message.objects.create(
            chat=chat,
            content=content,
            is_ai=True,
            sender=sender,
            source_type=MessageSource.TELEGRAM,
            reply_to=reply_to,
            metadata={
                "telegram": {
                    "update_id": None,
                    "message_id": None,
                    "reply_to_id": reply_to.id if reply_to else None,
                    "source_core_db_id": source_core_db_id,
                    "user": {"id": sender.id} if sender else None,
                    "raw": {}
                }
            }
        )

    @staticmethod
    def update_ai_message_metadata(message: Message, update_id: Optional[int] = None,
                                   message_id: Optional[int] = None, extra_metadata: dict = None) -> Message:
        """
        Обновляет metadata AI-сообщения после отправки пользователю и получения update_id.

        Args:
            message: объект Message для обновления
            update_id: Telegram update_id (если есть)
            message_id: Telegram message_id (если есть)
            extra_metadata: дополнительные данные для вложения в metadata["telegram"]

        Returns:
            Message: обновлённое сообщение
        """
        tg_meta = message.metadata.get("telegram", {})
        if update_id:
            tg_meta["update_id"] = update_id
        if message_id:
            tg_meta["message_id"] = str(message_id)
        if extra_metadata:
            tg_meta.update(extra_metadata)
        message.metadata["telegram"] = tg_meta
        message.save(update_fields=["metadata"])
        return message
