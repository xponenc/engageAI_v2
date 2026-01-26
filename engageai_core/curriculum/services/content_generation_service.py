import asyncio
import os
import sys
from pathlib import Path
import json
import logging
from typing import Optional

from asgiref.sync import sync_to_async
from django.db import transaction, IntegrityError

# --- добавляем корень проекта в PYTHONPATH ---
BASE_DIR = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "engageai_core.settings"
)

import django

django.setup()

from curriculum.models import LearningObjective
from curriculum.models.content.course import Course
from curriculum.models.content.lesson import Lesson
from curriculum.models.systematization.professional_tag import ProfessionalTag
from curriculum.models.content.balance import CourseBalance, DEFAULT_COURSE_BALANCE
from ai.llm_service.factory import llm_factory

logger = logging.getLogger(__name__)


class ContentGenerationService:
    """
    Сервис генерации курсов и уроков с использованием LLM.

    Особенности:
    - Баланс CEFR и навыков фиксирован через DEFAULT_COURSE_BALANCE
    - Уроки генерируются по одному для точного контроля
    - Привязка LearningObjective и ProfessionalTag автоматически
    """

    def __init__(self):
        self.llm = llm_factory

    async def generate_course(self, theme: str, num_lessons: int = 60) -> Course:
        """
        Генерирует курс с базовым балансом и привязкой тегов.
        """
        # Курс
        try:
            course_data = await self._generate_course_data(theme)
        except Exception as e:
            logger.exception(
                f"КРИТИЧЕСКАЯ ОШИБКА: не удалось сгенерировать данные курса для темы '{theme}'",
                extra={
                    "theme": theme,
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                }
            )
            raise  # ← позволяем ошибке всплыть для обработки на уровне вызова
        try:
            course = await sync_to_async(Course.objects.create)(
                title=course_data["title"],
                description=course_data["description"],
                is_active=True
            )
            logger.info(f"Успешно создан курс: {course.title} (ID: {course.id})")
        except Exception as e:
            logger.exception(
                f"Ошибка сохранения курса в БД для темы '{theme}'",
                extra={"theme": theme, "course_data": course_data}
            )
            raise

        # Теги
        try:
            tags = await self._generate_professional_tags(theme=theme, course=course)
        except Exception as e:
            logger.exception(
                f"КРИТИЧЕСКАЯ ОШИБКА: не удалось теги для курса для темы '{course}'",
                extra={
                    "course": course,
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                }
            )
            raise

        await sync_to_async(course.professional_tags.set)(tags)
        logger.info(f"Привязано тегов: {len(tags)}")

        # Баланс уроков курса
        await sync_to_async(CourseBalance.objects.create)(
            course=course,
            total_lessons=DEFAULT_COURSE_BALANCE["total_lessons"],
            level_distribution=DEFAULT_COURSE_BALANCE["levels"],
            skill_distribution=DEFAULT_COURSE_BALANCE["skills"],
            frozen=True
        )

        # Генерация уроков ---
        await self._generate_lessons(course)

        return course

    async def generate_lesson(
            self,
            course: Course,
            order: int,
            level: str,
            skill_focus: list[str],
            theme_tags: list[str],
            user: Optional['User'] = None
    ) -> Lesson:
        """
        Универсальный генератор одного урока.
        Можно использовать как для базовой генерации, так и для адаптивного урока.
        """
        tags_str = ""
        if course:
            tags = await sync_to_async(list)(course.professional_tags.all())
            # tags_str = ', '.join(t.name for t in course.professional_tags.all())
            tags_str = ", ".join(t.name for t in tags)
        if theme_tags:
            tags_str += f", {', '.join(theme_tags)}" if tags_str else ', '.join(theme_tags)

        theme_str = ""
        if theme_tags:
            theme_str = f"Theme: professional, tags: {tags_str}."

        if skill_focus:
            focus_str = (f"Pay special attention to the following skills: {', '.join(skill_focus)}. "
                         f"These skills should dominate this lesson.")
        else:
            focus_str = ("Balance skills: grammar, vocabulary, reading, listening,"
                         " writing, speaking. Choose 1–3 relevant skills")
        system_prompt = """You are an expert English curriculum designer. """
        user_prompt = f"""
               Generate ONE lesson for course: 
               "{course.title if course else 'Adaptive professional English'}".
               Lesson CEFR level: {level}
               {theme_str}
               {focus_str}

               Rules:
               - skill_focus: array of EXACTLY these values only: grammar, vocabulary, reading, listening, writing, speaking. No more than 3.
               - learning_objectives: 1 to 3 objectives per lesson.
                 Use format: {{"identifier": "grammar-A2-01", "name": "Use Present Simple for routines", "cefr_level": "A2", "skill_domain": "grammar"}}
                 Do NOT invent fake identifiers — use logical ones like grammar-A2-01, vocabulary-B1-03, etc.
               - theory_content: detailed lesson theory in English (HTML or Markdown, 1000–1500 characters): explanation, examples, key phrases, tables, dialogues.
               - All text (title, description, theory_content, objective names) must be in ENGLISH.

               Return ONLY a valid JSON (no comments, no text):
               [
                   {{
                       "title": "short, attractive title in English",
                       "description": "150–250 characters in English",
                       "duration_minutes": int (20–40),
                       "skill_focus": ["grammar", "vocabulary"],
                       "theory_content": "HTML or Markdown text of the theory in English (1000–1500 characters)",
                       "learning_objectives": [
                           {{"identifier": "grammar-A2-01", "name": "Use Present Simple for routines", "cefr_level": "A2", "skill_domain": "grammar"}},
                           ...
                       ]
                   }}
               ]
               """
        context = {
            "course_id": course.pk,
            "user_id": user.pk if user else None,
        }
        result = await self.llm.generate_json_response(
            system_prompt=system_prompt,
            user_message=user_prompt,
            temperature=0.2,
            context=context
        )

        if result.error:
            logger.error(
                f"Ошибка генерации урока для курса '{course}': {result.error}",
                extra={"raw_response": result.raw_provider_response}
            )
            raise ValueError(f"Не удалось сгенерировать урок: {result.error}")
        lesson_data = result.response.message
        if not isinstance(lesson_data, dict):
            logger.error(
                f"Некорректный формат ответа для генерации урока к курсу '{course}': message не является словарём",
                extra={
                    "message_type": type(lesson_data).__name__,
                    "message_value": str(lesson_data)[:200],
                    "raw_response": result.raw_provider_response[:300] if result.raw_provider_response else None
                }
            )
            raise ValueError("Ответ не является JSON-объектом")

        print(lesson_data)

        # Создаём Lesson
        try:
            with transaction.atomic():
                lesson = await sync_to_async(Lesson.objects.create)(
                    course=course,
                    order=order,
                    title=lesson_data["title"],
                    description=lesson_data["description"],
                    duration_minutes=lesson_data["duration_minutes"],
                    required_cefr=level,
                    skill_focus=lesson_data["skill_focus"],
                    content=lesson_data["theory_content"],
                    is_active=True,
                    is_remedial=False
                )
                # Создание learning objectives
                objectives_to_add = []
                for obj_data in lesson_data.get("learning_objectives", []):
                    obj, _ = await sync_to_async(LearningObjective.objects.get_or_create)(
                        identifier=obj_data["identifier"],
                        defaults={
                            "name": obj_data["name"],
                            "cefr_level": obj_data["cefr_level"],
                            "skill_domain": obj_data["skill_domain"]
                        }
                    )
                    objectives_to_add.append(obj)

                # Bulk-добавление связей
                if objectives_to_add:
                    lesson.learning_objectives.add(*objectives_to_add)

        except IntegrityError as e:
            logger.exception(
                "DB integrity error during lesson creation",
                extra={"course_id": course.pk, "level": level, "lesson_data": lesson_data}
            )
            raise ValueError("Database error: lesson creation failed") from e
        except Exception as e:
            logger.exception(
                "Unexpected error in lesson generation",
                extra={"course_id": course.pk, "level": level, "lesson_data": lesson_data}
            )
            raise

        logger.info("Lesson created successfully", extra={
            "lesson_id": lesson.pk,
            "course": course.title,
            "level": level,
            "objectives_count": len(objectives_to_add)
        })

        return lesson

    async def _generate_course_data(self, theme: str) -> dict:
        prompt = ("Ты опытный и талантливый проектировщик курсов повышения уровня английского языка. "
                  "Выполни задание и ответь строго JSON")
        user_message = f"""
        Сгенерируй название и описание курса по теме "{theme}".
        Курс универсальный — уроки от A2 до C1, адаптивный путь под уровень студента.
        Баланс навыков: примерно равное покрытие grammar, vocabulary, listening, reading, writing, speaking.

        Верни ТОЛЬКО JSON:
        {{
            "title": "str (короткое, привлекательное название)",
            "description": "str (200–300 символов, мотивирующее описание)"
        }}
        """

        result = await self.llm.generate_json_response(
            system_prompt=prompt,
            user_message=user_message,
            temperature=0.3,
        )

        if result.error:
            logger.error(
                f"Ошибка генерации данных курса для темы '{theme}': {result.error}",
                extra={"raw_response": result.raw_provider_response}
            )
            raise ValueError(f"Не удалось сгенерировать курс: {result.error}")
        data = result.response.message
        if not isinstance(data, dict):
            logger.error(
                f"Некорректный формат ответа для генерации курса на тему '{theme}': message не является словарём",
                extra={
                    "message_type": type(data).__name__,
                    "message_value": str(data)[:200],
                    "raw_response": result.raw_provider_response[:300] if result.raw_provider_response else None
                }
            )
            raise ValueError("Ответ не является JSON-объектом")

        print(data)

        return data

    async def _generate_professional_tags(self, theme: str, course: Course) -> list[ProfessionalTag]:
        system_prompt = ("Ты опытный и талантливый проектировщик курсов повышения уровня английского языка. "
                         "Выполни задание и ответь строго JSON")
        user_message = f"""
        Придумай 8–12 коротких профессиональных тегов для темы курса "{theme}".
        Теги должны быть релевантны IT, бизнесу или профессии (backend, qa, standup-meetings, ticket-writing и т.д.).
        Короткие, уникальные, без пробелов.

        Верни ТОЛЬКО JSON:
        {{"tags": ["backend", "devops", "standup", ...]}}
        """

        result = await self.llm.generate_json_response(
            system_prompt=system_prompt,
            user_message=user_message,
            context={"course_id": course.pk},
            temperature=0.4,
        )

        if result.error:
            logger.error(
                f"Ошибка генерации тегов для курса '{course}': {result.error}",
                extra={"raw_response": result.raw_provider_response}
            )
            raise ValueError(f"Не удалось сгенерировать теги: {result.error}")
        data = result.response.message
        if not isinstance(data, dict):
            logger.error(
                f"Некорректный формат ответа генерации тегов для курса '{course}': message не является словарём",
                extra={
                    "message_type": type(data).__name__,
                    "message_value": str(data)[:200],
                    "raw_response": result.raw_provider_response[:300] if result.raw_provider_response else None
                }
            )
            raise ValueError("Ответ не является JSON-объектом")

        tags = []
        for name in data["tags"]:
            tag, created = await sync_to_async(ProfessionalTag.objects.get_or_create)(
                name=name,
                defaults={"description": f"Тег для темы {theme}"}
            )
            tags.append(tag)
        return tags

    async def _generate_lessons(self, course: Course):
        """
        Генерирует все уроки курса на основе CourseBalance.
        """
        course_balance = await sync_to_async(CourseBalance.objects.get)(course=course)
        last_order = 0

        # Генерация по уровням
        for level, level_pct in course_balance.level_distribution.items():
            num_lessons_level = round(course_balance.total_lessons * level_pct)
            for _ in range(num_lessons_level):
                # Выбираем до 3 навыков для урока
                sorted_skills = sorted(
                    course_balance.skill_distribution.items(),
                    key=lambda x: -x[1]
                )
                skill_focus = [s for s, pct in sorted_skills[:3]]

                # Генерация урока
                tags = await sync_to_async(list)(course.professional_tags.all())
                lesson = await self.generate_lesson(
                    course=course,
                    order=last_order,
                    level=level,
                    skill_focus=skill_focus,
                    theme_tags=[t.name for t in tags]
                )
                last_order += 1
                break

    # def _generate_tasks(self, lesson: Lesson, num_tasks: int = 4):
    #     ...


if __name__ == "__main__":
    generator = ContentGenerationService()
    asyncio.run(generator.generate_course(theme="AI, LLM", num_lessons=60))
