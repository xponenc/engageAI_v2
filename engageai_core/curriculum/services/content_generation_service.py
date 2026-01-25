import asyncio
import os
import sys
from pathlib import Path

from curriculum.models.content.balance import CourseBalance, DEFAULT_COURSE_BALANCE

# --- добавляем корень проекта в PYTHONPATH ---
BASE_DIR = Path(__file__).resolve().parents[2]
print(BASE_DIR)
# parents[3]:
# services → curriculum → engageai_core → engageai_v2

sys.path.insert(0, str(BASE_DIR))
print(sys.path[0])

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "engageai_core.settings"
)

import django

django.setup()

from django.db import models

from ai.llm.llm_factory import llm_factory
from curriculum.models import LearningObjective
from curriculum.models.content.course import Course
from curriculum.models.content.lesson import Lesson
from curriculum.models.systematization.professional_tag import ProfessionalTag
import json
import logging

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

    def generate_course(self, theme: str, num_lessons: int = 60) -> Course:
        """
        Генерирует курс с базовым балансом и привязкой тегов.
        """
        # --- Шаг 1: Данные курса ---
        course_data = self._generate_course_data(theme)
        course = Course.objects.create(
            title=course_data["title"],
            description=course_data["description"],
            is_active=True
        )
        logger.info(f"Создан курс: {course.title}")

        # --- Шаг 2: Теги ---
        tags = self._generate_professional_tags(theme)
        course.professional_tags.set(tags)
        logger.info(f"Привязано тегов: {len(tags)}")

        # --- Шаг 3: CourseBalance ---
        CourseBalance.objects.create(
            course=course,
            total_lessons=DEFAULT_COURSE_BALANCE["total_lessons"],
            level_distribution=DEFAULT_COURSE_BALANCE["levels"],
            skill_distribution=DEFAULT_COURSE_BALANCE["skills"],
            frozen=True
        )

        # --- Шаг 4: Генерация уроков ---
        self._generate_lessons(course)

        return course

    def generate_lesson(
            self,
            course: Course,
            order: int,
            level: str,
            skill_focus: list[str],
            theme_tags: list[str]
    ) -> Lesson:
        """
        Универсальный генератор одного урока.
        Можно использовать как для базовой генерации, так и для адаптивного урока.
        """
        tags_str = ""
        if course:
            tags_str = ', '.join(t.name for t in course.professional_tags.all())
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

        prompt = f"""
               You are an expert English curriculum designer.
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

        response = asyncio.run(self.llm.generate_json_response(
            system_prompt=prompt,
            user_message=""
        ))
        json_text = response.response.get("response", "").strip()
        data = json.loads(json_text)[0]  # Только один урок

        # Создаём Lesson
        lesson = Lesson.objects.create(
            course=course,
            order=order,
            title=data["title"],
            description=data["description"],
            duration_minutes=data["duration_minutes"],
            required_cefr=level,
            skill_focus=data["skill_focus"],
            theory_content=data["theory_content"],
            is_active=True,
            is_remedial=False
        )

        # Привязка learning objectives
        for obj_data in data.get("learning_objectives", []):
            obj, _ = LearningObjective.objects.get_or_create(
                identifier=obj_data["identifier"],
                defaults={
                    "name": obj_data["name"],
                    "cefr_level": obj_data["cefr_level"],
                    "skill_domain": obj_data["skill_domain"]
                }
            )
            lesson.learning_objectives.add(obj)

        logger.info(f"Создан урок: {lesson.title} ({level})")
        return lesson

    def _generate_course_data(self, theme: str) -> dict:
        prompt = f"""
        Сгенерируй название и описание курса по теме "{theme}".
        Курс универсальный — уроки от A2 до C1, адаптивный путь под уровень студента.
        Баланс навыков: примерно равное покрытие grammar, vocabulary, listening, reading, writing, speaking.

        Верни ТОЛЬКО JSON:
        {{
            "title": "str (короткое, привлекательное название)",
            "description": "str (200–300 символов, мотивирующее описание)"
        }}
        """

        print(prompt)

        response = asyncio.run(self.llm.generate_json_response(
            system_prompt=prompt,
            user_message="",
        ))
        print(response)
        json_text = response.response.get("response", "").strip()
        data = json.loads(json_text)
        print(data)

        return data

    def _generate_professional_tags(self, theme: str) -> list[ProfessionalTag]:
        prompt = f"""
        Придумай 8–12 коротких профессиональных тегов для темы курса "{theme}".
        Теги должны быть релевантны IT, бизнесу или профессии (backend, qa, standup-meetings, ticket-writing и т.д.).
        Короткие, уникальные, без пробелов.

        Верни ТОЛЬКО JSON:
        {{"tags": ["backend", "devops", "standup", ...]}}
        """
        print(prompt)
        response = asyncio.run(self.llm.generate_json_response(
            system_prompt=prompt,
            user_message="",
        ))
        print(response)
        json_text = response.response.get("response", "").strip()
        data = json.loads(json_text)
        print(data)

        tags = []
        for name in data["tags"]:
            tag, created = ProfessionalTag.objects.get_or_create(
                name=name,
                defaults={"description": f"Тег для темы {theme}"}
            )
            tags.append(tag)
        print(tags)
        return tags

    def _generate_lessons(self, course: Course):
        """
        Генерирует все уроки курса на основе CourseBalance.
        """
        course_balance = CourseBalance.objects.get(course=course)
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
                lesson = self.generate_lesson(
                    course=course,
                    order=last_order + 1,
                    level=level,
                    skill_focus=skill_focus,
                    theme_tags=[t.name for t in course.professional_tags.all()]
                )
                last_order += 1

    # def _generate_tasks(self, lesson: Lesson, num_tasks: int = 4):
    #     ...


if __name__ == "__main__":
    generator = ContentGenerationService()
    generator.generate_course(theme="AI, LLM", num_lessons=60)
