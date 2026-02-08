from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from curriculum.models.systematization.learning_objective import LearningObjective
from curriculum.models.content.response_format import ResponseFormat
from curriculum.models.systematization.professional_tag import ProfessionalTag
from users.models import CEFRLevel
from curriculum.models.content.lesson import Lesson
from curriculum.validators import validate_task_content_schema, validate_skill_focus


class TaskType(models.TextChoices):
    """Типы вопросов."""
    GRAMMAR = ('grammar', _('Grammar'))
    VOCABULARY = ('vocabulary', _('Vocabulary'))
    READING = ('reading', _('Reading'))
    LISTENING = ('listening', _('Listening'))
    WRITING = ('writing', _('Writing'))
    SPEAKING = ('speaking', _('Speaking'))


class TaskDifficulty(models.TextChoices):
    EASY = ('easy', _('Легкое'))
    MEDIUM = ('medium', _('Среднее'))
    HARD = ('hard', _('Сложное'))


class Task(models.Model):
    """
    Задание — самая мелкая единица взаимодействия.
    Полностью покрывает все 8 блоков диагностики.

    Назначение:
    - Закрытые вопросы: MCQ по грамматике, reading comprehension.
    - Открытые: writing warm-up, speaking probe.

    Ключевые поля:
    - task_type: тип навыка (грамматика, listening и т.д.)
    - response_format: как отвечает студент (выбор, текст, аудио)
    - content: структурированное содержимое (см. примеры ниже)
    - professional_tags: релевантность роли студента
    - is_diagnostic: используется ли в диагностике

    Примеры content:

    1. Multiple Choice (Grammar):
    {
      "prompt": "Which sentence is correct?",
      "options": ["I have went...", "I went...", "I have go..."],
      "correct_idx": 1,
      "explanation": "Past Simple for completed past actions."
    }

    2. Short Text (Listening):
    {
      "prompt": "What was the main issue mentioned in the audio?",
      "correct": ["deployment failed", "build error"],
      "case_sensitive": false
    }

    3. Free Text (Writing Warm-up):
    {
      "prompt": "What did you do at work yesterday?",
      "max_length_words": 50,
      "expected_skills": ["past_simple", "work_vocabulary"]
    }

    4. Audio (Speaking):
    {
      "prompt": "Record 20–30 seconds about your current task.",
      "max_duration_sec": 30
    }
    """
    objects = models.Manager()

    DIFFICULTY_WEIGHTS = {
        'easy': Decimal('0.5'),
        'medium': Decimal('1.0'),
        'hard': Decimal('2.0'),
    }

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, null=True, blank=True, verbose_name=_("Lesson"),
                               related_name="tasks")
    task_type = models.CharField(max_length=20, choices=TaskType, verbose_name=_("Task Type"))
    response_format = models.CharField(max_length=20, choices=ResponseFormat, verbose_name=_("Response Format"))

    difficulty = models.CharField(
        max_length=10,
        choices=TaskDifficulty.choices,
        default=TaskDifficulty.MEDIUM,
        verbose_name=_("Сложность задания"),
        help_text=_("Легкое (0.5), Среднее (1.0), Сложное (2.0)")
    )
    content = models.JSONField(verbose_name=_("Content"))
    # схема задается в engageai_core/curriculum/schemas.py:TASK_CONTENT_SCHEMAS
    content_schema_version = models.CharField(default="v1", verbose_name=_("Content Schema"))
    difficulty_cefr = models.CharField(max_length=2, choices=CEFRLevel, verbose_name=_("Difficulty CEFR"))
    learning_objectives = models.ManyToManyField(
        LearningObjective,
        related_name="tasks",
        help_text="Какие учебные цели проверяет задание"
    )
    # skill_focus = models.JSONField(default=list, validators=[validate_skill_focus], verbose_name=_("Skill Focus"),
    #                                help_text=_("e.g., ['listening', 'vocabulary']")
    #                                ) # TODO это если надо будет оценивать скилы точечно
    is_diagnostic = models.BooleanField(default=False, verbose_name=_("Used in Diagnostic"))
    professional_tags = models.ManyToManyField(ProfessionalTag, blank=True, verbose_name=_("Professional Tags"))
    is_active = models.BooleanField(default=True, verbose_name=_("Задание актуально"))
    order = models.PositiveIntegerField(
        verbose_name=_("Порядок задачи в уроке"),
        help_text=_("Порядок задания в уроке (чем меньше число, тем раньше задание)")
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Task")
        verbose_name_plural = _("Tasks")
        ordering = ['lesson', 'order']
        indexes = [
            models.Index(fields=['lesson', 'order']),
            models.Index(fields=['task_type']),
            models.Index(fields=['response_format']),
            models.Index(fields=['lesson', 'is_active', 'order'],
                         name='task_lesson_active_order_idx'),
        ]

    def __str__(self):
        return f"{self.get_task_type_display()} ({self.get_response_format_display()}) — {self.difficulty_cefr}"

    def clean(self):
        validate_task_content_schema(
            self.content,
            self.content_schema_version
        )

    def save(self, *args, **kwargs):
        """Автоматическая установка порядка при создании"""
        if not self.pk and self.order == 0:
            # Получаем максимальный order в этом уроке и добавляем 1
            max_order = Task.objects.filter(lesson=self.lesson).aggregate(
                max_order=models.Max('order')
            )['max_order'] or 0
            self.order = max_order + 1
        super().save(*args, **kwargs)

    def get_difficulty_weight(self) -> Decimal:
        """Возвращает вес сложности для расчетов"""
        return self.DIFFICULTY_WEIGHTS.get(self.difficulty, Decimal('1.0'))
