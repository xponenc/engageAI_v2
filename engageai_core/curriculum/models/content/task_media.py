from django.db import models
from django.utils.translation import gettext_lazy as _

from curriculum.models.content.task import Task


class MediaType(models.TextChoices):
    """Тип медиа файла"""

    TEXT = ('text', _('Raw text snippet or prompt'))
    AUDIO = ('audio', _('Audio file (e.g., MP3, WAV)'))
    VIDEO = ('video', _('Video file (e.g AVI, MP4)'))
    IMAGE = ('image', _('Image (e.g., diagram, screenshot)'))
    DOC = ('document', _('PDF, DOC, or other document'))


class TaskMedia(models.Model):
    """
    Медиафайл, прикреплённый к заданию.

    Назначение:
    - Аудио для listening (блок 6),
    - Изображение для reading (например, скрин тикета),
    - Текстовый фрагмент.

    Поля:
    - file: путь к файлу
    - media_type: тип контента
    - order: порядок, если файлов несколько
    """
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='media_files', verbose_name=_("Task"))
    file = models.FileField(upload_to='task_media/', verbose_name=_("File"))
    media_type = models.CharField(max_length=20, choices=MediaType, verbose_name=_("Media Type"))
    order = models.PositiveSmallIntegerField(default=0, verbose_name=_("Order"))

    class Meta:
        verbose_name = _("Task Media")
        verbose_name_plural = _("Task Media")
        indexes = [
            models.Index(fields=['task']),
            models.Index(fields=['media_type']),
        ]

    def __str__(self):
        return f"{self.get_media_type_display()} for {self.task}"
