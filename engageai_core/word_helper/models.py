from django.db import models


class Word(models.Model):
    """
    Основная лексическая единица — слово на английском языке.
    Используется в мини-хелпере, упражнениях, AI-аналитике и персонализированных промптах.
    """

    word = models.CharField(
        max_length=255,
        db_index=True,
        unique=True,
        verbose_name="Слово",
        help_text="Форма слова, как она встречается в тексте (например, 'running')."
    )
    canonical_form = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Базовая форма",
        help_text="Инфинитив для глаголов, единственное число для существительных и т.д. (например, 'run')."
    )
    pos = models.CharField(
        max_length=50,
        verbose_name="Часть речи",
        help_text="Part of Speech: noun, verb, adjective и т.д."
    )
    lang_code = models.CharField(
        max_length=10,
        default="en",
        verbose_name="Код языка",
        help_text="ISO 639-1 код языка (например, 'en' для английского)."
    )
    ipa = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Международная фонетическая транскрипция (IPA)",
        help_text="Пример: /ˈrʌnɪŋ/"
    )

    class Meta:
        verbose_name = "Слово"
        verbose_name_plural = "Слова"

    def __str__(self):
        return self.word


class Pronunciation(models.Model):
    """
    Произношение слова от конкретного голоса/акцента.
    Поддерживает расширение до множества TTS-голосов и акцентов (UK, US и др.).
    """

    VOICE_CHOICES = [
        ("random", "Random Voice"),
        ("uk_female", "UK English – Female"),
        ("us_male", "US English – Male"),
        # Расширяемо в будущем
    ]

    word = models.ForeignKey(
        Word,
        related_name='pronunciations',
        on_delete=models.CASCADE,
        verbose_name="Слово"
    )
    voice_type = models.CharField(
        max_length=50,
        choices=VOICE_CHOICES,
        default="random",
        verbose_name="Тип голоса",
        help_text="Определяет акцент и пол голоса для произношения."
    )
    audio_file = models.FileField(
        upload_to='word_audio/',
        blank=True,
        null=True,
        verbose_name="Аудиофайл",
        help_text="Файл произношения в формате MP3 или WAV."
    )
    source = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Источник",
        help_text="Откуда взят файл: Wiktionary, Google TTS, AWS Polly и т.д."
    )

    class Meta:
        verbose_name = "Произношение"
        verbose_name_plural = "Произношения"
        unique_together = ('word', 'voice_type')

    def __str__(self):
        return f"{self.word.word} [{self.voice_type}]"


class WordSense(models.Model):
    """
    Одно значение (смысл) слова. У одного слова может быть несколько значений.
    Используется для контекстного перевода и объяснений в мини-хелпере.
    """

    word = models.ForeignKey(
        Word,
        related_name='senses',
        on_delete=models.CASCADE,
        verbose_name="Слово"
    )
    gloss = models.TextField(
        verbose_name="Объяснение / Перевод",
        help_text="Пояснение значения слова на простом английском или с переводом."
    )
    raw_tags = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Необработанные теги",
        help_text="Исходные теги из источника (например, ['countable'])."
    )
    categories = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Категории",
        help_text="Классификация значения (например, ['Past participles'])."
    )

    class Meta:
        verbose_name = "Значение слова"
        verbose_name_plural = "Значения слов"

    def __str__(self):
        return f"{self.word.word}: {self.gloss[:50]}..."


class WordForm(models.Model):
    """
    Грамматическая форма слова (например, past tense, plural).
    Связывает производные формы с базовым словом.
    """

    word = models.ForeignKey(
        Word,
        related_name='forms',
        on_delete=models.CASCADE,
        verbose_name="Базовое слово"
    )
    form = models.CharField(
        max_length=255,
        verbose_name="Форма",
        help_text="Конкретная грамматическая форма (например, 'ran', 'mice')."
    )
    tags = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Стандартизированные теги",
        help_text="Нормализованные метки, например: ['past', 'singular']."
    )
    raw_tags = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Исходные теги",
        help_text="Как указано в источнике данных."
    )

    class Meta:
        verbose_name = "Грамматическая форма"
        verbose_name_plural = "Грамматические формы"

    def __str__(self):
        return f"{self.word.word} → {self.form}"