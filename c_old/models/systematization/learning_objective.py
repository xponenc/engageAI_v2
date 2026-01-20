from django.db import models
from django.utils.translation import gettext_lazy as _

from users.models import CEFRLevel


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