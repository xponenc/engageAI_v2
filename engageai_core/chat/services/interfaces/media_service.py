from chat.models import Message
from chat.services.interfaces.base_service import BaseService
from chat.services.interfaces.exceptions import MediaProcessingError


class MediaService(BaseService):
    """Сервис для обработки медиафайлов"""

    def prepare_media_tasks(self, message_data: dict, is_album: bool = False) -> list:
        """Подготавливает задачи для обработки медиа из сообщения"""
        media_tasks = []

        # Обработка разных типов медиа
        if photo := message_data.get("photo"):
            media_tasks.append(self._prepare_photo_task(photo[-1], message_data.get("caption", "")))

        if document := message_data.get("document"):
            media_tasks.append(self._prepare_document_task(document, message_data.get("caption", "")))

        if audio := message_data.get("audio") or message_data.get("voice"):
            media_tasks.append(self._prepare_audio_task(
                audio or message_data.get("voice"),
                message_data.get("caption", "")
            ))

        if video := message_data.get("video") or message_data.get("animation"):
            media_tasks.append(self._prepare_video_task(
                video or message_data.get("animation"),
                message_data.get("caption", "")
            ))

        if sticker := message_data.get("sticker"):
            media_tasks.append(self._prepare_sticker_task(sticker))

        return media_tasks

    def process_media_for_message(self, message: Message, media_tasks: list, bot_tag: str):
        """Запускает обработку медиа для сообщения"""
        for task_data in media_tasks:
            self._enqueue_media_task(message.pk, task_data, bot_tag)

    def _prepare_photo_task(self, photo_size: dict, caption: str = "") -> dict:
        """Подготавливает данные для обработки фото"""
        return {
            "file_id": photo_size["file_id"],
            "file_type": "image",
            "width": photo_size.get("width"),
            "height": photo_size.get("height"),
            "caption": caption
        }

    def _prepare_document_task(self, document: dict, caption: str = "") -> dict:
        """Подготавливает данные для обработки документа"""
        mime_type = document.get("mime_type", "")
        file_name = document.get("file_name", "document")
        file_type = "document"

        # Проверяем, является ли документ изображением
        if mime_type.startswith("image/") or file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
            file_type = "image"

        return {
            "file_id": document["file_id"],
            "file_type": file_type,
            "mime_type": mime_type,
            "file_name": file_name,
            "caption": caption
        }

    def _prepare_audio_task(self, audio: dict, caption: str = "") -> dict:
        """Подготавливает данные для обработки аудио"""
        return {
            "file_id": audio["file_id"],
            "file_type": "audio",
            "mime_type": audio.get("mime_type", "audio/mpeg"),
            "file_name": audio.get("file_name", "audio"),
            "duration": audio.get("duration", 0),
            "caption": caption
        }

    def _prepare_video_task(self, video: dict, caption: str = "") -> dict:
        """Подготавливает данные для обработки видео"""
        return {
            "file_id": video["file_id"],
            "file_type": "video",
            "mime_type": video.get("mime_type", "video/mp4"),
            "file_name": video.get("file_name", "video"),
            "duration": video.get("duration", 0),
            "width": video.get("width"),
            "height": video.get("height"),
            "caption": caption
        }

    def _prepare_sticker_task(self, sticker: dict) -> dict:
        """Подготавливает данные для обработки стикера"""
        return {
            "file_id": sticker["file_id"],
            "file_type": "image",
            "mime_type": "image/webp",
            "file_name": "sticker.webp",
            "width": sticker.get("width"),
            "height": sticker.get("height")
        }

    def _enqueue_media_task(self, message_id: int, task_data: dict, bot_tag: str):
        """Ставит задачу в очередь Celery для обработки медиа"""
        try:
            # Получаем токен бота по тегу (реализация должна быть в другом месте)
            from chat.services.telegram_bot_services import get_bot_by_tag
            bot = get_bot_by_tag(bot_tag)

            # Импорт задачи внутри метода для избежания циклических импортов
            from chat.tasks import process_telegram_media
            process_telegram_media.delay(
                message_id=message_id,
                file_data=task_data,
                bot_token=bot.token
            )
            self.logger.debug(f"Задача обработки медиа поставлена в очередь для сообщения {message_id}")
        except Exception as e:
            self.logger.exception(f"Ошибка постановки задачи обработки медиа в очередь: {str(e)}")
            raise MediaProcessingError(f"Ошибка постановки задачи в очередь: {str(e)}")
