from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _

from users.models import CEFRLevel


# ==============================================================================
# СПРАВОЧНИКИ И КОНСТАНТЫ
# ==============================================================================

class TaskType(models.TextChoices):
    """Типы вопросов."""
    GRAMMAR = "mcq", "Multiple Choice"
    VOCABULARY = ('vocabulary', _('Vocabulary'))
    READING = ('reading', _('Reading'))
    LISTENING = ('listening', _('Listening'))
    WRITING = ('writing', _('Writing'))
    SPEAKING = ('speaking', _('Speaking'))

class ResponseFormat(models.TextChoices):
    """Типы ответов"""
    MULTIPLE_CHOICE =('multiple_choice', _('Multiple Choice – выбор одного или нескольких вариантов'))
    SINGLE_CHOICE =('single_choice', _('Single Choice – выбор одного варианта'))
    SHORT_TEXT =('short_text', _('Short Text – краткий текстовый ответ, 1–3 слова'))
    FREE_TEXT =('free_text', _('Free Text – развёрнутый ответ, абзац или текст'))
    AUDIO =('audio', _('Audio – голосовое сообщение'))


class MediaType(models.TextChoices):
    TEXT = ('text', _('Raw text snippet or prompt'))
    AUDIO = ('audio', _('Audio file (e.g., MP3, WAV)'))
    VIDEO = ('video', _('Video file (e.g AVI, MP4)'))
    IMAGE = ('image', _('Image (e.g., diagram, screenshot)'))
    DOC = ('document', _('PDF, DOC, or other document'))


class ProfessionalTag(models.Model):
    """
    Профессиональный тег — обозначает сферу или тип задач, релевантных заданию.
    Примеры: "backend", "qa", "incident-response", "technical-writing".

    Назначение:
    - Позволяет персонализировать диагностику и обучение под роль студента (из мини-анкеты).
    - Используется для фильтрации заданий по релевантности.

    Примеры наполнения:
    - "backend"
    - "qa"
    - "devops"
    - "product-interviews"
    - "api-documentation"
    - "standup-meetings"
    - "ticket-writing"

    Рекомендация:
    - Теги создаются кураторами/методистами.
    - Студент выбирает 1–3 тега при регистрации или в мини-анкете.
    """
    name = models.CharField(
        max_length=50,
        unique=True,
        verbose_name=_("Tag Name"),
        help_text=_("Short, machine-readable name (e.g., 'backend', 'standup-meetings')")
    )
    description = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("Description"),
        help_text=_("Human-readable explanation for admins")
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Is Active"))

    class Meta:
        verbose_name = _("Professional Tag")
        verbose_name_plural = _("Professional Tags")
        indexes = [models.Index(fields=['name'])]

    def __str__(self):
        return self.name


class LearningObjective(models.Model):
    """
    Учебная цель — педагогически сформулированное умение, которое должен развить студент.

    Вместо ручного кода (например, "B1-G-01") используется структурированное описание:
    - CEFR-уровень,
    - область навыка (грамматика, лексика и т.д.),
    - порядковый номер в рамках уровня и области.

    Идентификатор (`identifier`) генерируется автоматически и гарантирует уникальность.

    Примеры:
    - "Use Past Simple and Present Perfect correctly in work contexts" → grammar, B1, order=1 → identifier="grammar-B1-01"
    - "Understand technical stand-up meetings" → listening, B1, order=1 → identifier="listening-B1-01"
    """

    # TODO промпт для генерации уроков

    """
    You are an expert English curriculum designer for IT professionals.
Your task is to generate a structured LESSON and TASKS that help the student achieve a specific LEARNING OBJECTIVE.

The student:
- Role: backend developer
- Weakness: confuses Past Simple and Present Perfect (e.g., "I have fixed it yesterday")
- Target objective: {
"identifier": "grammar-B1-01",
 "name": "Use Past Simple and Present Perfect correctly in work contexts",
  "cefr_level": "B1",
   "skill_domain": "grammar"
   }

Output JSON with two keys: "lesson" and "tasks".

LESSON FORMAT:
{
  "title": "string",
  "description": "string",
  "lesson_type": "grammar",
  "duration_minutes": int (5-15),
  "required_cefr": "B1",
  "skill_focus": ["grammar"],
  "content": { /* optional narrative for student */ }
}

TASK FORMAT (array of 3–4 tasks):
Each task must have:
- "task_type": "grammar"
- "response_format": one of ["single_choice", "multiple_choice", "short_text"]
- "difficulty_cefr": "B1"
- "content": structured per platform rules (see examples below)
- "professional_tags": ["backend", "standup-meetings"] (relevant to student)

Content examples:
- MCQ: {"prompt": "...", "options": [...], "correct_idx": 1}
- Short text: {"prompt": "...", "correct": ["expected answer"], "case_sensitive": false}

DO NOT include file uploads or audio. Keep tasks text-based.

Output ONLY valid JSON. No explanations.
    """
    # TODO system_prompt
    """
    You are an expert AI tutor and curriculum designer for IT professionals learning English.
You generate structured lessons and tasks that align with specific learning objectives.
You NEVER invent fake audio, video, or file content. Instead, you specify media requirements clearly so the system can provide real media.

All output must be valid JSON and follow the exact schema described below.
    """
    # TODO user_prompt
    """
    Generate a lesson and tasks for the following student and learning objective(s).

STUDENT CONTEXT:
- Professional role: {{ student_profession }}
- CEFR level: {{ student_cefr }}
- Learning goals: {{ student_goals }}
- Weaknesses: {{ student_weaknesses }} (e.g., ["confuses past tenses", "struggles with listening to native speakers"])
- Strengths: {{ student_strengths }} (e.g., ["strong vocabulary", "good reading comprehension"])

LEARNING OBJECTIVE(S) TO TARGET:
[ 
  {
    "identifier": "string",       // e.g., "grammar-B1-01"
    "name": "string",             // e.g., "Use Past Simple and Present Perfect correctly in work contexts"
    "skill_domain": "string",     // one of: grammar, vocabulary, reading, listening, writing, speaking
    "cefr_level": "string"        // e.g., "B1"
  },
  ... (1–3 objectives max)
]

INSTRUCTIONS:
1. Generate ONE lesson and 2–4 tasks.
2. Choose lesson_type = skill_domain of the PRIMARY objective.
3. For each task:
   - Set task_type = skill_domain
   - Choose response_format appropriately:
        • grammar/vocabulary/reading → "single_choice", "multiple_choice", or "short_text"
        • writing → "free_text"
        • speaking → "audio"
        • listening → "short_text" or "multiple_choice" (audio will be provided separately)
   - If the task requires media (e.g., listening needs audio), set:
        "media_required": true,
        "media_type": "audio|text|image",
        "media_description": "Clear description for content team (e.g., '30s stand-up audio about deployment')"
   - Do NOT include actual file paths or fake URLs.
4. Use professional context in prompts: mention stand-ups, tickets, PRs, incidents, etc.
5. Keep language supportive, clear, and professional.

OUTPUT FORMAT (strict JSON):
{
  "lesson": {
    "title": "string",
    "description": "string",
    "lesson_type": "string",           // skill_domain
    "duration_minutes": integer (5–20),
    "required_cefr": "string",
    "skill_focus": ["string"],         // e.g., ["grammar", "writing"]
    "content": { "intro": "string" }   // optional
  },
  "tasks": [
    {
      "task_type": "string",
      "response_format": "string",
      "difficulty_cefr": "string",
      "professional_tags": ["string"],  // e.g., ["backend", "standup-meetings"]
      "content": { ... },               // structured per task type (see examples below)
      "media_required": boolean,        // optional
      "media_type": "string",           // only if media_required=true
      "media_description": "string"     // only if media_required=true
    }
  ]
}

CONTENT SCHEMAS BY RESPONSE FORMAT:
- single_choice / multiple_choice:
    { "prompt": "string", "options": ["a", "b", "c"], "correct_idx": 1 }
- short_text:
    { "prompt": "string", "correct": ["answer1", "answer2"], "case_sensitive": false }
- free_text:
    { "prompt": "string", "max_length_words": 50, "expected_elements": ["past_tense", "IT_vocab"] }
- audio:
    { "prompt": "string", "max_duration_sec": 30 }

OUTPUT ONLY VALID JSON. NO MARKDOWN. NO EXPLANATIONS.
    """
    """
    📌 Как система использует этот промпт
Собирает контекст студента из Student, SkillProfile, ErrorLog.
Выбирает 1–3 LearningObjective (например, из рекомендаций адаптивного сервиса).
Подставляет данные в шаблон промпта (через Jinja или f-strings).
Отправляет в LLM → получает JSON.
Обрабатывает ответ:
Создаёт Lesson.
Для каждого Task:
сохраняет content,
если media_required == true — создаёт задачу для контент-команды или использует существующий TaskMedia (если речь о диагностике),
привязывает ProfessionalTag по совпадению (например, "backend" → ищет тег в БД).
Привязывает все задания к Lesson, а Lesson — к целям (learning_objectives).

🌟 Преимущества такого подхода
Возможность - Как реализована
Поддержка всех 6 навыков - Через skill_domain и правильный response_format
Профессиональная релевантность - professional_tags + контекст в промпте
Безопасная работа с медиа - LLM описывает, что нужно, но не выдумывает файлы
Точная привязка к целям - Используется identifier из LearningObjective
Готовность к диагностике и обучению - Один промпт работает и для Warm-up, и для глубокого урока

    """
    # === Структурированные поля ===
    cefr_level = models.CharField(
        max_length=2,
        choices=CEFRLevel,
        verbose_name=_("CEFR Level"),
        help_text=_("Уровень CEFR, на котором эта цель актуальна")
    )
    skill_domain = models.CharField(
        max_length=20,
        choices=[
            ('grammar', _('Grammar')),
            ('vocabulary', _('Vocabulary')),
            ('listening', _('Listening')),
            ('reading', _('Reading')),
            ('writing', _('Writing')),
            ('speaking', _('Speaking')),
        ],
        verbose_name=_("Skill Domain"),
        help_text=_("Область языкового навыка")
    )
    order_in_level = models.PositiveSmallIntegerField(
        default=1,
        verbose_name=_("Order within level and domain"),
        help_text=_("Порядковый номер цели в рамках уровня и области (для сортировки)")
    )

    # === Человекочитаемые поля ===
    name = models.CharField(
        max_length=200,
        verbose_name=_("Name"),
        help_text=_("Clear, actionable objective — e.g., 'Use Past Simple correctly in work emails'")
    )
    description = models.TextField(
        blank=True,
        verbose_name=_("Description"),
        help_text=_("Optional detailed explanation for methodologists")
    )

    # === Автоматически генерируемый идентификатор (для API, логики, LLM) ===
    identifier = models.SlugField(
        max_length=50,
        unique=True,
        editable=False,
        verbose_name=_("Machine Identifier"),
        help_text=_("Auto-generated unique ID like 'grammar-B1-01'")
    )

    # === Служебные поля ===
    is_active = models.BooleanField(default=True, verbose_name=_("Is Active"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Learning Objective")
        verbose_name_plural = _("Learning Objectives")
        unique_together = [
            ['cefr_level', 'skill_domain', 'order_in_level']
        ]
        ordering = ['cefr_level', 'skill_domain', 'order_in_level']
        indexes = [
            models.Index(fields=['cefr_level', 'skill_domain']),
            models.Index(fields=['identifier']),
        ]

    def save(self, *args, **kwargs):
        # Генерируем идентификатор вида: grammar-B1-01
        self.identifier = f"{self.skill_domain}-{self.cefr_level}-{self.order_in_level:02d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"[{self.identifier}] {self.name}"


# ==============================================================================
# 3. УЧЕБНЫЙ КОНТЕНТ
# ==============================================================================

class Course(models.Model):
    """
    Учебный курс — структурированная последовательность уроков.
    Может быть диагностическим (is_diagnostic=True) или обучающим.

    Назначение:
    - Диагностический курс: содержит 8 блоков из плана.
    - Обучающий курс: тематический путь (например, "English for Backend Engineers").

    Поля:
    - title: название курса
    - target_cefr_from/to: диапазон CEFR
    - estimated_duration: общая длительность в минутах
    - learning_objectives: цели, которые покрывает курс
    - required_skills: список навыков/уровней, необходимых для старта (JSON)
    - is_diagnostic: флаг для диагностики
    """
    title = models.CharField(max_length=200, verbose_name=_("Title"))
    description = models.TextField(verbose_name=_("Description"))
    target_cefr_from = models.CharField(max_length=2, choices=CEFRLevel, verbose_name=_("From CEFR"))
    target_cefr_to = models.CharField(max_length=2, choices=CEFRLevel, verbose_name=_("To CEFR"))
    estimated_duration = models.PositiveIntegerField(
        verbose_name=_("Estimated Duration (minutes)"),
        help_text=_("Total estimated time to complete the course")
    )
    learning_objectives = models.ManyToManyField(LearningObjective, verbose_name=_("Learning Objectives"))
    required_skills = models.JSONField(
        default=list,
        verbose_name=_("Required Skills"),
        help_text=_("e.g., ['grammar:B1', 'listening:A2']")
    )
    is_diagnostic = models.BooleanField(
        default=False,
        verbose_name=_("Is Diagnostic"),
        help_text=_("If True, this course implements the 8-block diagnostic flow")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, verbose_name=_("Is Active"))

    class Meta:
        verbose_name = _("Course")
        verbose_name_plural = _("Courses")
        indexes = [models.Index(fields=['is_diagnostic'])]

    def __str__(self):
        return f"{self.title} ({self.get_target_cefr_from_display()} → {self.get_target_cefr_to_display()})"


class Lesson(models.Model):
    """
    Урок — логическая единица внутри курса (например, "Listening: Stand-up Meetings").

    Назначение:
    - Соответствует одному из 8 блоков диагностики или теме в обучении.
    - Содержит задания (Tasks).

    Поля:
    - lesson_type: тип урока (грамматика, аудирование и т.д.)
    - duration_minutes: сколько времени займёт
    - skill_focus: навыки, на которые направлен (["listening", "vocabulary"])
    - adaptive_parameters: правила адаптации (например, пороги для усложнения)
    """
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='lessons', verbose_name=_("Course"))
    title = models.CharField(max_length=200, verbose_name=_("Title"))
    description = models.TextField(verbose_name=_("Description"))
    lesson_type = models.CharField(max_length=20, choices=TaskType, verbose_name=_("Lesson Type"))
    order = models.PositiveIntegerField(verbose_name=_("Order"))
    content = models.JSONField(
        verbose_name=_("Content"),
        help_text=_("Optional structured lesson instructions or narrative for AI")
    )
    duration_minutes = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(120)],
        verbose_name=_("Duration (minutes)")
    )
    required_cefr = models.CharField(max_length=2, choices=CEFRLevel, verbose_name=_("Required CEFR"))
    learning_objectives = models.ManyToManyField(LearningObjective, verbose_name=_("Learning Objectives"))
    skill_focus = models.JSONField(
        default=list,
        verbose_name=_("Skill Focus"),
        help_text=_("e.g., ['listening', 'vocabulary']")
    )
    adaptive_parameters = models.JSONField(
        default=dict,
        verbose_name=_("Adaptive Parameters"),
        help_text=_("e.g., {'min_correct_ratio': 0.7, 'max_items': 10}")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, verbose_name=_("Is Active"))

    class Meta:
        verbose_name = _("Lesson")
        verbose_name_plural = _("Lessons")
        ordering = ['course', 'order']
        indexes = [models.Index(fields=['course', 'order'])]
        unique_together = [['course', 'order']]

    def __str__(self):
        return f"{self.course.title} → {self.title}"


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
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, null=True, blank=True, verbose_name=_("Lesson"))
    task_type = models.CharField(max_length=20, choices=TaskType, verbose_name=_("Task Type"))
    response_format = models.CharField(max_length=20, choices=ResponseFormat, verbose_name=_("Response Format"))
    content = models.JSONField(verbose_name=_("Content"))
    difficulty_cefr = models.CharField(max_length=2, choices=CEFRLevel, verbose_name=_("Difficulty CEFR"))
    is_diagnostic = models.BooleanField(default=False, verbose_name=_("Used in Diagnostic"))
    professional_tags = models.ManyToManyField(ProfessionalTag, blank=True, verbose_name=_("Professional Tags"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Task")
        verbose_name_plural = _("Tasks")
        indexes = [
            models.Index(fields=['task_type']),
            models.Index(fields=['response_format']),
            models.Index(fields=['difficulty_cefr']),
            models.Index(fields=['is_diagnostic']),
        ]

    def __str__(self):
        return f"{self.get_task_type_display()} ({self.get_response_format_display()}) — {self.difficulty_cefr}"


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


# ==============================================================================
# 4. СТУДЕНТ И ПРОГРЕСС
# ==============================================================================

class Student(models.Model):
    """
    Профиль студента — расширение User.

    Назначение:
    - Хранит профессиональный контекст (из мини-анкеты, блок 2),
    - Текущий CEFR-уровень,
    - Используется для персонализации.

    Поля:
    - professional_context: свободное текстовое поле или JSON с ролью/целями
    - cefr_level: текущий уровень (обновляется после диагностики)
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name=_("User"))
    cefr_level = models.CharField(
        max_length=2, choices=CEFRLevel, null=True, blank=True,
        verbose_name=_("Current CEFR Level")
    )
    professional_context = models.TextField(
        blank=True,
        verbose_name=_("Professional Context"),
        help_text=_("e.g., 'Backend developer in fintech. Need English for stand-ups and documentation.'")
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Student")
        verbose_name_plural = _("Students")
        indexes = [models.Index(fields=['cefr_level'])]

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.cefr_level or '–'})"


class SkillProfile(models.Model):
    """
    Профиль навыков — результат диагностики или промежуточной оценки.

    Назначение:
    - Соответствует цели №2 из плана: «Сформировать первичный профиль навыков».
    - Используется для Goal Setting и подбора курсов.

    Поля:
    - grammar, vocabulary, listening, reading, writing, speaking: float от 0.0 до 1.0
    - snapshot_at: момент оценки (можно хранить историю прогресса)
    """
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name=_("Student"))
    grammar = models.FloatField(default=0.0, verbose_name=_("Grammar Score"))
    vocabulary = models.FloatField(default=0.0, verbose_name=_("Vocabulary Score"))
    listening = models.FloatField(default=0.0, verbose_name=_("Listening Score"))
    reading = models.FloatField(default=0.0, verbose_name=_("Reading Score"))
    writing = models.FloatField(default=0.0, verbose_name=_("Writing Score"))
    speaking = models.FloatField(default=0.0, verbose_name=_("Speaking Score"))
    snapshot_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Snapshot Timestamp"))

    class Meta:
        verbose_name = _("Skill Profile")
        verbose_name_plural = _("Skill Profiles")
        indexes = [
            models.Index(fields=['student']),
            models.Index(fields=['snapshot_at']),
        ]

    def __str__(self):
        return f"Skill Profile for {self.student} at {self.snapshot_at.date()}"


class ErrorLog(models.Model):
    """
    Журнал типичных ошибок — для цели №3: «Выявить типичные ошибки».

    Назначение:
    - Формирует Error Profile студента.
    - Используется для рекомендаций и подбора практики.

    Примеры:
    - error_type: "tense"
    - example: "I have went to the meeting"
    - correction: "I went to the meeting"
    """
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name=_("Student"))
    error_type = models.CharField(max_length=30, verbose_name=_("Error Type"))
    example = models.TextField(verbose_name=_("Example"))
    correction = models.TextField(blank=True, verbose_name=_("Correction"))
    context_task = models.ForeignKey(Task, on_delete=models.SET_NULL, null=True, blank=True,
                                     verbose_name=_("Context Task"))
    detected_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Detected At"))
    resolved = models.BooleanField(default=False, verbose_name=_("Resolved"))

    class Meta:
        verbose_name = _("Error Log")
        verbose_name_plural = _("Error Logs")
        indexes = [
            models.Index(fields=['student']),
            models.Index(fields=['error_type']),
            models.Index(fields=['resolved']),
        ]

    def __str__(self):
        return f"{self.error_type} — {self.student}"


class Enrollment(models.Model):
    """
    Зачисление студента на курс.

    Назначение:
    - Отслеживание прогресса в диагностике и обучении.
    - Поддержка нескольких активных путей.
    """
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name=_("Student"))
    course = models.ForeignKey(Course, on_delete=models.CASCADE, verbose_name=_("Course"))
    started_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Started At"))
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Completed At"))
    current_lesson = models.ForeignKey(Lesson, on_delete=models.SET_NULL, null=True, blank=True,
                                       verbose_name=_("Current Lesson"))

    class Meta:
        verbose_name = _("Enrollment")
        verbose_name_plural = _("Enrollments")
        indexes = [
            models.Index(fields=['student', 'course']),
            models.Index(fields=['started_at']),
        ]

    def __str__(self):
        return f"{self.student} → {self.course}"


# ==============================================================================
# 5. ДИАГНОСТИКА И ОЦЕНКА
# ==============================================================================

class DiagnosticSession(models.Model):
    """
    Сессия адаптивной диагностики — охватывает все 8 блоков.

    Назначение:
    - Связывает студента, его ответы, итоговый уровень и профиль.
    - Используется для аналитики и повторной диагностики.
    """
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name=_("Student"))
    started_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Started At"))
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Completed At"))
    final_cefr = models.CharField(max_length=2, choices=CEFRLevel, null=True, blank=True,
                                  verbose_name=_("Final CEFR"))
    skill_profile = models.ForeignKey(SkillProfile, on_delete=models.SET_NULL, null=True, blank=True,
                                      verbose_name=_("Skill Profile"))

    class Meta:
        verbose_name = _("Diagnostic Session")
        verbose_name_plural = _("Diagnostic Sessions")
        indexes = [
            models.Index(fields=['student']),
            models.Index(fields=['completed_at']),
        ]

    def __str__(self):
        return f"Diagnostic for {self.student} ({self.final_cefr or 'in progress'})"


class StudentTaskResponse(models.Model):
    """
    Ответ студента на задание.

    Назначение:
    - Хранит как текст, так и аудио.
    - Используется для автоматической и LLM-оценки.

    Поля:
    - response_text: для writing, short_text
    - audio_file: для speaking
    - is_correct: True/False для закрытых, None для открытых
    """
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name=_("Student"))
    task = models.ForeignKey(Task, on_delete=models.CASCADE, verbose_name=_("Task"))
    response_text = models.TextField(blank=True, verbose_name=_("Text Response"))
    audio_file = models.FileField(upload_to='responses/', blank=True, null=True, verbose_name=_("Audio Response"))
    submitted_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Submitted At"))
    is_correct = models.BooleanField(
        null=True,
        blank=True,
        verbose_name=_("Is Correct (Auto)"),
        help_text=_("True/False for closed questions, None for open-ended")
    )

    class Meta:
        verbose_name = _("Student Task Response")
        verbose_name_plural = _("Student Task Responses")
        indexes = [
            models.Index(fields=['student']),
            models.Index(fields=['task']),
            models.Index(fields=['submitted_at']),
        ]

    def __str__(self):
        return f"Response by {self.student} to {self.task}"


class Assessment(models.Model):
    """
    Результат оценки LLM для открытого задания.

    Назначение:
    - Хранит структурированную обратную связь по writing/speaking.
    - Используется для обновления SkillProfile и ErrorLog.

    Поля:
    - raw_output: полный ответ LLM (для аудита)
    - structured_feedback: нормализованный JSON (см. пример ниже)

    Пример structured_feedback:
    {
      "score_grammar": 0.7,
      "score_vocabulary": 0.85,
      "errors": [{"type": "tense", "example": "I have went", "correction": "I went"}],
      "strengths": ["clear structure", "good IT vocabulary"],
      "suggestions": ["review past tenses"]
    }
    """
    task_response = models.OneToOneField(StudentTaskResponse, on_delete=models.CASCADE, verbose_name=_("Task Response"))
    llm_version = models.CharField(max_length=50, blank=True, verbose_name=_("LLM Version"))
    raw_output = models.JSONField(verbose_name=_("Raw LLM Output"))
    structured_feedback = models.JSONField(verbose_name=_("Structured Feedback"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))

    class Meta:
        verbose_name = _("Assessment")
        verbose_name_plural = _("Assessments")
        indexes = [models.Index(fields=['task_response'])]

    def __str__(self):
        return f"Assessment for {self.task_response}"