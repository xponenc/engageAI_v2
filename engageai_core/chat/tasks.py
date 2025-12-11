# tasks.py
import mimetypes
import os
import tempfile
from io import BytesIO
from django.core.files import File
from django.core.files.temp import NamedTemporaryFile
from PIL import Image
from requests.exceptions import RequestException
from celery import shared_task
from celery.utils.log import get_task_logger
from .models import MediaFile, Message
from .services.telegram_bot_services import TelegramBotService

logger = get_task_logger(__name__)

THUMBNAIL_SIZE = (128, 128)  # Размер миниатюр


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_telegram_media(self, message_id, file_data, bot_token):
    """
    Фоновая задача для загрузки медиа из Telegram и сохранения в MediaFile
    """
    try:
        message = Message.objects.get(id=message_id)
        bot_service = TelegramBotService(bot_token)

        # 1. Получаем информацию о файле от Telegram
        file_info = bot_service.get_file(file_data['file_id'])
        file_path = file_info['file_path']
        file_url = bot_service.get_file_url(file_path)

        # 2. Скачиваем файл
        try:
            file_content = bot_service.download_file(file_url)
        except RequestException as e:
            logger.error(f"Ошибка загрузки файла {file_path}: {str(e)}")
            raise self.retry(exc=e)

        # 3. Определяем параметры файла
        file_name = os.path.basename(file_path)
        mime_type = file_data.get('mime_type') or mimetypes.guess_type(file_name)[0] or 'application/octet-stream'
        file_size = len(file_content)

        # 4. Создаем запись в БД
        media_file = MediaFile.objects.create(
            message=message,
            file_type=file_data['file_type'],
            mime_type=mime_type,
            size=file_size,
            external_id=file_data['file_id'],
            created_by=message.sender,
            ai_generated=False
        )

        # 5. Сохраняем основной файл
        with tempfile.NamedTemporaryFile() as temp_file:
            temp_file.write(file_content)
            temp_file.flush()
            media_file.file.save(file_name, File(temp_file), save=False)

        should_generate_thumbnail = (
                file_data['file_type'] == 'image' or
                mime_type.startswith('image/') or
                file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'))
        )

        if should_generate_thumbnail:
            try:
                generate_thumbnail(media_file, file_content)
            except Exception as e:
                logger.error(f"Ошибка генерации миниатюры для {file_name}: {str(e)}")

        media_file.save()
        logger.info(f"Успешно обработан медиафайл {media_file.id} для сообщения {message_id}")
        return media_file.id

    except Message.DoesNotExist:
        logger.error(f"Сообщение {message_id} не найдено")
    except Exception as e:
        logger.exception(f"Критическая ошибка обработки медиа: {str(e)}")
        raise self.retry(exc=e)


def generate_thumbnail(media_file, original_content):
    """Генерация миниатюры для изображения с валидацией"""
    try:
        img = Image.open(BytesIO(original_content))

        # Проверяем, что это действительно изображение
        if img.format not in ['JPEG', 'PNG', 'GIF', 'BMP', 'WEBP']:
            logger.warning(f"Формат изображения {img.format} не поддерживается для миниатюр")
            return

        # Конвертируем в RGB если необходимо
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')

        # Создаем миниатюру
        img.thumbnail(THUMBNAIL_SIZE)

        # Сохраняем в буфер
        thumb_io = BytesIO()
        img.save(thumb_io, format='JPEG', quality=85)
        thumb_io.seek(0)

        # Формируем имя файла для миниатюры
        original_name = os.path.splitext(os.path.basename(media_file.file.name))[0]
        thumb_name = f"{original_name}_thumb.jpg"

        # Сохраняем миниатюру
        media_file.thumbnail.save(thumb_name, File(thumb_io), save=False)

        return True
    except Exception as e:
        logger.error(f"Ошибка при генерации миниатюры: {str(e)}")
        return False