import json
import logging
from typing import Optional, List, Dict

from asgiref.sync import sync_to_async
from django.db import transaction
from django.db.models import Count

from curriculum.models import Course
from curriculum.models.content.lesson import Lesson
from curriculum.models.systematization.learning_objective import LearningObjective
from curriculum.services.content_generation.base_generator import BaseContentGenerator
from llm_logger.models import LLMRequestType

logger = logging.getLogger(__name__)


class LessonGenerationService(BaseContentGenerator):
    """
    Сервис генерации уроков с привязкой к целям обучения (LearningObjectives).
    Ответственность: только создание уроков на основе параметров.
    """

    async def generate(
            self,
            course,
            order: int,
            level: str,
            skill_focus: List[str],
            theme_tags: List[str],
            methodological_tags: Optional[List[Dict]] = None,
            user_id: Optional[int] = None
    ) -> Lesson:
        """
        Генерация одного урока:
        1. Получение данных через LLM
        2. Создание в БД с привязкой к целям обучения
        """

        try:
            lesson_data = await self._llm_generate_lesson_data(
                course=course,
                level=level,
                skill_focus=skill_focus,
                theme_tags=theme_tags,
                user_id=user_id,
                methodological_tags=methodological_tags
            )
        except Exception as e:
            self.logger.exception(
                f"КРИТИЧЕСКАЯ ОШИБКА: не удалось сгенерировать данные урока",
                extra={
                    "course_id": course.pk if course else None,
                    "level": level,
                    "skill_focus": skill_focus,
                    "error_type": type(e).__name__,
                    "error_message": str(e)[:200]
                }
            )
            raise

        try:
            lesson = await self._create_lesson(
                course=course,
                order=order,
                level=level,
                lesson_data=lesson_data
            )
            self.logger.info(
                f"Урок успешно создан: {lesson.title} (ID: {lesson.pk})",
                extra={
                    "lesson_id": lesson.pk,
                    "course_id": course.pk,
                    "level": level,
                    "skill_focus": skill_focus
                }
            )
        except Exception as e:
            self.logger.exception(
                f"Ошибка создания урока в БД",
                extra={
                    "course_id": course.pk,
                    "level": level,
                    "lesson_title": lesson_data.get("title", "N/A"),
                    "error_type": type(e).__name__,
                    "error_message": str(e)[:200]
                }
            )
            raise
        return lesson

    async def _llm_generate_lesson_data(self,
                                        course: Course,
                                        level: str,
                                        skill_focus: list[str],
                                        theme_tags: list[str],
                                        user_id: Optional[int] = None,
                                        methodological_tags: Optional[List[Dict]] = None,
                                        ) -> dict:
        """Генерация данных урока через LLM"""
        professional_tags_str = ""
        if theme_tags:
            professional_tags_str = "Professional tags for the topic: " + ', '.join(theme_tags)

        lesson_objectives = ""
        if methodological_tags:
            objectives_list = []
            for unit in methodological_tags:
                objectives_list.append(
                    f"• {unit['name']} ({unit['skill_domain']}) - {unit['description']}"
                )

            lesson_objectives = (
                f"MANDATORY LESSON OBJECTIVES (methodological plan):\n"
                f"{chr(10).join(objectives_list)}\n\n"
                f"CRITICAL: This lesson MUST fully cover ALL listed objectives.\n"
                f"Theory, examples, and tasks must directly address each objective."
            )
            skill_emphasis = f"Skills from objectives: {', '.join(skill_focus)}"
        elif skill_focus:
            # Fallback для обратной совместимости
            lesson_objectives = f"Focus skills: {', '.join(skill_focus)}"
            skill_emphasis = "These skills should dominate this lesson."
        else:
            lesson_objectives = f"Balance skills: grammar, vocabulary, reading, listening, writing, speaking. "
            skill_emphasis = "Choose 2–3 relevant skills"

        system_prompt = """You are an expert English language curriculum designer specializing in CEFR-aligned courses."""

        user_prompt = f"""
Generate ONE lesson for course: 
This is an ENGLISH LANGUAGE lesson. The learner studies English, not a profession.

Course: "{course.title if course else 'Adaptive professional English'}".
Lesson CEFR level: {level}
{professional_tags_str}

{lesson_objectives}

SKILL EMPHASIS: {skill_emphasis}

Rules:
- PRIMARY GOAL: teaching ENGLISH language skills.
  The lesson title, description, objectives, and theory must explicitly focus on learning English.
  Professional or thematic context is SECONDARY and may be used ONLY as examples, situations, dialogues, or vocabulary context.
- Professional or thematic context must NOT dominate the lesson.
  Do NOT teach the profession itself.
  Use professional context only to illustrate grammar, vocabulary, or communication in English.
- Skill_focus: array of EXACTLY these values only - {', '.join(skill_focus)}. No more than 3.
- Learning_objectives: 1 to 3 objectives per lesson.
  Use format: {{"name": "Use Present Simple for routines", "cefr_level": "A2", "skill_domain": "grammar", "description": "Detailed explanation for methodologists"}}
  Do NOT invent fake identifiers — use logical ones like grammar-A2-01, vocabulary-B1-03, etc.
- Theory_content: detailed ENGLISH LANGUAGE theory in English (HTML, Length: 300–450 words):
  Must fully explain the language material of the lesson:
  rule explanation, examples, key phrases, short tables or lists, and short dialogues.
  Professional context may appear ONLY inside examples and dialogues.
- All text (title, description, theory_content, objective names) must be in ENGLISH.

Return ONLY a valid JSON (no comments, no text):
[
   {{
       "title": "title": "short, attractive title in English with a clear focus on learning English (grammar, vocabulary, or communication), not the profession",
       "description": "description": "150–250 characters in English explaining what ENGLISH SKILL the learner will practice; professional context may be mentioned only as an example",
       "duration_minutes": int (20–40),
       "skill_focus": ["grammar", "vocabulary"],
       "theory_content": "HTML or Markdown text of the theory in English (1000–1500 characters)",
       "theory_content_ru": "HTML or Markdown — an exact translation of theory_content into Russian (same length, same formatting, do not translate important terms, you can limit yourself to translating explanations)",
       "learning_objectives": [
           {{"name": "Use Present Simple for routines", "cefr_level": "A2", "skill_domain": "grammar", "description": "Detailed explanation for methodologists"}},
           ...
       ]
   }}
]
                       """
        context = {
            "course_id": course.pk,
            "user_id": user_id,
            "request_type": LLMRequestType.LESSON_GENERATION.value,
        }

        data = await self._safe_llm_call(
            system_prompt=system_prompt,
            user_message=user_prompt,
            temperature=0.2,
            context=context,
            response_format=dict
        )

        return data

    @sync_to_async
    @transaction.atomic
    def _create_lesson(self, course, order: int, level: str, lesson_data: dict) -> Lesson:
        lesson = Lesson.objects.create(
            course=course,
            order=order,
            title=lesson_data["title"],
            description=lesson_data["description"],
            duration_minutes=lesson_data["duration_minutes"],
            required_cefr=level,
            skill_focus=lesson_data["skill_focus"],
            content=lesson_data["theory_content"],
            content_ru=lesson_data["theory_content_ru"],
            is_active=True,
            is_remedial=False,
        )

        # Привязка целей обучения
        objectives = []
        for obj_data in lesson_data.get("learning_objectives", []):
            # Поиск существующей цели или создание новой
            obj = LearningObjective.objects.filter(
                cefr_level=obj_data["cefr_level"],
                skill_domain=obj_data["skill_domain"],
                name=obj_data["name"]
            ).first()

            if not obj:
                # Определение порядка в уровне
                order_in_level = LearningObjective.objects.filter(
                    cefr_level=obj_data["cefr_level"],
                    skill_domain=obj_data["skill_domain"]
                ).count() + 1

                obj = LearningObjective.objects.create(
                    name=obj_data["name"],
                    cefr_level=obj_data["cefr_level"],
                    skill_domain=obj_data["skill_domain"],
                    order_in_level=order_in_level,
                    description=obj_data["description"],
                )

            objectives.append(obj)

        if objectives:
            lesson.learning_objectives.add(*objectives)

        return lesson