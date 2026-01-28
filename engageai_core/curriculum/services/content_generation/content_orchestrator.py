import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from asgiref.sync import sync_to_async

# --- добавляем корень проекта в PYTHONPATH ---
BASE_DIR = Path(__file__).resolve().parents[3]

sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "engageai_core.settings"
)

import django

django.setup()

from curriculum.models.content.course import Course
from curriculum.models.content.balance import CourseBalance
from curriculum.services.content_generation.course_generator import CourseGenerationService
from curriculum.services.content_generation.lesson_generator import LessonGenerationService
from curriculum.services.content_generation.task_generator import TaskGenerationService

logger = logging.getLogger(__name__)


class ContentOrchestrator:
    """
    Координатор полного цикла создания образовательного контента.
    Ответственность: оркестрация генерации курс → уроки → задания.
    """

    def __init__(self):
        self.course_generator = CourseGenerationService()
        self.lesson_generator = LessonGenerationService()
        self.task_generator = TaskGenerationService()

    async def generate_full_course(
            self,
            theme: str,
            num_lessons: int = 60,
            tasks_per_lesson: Optional[int] = None,
            include_media: bool = True,
            user_id: Optional[int] = None,
    ) -> Course:
        """
        Полный цикл создания курса с уроками и заданиями.

        Args:
            theme: Тема курса (например, "AI and LLMs for Developers")
            num_lessons: Общее количество уроков в курсе
            tasks_per_lesson: Количество заданий на урок (None = авто по уровню)
            include_media: Генерировать ли медиа для заданий (аудио для listening/speaking)
            user_id: id пользователя в интересах которого генерируется запрос
        """
        logger.info(f"Начата генерация курса по теме: '{theme}'")

        # Шаг 1: Создание курса
        course = await self.course_generator.generate(theme=theme, user_id=user_id)
        logger.info(f"Курс '{course.title}' создан (ID: {course.pk})")

        # Шаг 2: Генерация уроков
        lessons = await self._generate_lessons_for_course(
            course=course, num_lessons=num_lessons, tasks_per_lesson=tasks_per_lesson,
            include_media=include_media, user_id=user_id
        )

        logger.info(
            f"Курс '{course.title}' полностью сгенерирован: "
            f"{len(lessons)} уроков, ~{len(lessons) * (tasks_per_lesson or 5)} заданий"
        )

        return course

    async def _generate_lessons_for_course(
            self,
            course: Course,
            num_lessons: int,
            tasks_per_lesson: Optional[int],
            include_media: bool,
            user_id: Optional[int] = None,
    ) -> list:
        """Генерация уроков для курса на основе баланса"""
        course_balance = await CourseBalance.objects.aget(course=course)

        # Получаем профессиональные теги курса для контекста
        professional_tags = await sync_to_async(
            lambda: list(course.professional_tags.values_list('description', flat=True))
        )()

        lessons = []
        current_order = 0

        # Генерация по уровням согласно балансу
        for level, level_pct in course_balance.level_distribution.items():
            num_for_level = round(num_lessons * level_pct)

            # Выбор навыков для уровня (топ-3 по балансу)
            skill_items = sorted(
                course_balance.skill_distribution.items(),
                key=lambda x: -x[1]
            )[:3]
            skill_focus = [s for s, _ in skill_items]

            for i in range(num_for_level):
                # Генерация урока
                lesson = await self.lesson_generator.generate(
                    course=course,
                    order=current_order,
                    level=level,
                    skill_focus=skill_focus,
                    theme_tags=professional_tags,
                    user_id=user_id,
                )
                lessons.append(lesson)
                current_order += 1

                # Генерация заданий для урока
                num_tasks = tasks_per_lesson or (5 if level in ["A2", "B1"] else 6)
                await self.task_generator.generate_tasks_for_lesson(
                    lesson=lesson,
                    num_tasks=num_tasks,
                    include_media=include_media,
                    user_id=user_id,
                )

                logger.debug(
                    f"Урок {current_order}/{num_lessons} создан: {lesson.title} "
                    f"(уровень {level}, {num_tasks} заданий)"
                )
                if current_order > 3: # TODO временная заглушка
                    return lessons

        return lessons

    async def generate_single_lesson_with_tasks(
            self,
            course: Course,
            level: str,
            skill_focus: list[str],
            order: int = 0
    ) -> 'Lesson':
        """
        Утилита для генерации одного урока с заданиями (для ремедиации или адаптивного пути).
        """
        lesson = await self.lesson_generator.generate(
            course=course,
            order=order,
            level=level,
            skill_focus=skill_focus,
            theme_tags=[]
        )

        await self.task_generator.generate_tasks_for_lesson(
            lesson=lesson,
            num_tasks=5
        )

        return lesson


if __name__ == "__main__":
    o = ContentOrchestrator()
    asyncio.run(o.generate_full_course(theme="AI, LLM developer", user_id=2))
