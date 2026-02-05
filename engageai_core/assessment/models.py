# assessment/models.py
"""
Модели для приложения assessment.
Документирование на русском.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from django.contrib.postgres.fields import ArrayField
import uuid

from curriculum.models import Task
from users.models import CEFRLevel


class QuestionType(models.TextChoices):
    """Типы вопросов."""
    MCQ = "mcq", "Multiple Choice"
    OPEN = "open", "Open Answer"
    READING = "reading", "Understanding Text"


class SessionSourceType(models.TextChoices):
    """Типы источников сессии"""
    WEB = "web", "Сессия начата на сайте"
    TELEGRAM = "tg", "Сессия начата в боте"


# class SourceType(models.TextChoices):
#     """Источник вопроса."""
#     CEFR = "cefr", "Статический CEFR из банка"
#     LLM = "llm", "Сгенерирован LLM"

#
# class CEFRQuestion(models.Model):
#     """
#     Статический банк вопросов (CEFR).
#     Это мастер-таблица вопросов, используется для выборки и аналитики.
#     В сессиях храним клон вопроса в QuestionInstance.question_json,
#     чтобы гарантировать неизменность исторических данных.
#     """
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     level = models.CharField(max_length=2, choices=CEFRLevel.choices, db_index=True)
#     type = models.CharField(max_length=10, choices=QuestionType.choices, db_index=True)
#     question_text = models.TextField()
#     options = ArrayField(models.CharField(max_length=500), null=True, blank=True,
#                          help_text="Варианты для MCQ (список строк). Для open = null")
#     correct_answer = models.JSONField(null=True, blank=True,
#                                       help_text='{"index": 0} для MCQ или {"text":"..."} для точной проверки')
#     explanation = models.TextField(null=True, blank=True)
#     created_at = models.DateTimeField(auto_now_add=True)
#
#     objects = models.Manager()
#
#     class Meta:
#         indexes = [
#             models.Index(fields=["level", "type"]),
#         ]
#         ordering = ["level"]
#
#     def __str__(self):
#         return f"{self.level} | {self.type} | {self.question_text[:50]}"

#
# class LLMGeneratedQuestion(models.Model):
#     """
#     Вопросы, сгенерированные LLM для персонализации под пользователя.
#     Храним JSON, чтобы можно было пересмотреть сгенерированный текст.
#     """
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     template_id = models.CharField(max_length=128, null=True, blank=True,
#                                    help_text="Опциональный ID промпта/шаблона")
#     user_id = models.UUIDField(db_index=True, help_text="UUID пользователя, для которого сгенерирован вопрос")  # TODO FK?
#     test_session_id = models.UUIDField(db_index=True, help_text="ID TestSession при генерации")
#     question_json = models.JSONField()
#     created_at = models.DateTimeField(auto_now_add=True)
#
#     class Meta:
#         indexes = [
#             models.Index(fields=["user_id"]),
#             models.Index(fields=["test_session_id"])
#         ]
#         ordering = ["-created_at"]


class TestSession(models.Model):
    """
    Сессия тестирования. Одна попытка размещается в одной сессии.
      Логика:
    - У пользователя может быть только одна незавершённая сессия.
    - time_limit: ограничение на длительность (например 30 минут)
    - При окончании сохраняется итоговый протокол protocol_json
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    # aborted_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)

    time_limit_minutes = models.IntegerField(default=60, help_text="Время жизни сессии в минутах")

    # Блокировка сессии, чтобы избежать конфликтов simultaneous access
    locked_by = models.CharField(max_length=32, choices=SessionSourceType.choices, default=SessionSourceType.WEB.value,
                                 help_text="Кто в настоящий момент 'держит' сессию (web/telegram)")

    estimated_level = models.CharField(max_length=2, choices=CEFRLevel.choices,
                                       null=True, blank=True, db_index=True)
    protocol_json = models.JSONField(null=True, blank=True)

    objects = models.Manager()

    class Meta:
        indexes = [
            models.Index(fields=["user_id", "started_at"]),
            models.Index(fields=["estimated_level"]),
        ]
        ordering = ["-started_at"]

    def is_active(self) -> bool:
        """Возвращает True если сессия активна (не завершена и не просрочена)."""
        if self.finished_at or self.expired_at:
            return False
        return True

    def mark_expired(self):
        """Пометить сессию как просроченную."""
        self.finished_at = timezone.now()
        self.expired_at = self.started_at + timedelta(minutes=self.time_limit_minutes)
        self.save(update_fields=["expired_at", "finished_at"])

    def __str__(self):
        return f"Session {self.id} user {self.user_id}"


class QuestionInstance(models.Model):
    """
    Конкретный (инстанцированный) вопрос, выданный пользователю в TestSession.
    Содержит полную копию вопроса в question_json для неизменности истории.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(TestSession, on_delete=models.CASCADE, related_name="questions")
    task = models.ForeignKey(Task, on_delete=models.SET_NULL, null=True, blank=True, related_name='question_instances')
    # source_type = models.CharField(max_length=10, choices=SourceType.choices, db_index=True)
    # source_question_id = models.UUIDField(help_text="ID в CEFRQuestion или LLMGeneratedQuestion")
    # question_json = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = models.Manager()

    class Meta:
        indexes = [
            models.Index(fields=["session", "created_at"]),
        ]
        ordering = ["created_at"]


class TestAnswer(models.Model):
    """
    Ответ пользователя на конкретный QuestionInstance.
    Поле ai_feedback хранит результат LLM-оценки (для open-ответов) и/или комментарии.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.OneToOneField(QuestionInstance, on_delete=models.CASCADE, related_name="answer", db_index=True)
    answer_text = models.TextField(null=True, blank=True)
    answer_audio_url = models.URLField(null=True, blank=True)
    recognized_text = models.TextField(null=True, blank=True, help_text="STT result если был voice")
    score = models.FloatField(null=True, blank=True, help_text="Оценка 0.0–1.0")
    ai_feedback = models.JSONField(null=True, blank=True)
    answered_at = models.DateTimeField(auto_now_add=True)

    objects = models.Manager()

    class Meta:
        indexes = [
            models.Index(fields=["question", "answered_at"]),
        ]

    def __str__(self):
        return f"Answer {self.id} question {self.question_id}"



class TestAnswerMedia(models.Model):
    """
    Медиафайл, прикреплённый к ответу.
    """
    answer = models.ForeignKey(TestAnswer, on_delete=models.CASCADE, related_name='media_files', verbose_name="Task")
    file = models.FileField(upload_to='test_answer_media/', verbose_name="File")
