from django.db import models
from django.utils.translation import gettext_lazy as _


class ResponseFormat(models.TextChoices):
    """Типы ответов"""

    MULTIPLE_CHOICE = ('multiple_choice', _('Multiple Choice – выбор одного или нескольких вариантов'))
    SINGLE_CHOICE = ('single_choice', _('Single Choice – выбор одного варианта'))
    SHORT_TEXT = ('short_text', _('Short Text – краткий текстовый ответ, 1–3 слова'))
    FREE_TEXT = ('free_text', _('Free Text – развёрнутый ответ, абзац или текст'))
    AUDIO = ('audio', _('Audio – голосовое сообщение'))
