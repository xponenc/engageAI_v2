import mimetypes
import os
import tempfile
from io import BytesIO
from django.core.files import File
from PIL import Image
from django.db import transaction
from requests.exceptions import RequestException
from celery import shared_task
from celery.utils.log import get_task_logger
from .models import MediaFile
from chat.services.interfaces.ai_message_service import AiMediaService
from .services.telegram_bot_services import TelegramBotService

logger = get_task_logger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_telegram_media(self, message_id, file_data, bot_token):
    """
    Фоновая задача для загрузки медиа из Telegram
    Генерация миниатюр теперь полностью асинхронна через post_save сигнал
    """
    try:
        from .models import Message

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
            ai_generated=False,
            thumbnail_generated=False  # Явно указываем, что миниатюра не сгенерирована
        )

        # 5. Сохраняем основной файл
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(file_content)
            temp_file.flush()
            # Важно: save=True для триггера post_save сигнала
            media_file.file.save(file_name, File(temp_file), save=True)

        # 6. Генерация миниатюры произойдет автоматически через post_save сигнал
        logger.info(f"Успешно обработан медиафайл {media_file.id} для сообщения {message_id}")
        return media_file.id

    except Message.DoesNotExist:
        logger.error(f"Сообщение {message_id} не найдено")
    except Exception as e:
        logger.exception(f"Критическая ошибка обработки медиа: {str(e)}")
        raise self.retry(exc=e)

#
# @shared_task(bind=True, max_retries=3, default_retry_delay=60)
# def process_telegram_media(self, message_id, file_data, bot_token):
#     """
#     Фоновая задача для загрузки медиа из Telegram и сохранения в MediaFile
#     """
#     try:
#         message = Message.objects.get(id=message_id)
#         bot_service = TelegramBotService(bot_token)
#
#         # 1. Получаем информацию о файле от Telegram
#         file_info = bot_service.get_file(file_data['file_id'])
#         file_path = file_info['file_path']
#         file_url = bot_service.get_file_url(file_path)
#
#         # 2. Скачиваем файл
#         try:
#             file_content = bot_service.download_file(file_url)
#         except RequestException as e:
#             logger.error(f"Ошибка загрузки файла {file_path}: {str(e)}")
#             raise self.retry(exc=e)
#
#         # 3. Определяем параметры файла
#         file_name = os.path.basename(file_path)
#         mime_type = file_data.get('mime_type') or mimetypes.guess_type(file_name)[0] or 'application/octet-stream'
#         file_size = len(file_content)
#
#         # 4. Создаем запись в БД
#         media_file = MediaFile.objects.create(
#             message=message,
#             file_type=file_data['file_type'],
#             mime_type=mime_type,
#             size=file_size,
#             external_id=file_data['file_id'],
#             created_by=message.sender,
#             ai_generated=False
#         )
#
#         # 5. Сохраняем основной файл
#         with tempfile.NamedTemporaryFile() as temp_file:
#             temp_file.write(file_content)
#             temp_file.flush()
#             media_file.file.save(file_name, File(temp_file), save=False)
#
#         should_generate_thumbnail = (
#                 file_data['file_type'] == 'image' or
#                 mime_type.startswith('image/') or
#                 file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'))
#         )
#
#         if should_generate_thumbnail:
#             try:
#                 generate_thumbnail(media_file, file_content)
#             except Exception as e:
#                 logger.error(f"Ошибка генерации миниатюры для {file_name}: {str(e)}")
#
#         media_file.save()
#         logger.info(f"Успешно обработан медиафайл {media_file.id} для сообщения {message_id}")
#         return media_file.id
#
#     except Message.DoesNotExist:
#         logger.error(f"Сообщение {message_id} не найдено")
#     except Exception as e:
#         logger.exception(f"Критическая ошибка обработки медиа: {str(e)}")
#         raise self.retry(exc=e)
#



# def generate_thumbnail(media_file, original_content):
#     """Генерация миниатюры для изображения с валидацией"""
#     print("Генерация миниатюр")
#     try:
#         img = Image.open(BytesIO(original_content))
#
#         # Проверяем, что это действительно изображение
#         if img.format not in ['JPEG', 'PNG', 'GIF', 'BMP', 'WEBP']:
#             logger.warning(f"Формат изображения {img.format} не поддерживается для миниатюр")
#             return
#
#         # Конвертируем в RGB если необходимо
#         if img.mode in ('RGBA', 'LA', 'P'):
#             img = img.convert('RGB')
#
#         # Создаем миниатюру
#         img.thumbnail(THUMBNAIL_SIZE)
#
#         # Сохраняем в буфер
#         thumb_io = BytesIO()
#         img.save(thumb_io, format='JPEG', quality=85)
#         thumb_io.seek(0)
#
#         # Формируем имя файла для миниатюры
#         original_name = os.path.splitext(os.path.basename(media_file.file.name))[0]
#         thumb_name = f"{original_name}_thumb.jpg"
#
#         # Сохраняем миниатюру
#         media_file.thumbnail.save(thumb_name, File(thumb_io), save=False)
#         print("SAVED")
#
#         return True
#     except Exception as e:
#         logger.error(f"Ошибка при генерации миниатюры: {str(e)}")
#         return False

@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def generate_thumbnail_async(self, media_file_id):
    """
    Асинхронная задача для генерации миниатюры изображения
    """
    try:
        # Получаем объект MediaFile
        media_file = MediaFile.objects.get(pk=media_file_id)

        # Проверяем, нужно ли вообще генерировать миниатюру
        if media_file.thumbnail_generated or media_file.thumbnail:
            logger.info(f"Миниатюра для MediaFile ID {media_file_id} уже существует")
            return

        # Проверяем, подходит ли файл для генерации миниатюры
        if not media_file.should_generate_thumbnail():
            logger.info(f"MediaFile ID {media_file_id} не требует генерации миниатюры")
            MediaFile.objects.filter(pk=media_file_id).update(thumbnail_generated=True)
            return

        # Проверяем существование файла
        if not media_file.file or not os.path.exists(media_file.file.path):
            logger.warning(f"Файл не существует для MediaFile ID {media_file_id}: {media_file.file.path}")

            # Повторяем попытку через некоторое время (файл может еще записываться)
            if self.request.retries < self.max_retries:
                raise self.retry(countdown=2 ** self.request.retries)

            # Если все попытки исчерпаны, помечаем как обработанный
            MediaFile.objects.filter(pk=media_file_id).update(thumbnail_generated=True)
            return

        # Читаем содержимое файла
        try:
            with open(media_file.file.path, 'rb') as f:
                file_content = f.read()
        except IOError as e:
            logger.error(f"Ошибка чтения файла для MediaFile ID {media_file_id}: {str(e)}")
            raise self.retry(exc=e)

        # Генерируем миниатюру
        result = _generate_thumbnail_for_file(media_file, file_content)

        if result:
            # Обновляем статус в БД
            MediaFile.objects.filter(pk=media_file_id).update(thumbnail_generated=True)
            logger.info(f"Миниатюра успешно сгенерирована для MediaFile ID {media_file_id}")
        else:
            logger.warning(f"Не удалось сгенерировать миниатюру для MediaFile ID {media_file_id}")

    except MediaFile.DoesNotExist:
        logger.error(f"MediaFile с ID {media_file_id} не найден")
    except Exception as e:
        logger.exception(f"Критическая ошибка генерации миниатюры для MediaFile ID {media_file_id}: {str(e)}")
        raise self.retry(exc=e)

def _generate_thumbnail_for_file(media_file, original_content):
    """Внутренняя функция генерации миниатюры с обработкой ошибок"""
    try:


        img = Image.open(BytesIO(original_content))

        # Проверяем формат изображения
        supported_formats = ['JPEG', 'PNG', 'GIF', 'BMP', 'WEBP', 'TIFF']
        if img.format not in supported_formats:
            logger.warning(f"Неподдерживаемый формат изображения {img.format} для MediaFile ID {media_file.id}")
            return False

        # Обработка больших изображений
        if img.width > MediaFile.MAX_PROCESSING_SIZE[0] or img.height > MediaFile.MAX_PROCESSING_SIZE[1]:
            img.thumbnail(MediaFile.MAX_PROCESSING_SIZE)

        # Конвертация в RGB для совместимости
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')

        # Создание миниатюры
        img.thumbnail(MediaFile.THUMBNAIL_SIZE)

        # Сохранение в буфер
        thumb_io = BytesIO()
        img.save(thumb_io, format='JPEG', quality=85)
        thumb_io.seek(0)

        # Формирование имени файла
        original_name = os.path.splitext(os.path.basename(media_file.file.name))[0]
        thumb_name = f"{original_name}_thumb.jpg"

        # Атомарное сохранение миниатюры
        with transaction.atomic():
            # Сохраняем миниатюру
            media_file.thumbnail.save(thumb_name, File(thumb_io), save=False)
            media_file.save(update_fields=['thumbnail'])

        return True

    except Exception as e:
        logger.error(f"Ошибка при генерации миниатюры: {str(e)}")
        return False


@shared_task
def cleanup_stale_thumbnail_tasks():
    """
    Очищает записи, где генерация миниатюр зависла более чем на 1 час
    """
    from django.utils import timezone
    from datetime import timedelta

    one_hour_ago = timezone.now() - timedelta(hours=1)

    # Находим записи, где thumbnail_generated=False, но файл существует более часа
    stale_records = MediaFile.objects.filter(
        thumbnail_generated=False,
        created_at__lt=one_hour_ago,
        file__isnull=False
    ).exclude(
        file=''  # Исключаем пустые файлы
    )[:100]  # Ограничиваем количество для одной задачи

    updated_count = 0
    for record in stale_records:
        try:
            # Проверяем существование файла
            if os.path.exists(record.file.path):
                # Принудительно запускаем генерацию миниатюры
                generate_thumbnail_async.delay(record.pk)
                updated_count += 1
            else:
                # Если файла нет, помечаем как обработанный
                record.thumbnail_generated = True
                record.save(update_fields=['thumbnail_generated'])
        except Exception as e:
            logger.error(f"Ошибка при очистке зависшей записи ID {record.pk}: {str(e)}")

    logger.info(f"Обработано {updated_count} зависших записей для генерации миниатюр")


# chat/tasks.py

@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_ai_generated_media_async(self, ai_message_id, media_data, user_id=None):
    """
    Асинхронная задача для обработки AI-сгенерированных медиафайлов
    """
    try:
        from .models import Message, MediaFile
        from django.contrib.auth import get_user_model

        # Получаем сообщение
        ai_message = Message.objects.get(pk=ai_message_id)

        # Получаем пользователя
        User = get_user_model()
        user = User.objects.get(pk=user_id) if user_id else None

        # Создаем сервис
        ai_media_service = AiMediaService(ai_message.chat)

        # Обрабатываем медиа
        media_obj = ai_media_service._process_single_media(media_data, ai_message)

        if media_obj:
            logger.info(f"AI-медиа успешно обработан: {media_obj.pk} для сообщения {ai_message_id}")
            # Обновляем тип сообщения, если это первый медиафайл
            if ai_message.media_files.count() == 1:
                ai_message.message_type = ai_media_service._get_message_type_for_media(media_obj.file_type)
                ai_message.save(update_fields=['message_type'])
        else:
            logger.warning(f"Не удалось обработать AI-медиа для сообщения {ai_message_id}")

    except Message.DoesNotExist:
        logger.error(f"Сообщение {ai_message_id} не найдено")
    except Exception as e:
        logger.exception(f"Ошибка обработки AI-медиа: {str(e)}")
        raise self.retry(exc=e)


