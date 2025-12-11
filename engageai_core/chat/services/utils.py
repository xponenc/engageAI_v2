import mimetypes
import os
from PIL import Image
from django.conf import settings
from django.core.files.base import ContentFile


def validate_file_type(file):
    """Валидация типа файла для безопасности"""
    # Разрешенные расширения
    allowed_extensions = {
        'image': ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg'],
        'audio': ['.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac'],
        'video': ['.mp4', '.avi', '.mov', '.wmv', '.mkv', '.webm'],
        'document': ['.pdf', '.doc', '.docx', '.txt', '.rtf', '.odt', '.xls', '.xlsx', '.ppt', '.pptx']
    }

    ext = os.path.splitext(file.name)[1].lower()

    # Проверяем по MIME-типу
    mime_type, _ = mimetypes.guess_type(file.name)
    if mime_type:
        main_type = mime_type.split('/')[0]
        if main_type == 'image' and ext not in allowed_extensions['image']:
            return False
        if main_type == 'audio' and ext not in allowed_extensions['audio']:
            return False
        if main_type == 'video' and ext not in allowed_extensions['video']:
            return False

    # Проверяем по расширению
    all_allowed = [ext for group in allowed_extensions.values() for ext in group]
    return ext in all_allowed


def get_file_type_from_mime(mime_type):
    """Определяет тип файла по MIME-типу"""
    if not mime_type:
        return None

    main_type = mime_type.split('/')[0]
    if main_type == 'image':
        return 'image'
    elif main_type == 'audio':
        return 'audio'
    elif main_type == 'video':
        return 'video'
    return 'document'


def two_generate_thumbnail(media_file, size=(300, 300)):
    """Генерирует миниатюру для изображения"""
    if media_file.file_type != 'image' or not media_file.file:
        return

    try:
        # Открываем исходное изображение
        with Image.open(media_file.file.path) as img:
            # Конвертируем в RGB если нужно
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')

            # Создаем копию с измененным размером
            img.thumbnail(size, Image.LANCZOS)

            # Сохраняем миниатюру во временный файл
            thumb_name = f"thumbnails/{os.path.splitext(os.path.basename(media_file.file.name))[0]}_{size[0]}x{size[1]}.jpg"
            thumb_path = os.path.join(settings.MEDIA_ROOT, thumb_name)

            # Создаем директорию если не существует
            os.makedirs(os.path.dirname(thumb_path), exist_ok=True)

            # Сохраняем изображение
            img.save(thumb_path, 'JPEG', quality=85)

            # Обновляем поле миниатюры
            with open(thumb_path, 'rb') as f:
                media_file.thumbnail.save(
                    os.path.basename(thumb_path),
                    ContentFile(f.read()),
                    save=True
                )

            # Удаляем временный файл
            if os.path.exists(thumb_path):
                os.remove(thumb_path)

    except Exception as e:
        # logger.error(f"Ошибка генерации миниатюры: {str(e)}")
        pass