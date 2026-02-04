import asyncio
import logging
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Optional, List, Dict

from asgiref.sync import sync_to_async


# --- добавляем корень проекта в PYTHONPATH ---
BASE_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "engageai_core.settings")
import django

django.setup()

from django.db import models

from curriculum.models import Course, Lesson, CourseBalance
from curriculum.models.content.methodological_plan import MethodologicalPlan
from curriculum.services.content_generation.methodological_plan_loader import MethodologicalPlanLoader, LEVEL_ORDER, \
    SKILL_ORDER

from curriculum.services.content_generation.course_generator import CourseGenerationService
from curriculum.services.content_generation.lesson_generator import LessonGenerationService
from curriculum.services.content_generation.task_generator import TaskGenerationService

logger = logging.getLogger(__name__)


class ContentOrchestrator:
    def __init__(self):
        self.course_generator = CourseGenerationService()
        self.lesson_generator = LessonGenerationService()
        self.task_generator = TaskGenerationService()
        self.plan_loader = MethodologicalPlanLoader()

    async def generate_full_course(
            self,
            theme: str,
            tasks_per_lesson: Optional[int] = None,
            include_media: bool = True,
            user_id: Optional[int] = None,
    ) -> Course:
        """Генерация полного курса: приоритет методплану, fallback на CourseBalance"""
        logger.info(f"Начата генерация курса по теме: '{theme}'")

        # Шаг 1: Создание курса (без изменений)
        course = await self.course_generator.generate(theme=theme, user_id=user_id)
        logger.info(f"Курс '{course.title}' создан (ID: {course.pk})")

        # Шаг 2: Генерация уроков по приоритету
        lessons = await self._generate_lessons_smart(
            course=course,
            tasks_per_lesson=tasks_per_lesson,
            include_media=include_media,
            user_id=user_id
        )

        logger.info(
            f"Курс '{course.title}' полностью сгенерирован: "
            f"{len(lessons)} уроков"
        )

        return course

    async def _generate_lessons_smart(
            self,
            course: Course,
            user_id: int,
            tasks_per_lesson: Optional[int] = None,
            include_media: bool = True,
        ):
        """Умная генерация с учётом LearningPlan"""
        # Проверяем, есть ли уже план для курса
        existing_plan = await sync_to_async(
            MethodologicalPlan.objects.filter(course=course).first
        )()

        if existing_plan and not existing_plan.is_complete:
            logger.info(f"Восстановление генерации: {existing_plan}")
            return await self._resume_from_learning_plan(course=course, plan=existing_plan, user_id=user_id,
                                                         include_media=include_media, tasks_per_lesson=tasks_per_lesson)

        # Новая генерация
        return await self._generate_lessons_new_plan(course, user_id=user_id,
                                                     tasks_per_lesson=tasks_per_lesson, include_media=include_media)

    async def _generate_lessons_new_plan(
            self,
            course: Course,
            user_id: int,
            tasks_per_lesson: Optional[int] = None,
            include_media: bool = True,
    ):
        """Новая генерация с сохранением плана"""
        try:
            plan_data = await self.plan_loader.load_full_plan()
            if plan_data['coverage'] > 0.99:
                await sync_to_async(MethodologicalPlan.objects.create)(
                    course=course,
                    plan_data=plan_data['plan'],
                    total_units=plan_data['total_units'],
                    levels=self._calc_level_stats(plan_data['plan']),
                    skills=self._calc_skill_stats(plan_data['plan']),
                )

                lessons = await self._generate_lessons_from_methodological_plan(
                    course=course,
                    plan=plan_data['plan'],
                    tasks_per_lesson=tasks_per_lesson,
                    include_media=include_media,
                    user_id=user_id,
                )
                await self._mark_plan_complete(course)
                return lessons

        except Exception as e:
            logger.warning(f"Методплан недоступен: {e}")

        # Fallback
        return await self._generate_lessons_for_course(
            course=course, num_lessons=60, tasks_per_lesson=tasks_per_lesson,
            include_media=include_media, user_id=user_id
        )

    async def _resume_from_learning_plan(
            self,
            course: Course,
            plan: MethodologicalPlan,
            tasks_per_lesson: Optional[int],
            include_media: bool,
            user_id:int):
        """Продолжение генерации с места сбоя"""
        logger.info(f"Возобновление: урок {plan.last_lesson_order + 1}")

        # Загружаем план из БД
        plan_dict = plan.plan_data
        lessons = []
        current_order = plan.last_lesson_order + 1

        # Находим, с какого уровня продолжить
        start_level = self._find_resume_level(plan_dict, plan.generated_units)

        professional_tags = await sync_to_async(
            lambda: list(course.professional_tags.values_list('description', flat=True))
        )()

        for level in LEVEL_ORDER:
            if level < start_level:
                continue

            units_for_level = self._get_ordered_units_for_level(plan_dict[level])
            lesson_groups = self._group_units_into_lessons(units_for_level)

            # for methodological_tags in lesson_groups:
            #     lesson = await self.lesson_generator.generate(
            #         course=course,
            #         order=current_order,
            #         level=level,
            #         skill_focus=skill_focus,
            #         theme_tags=professional_tags,
            #         methodological_tags=methodological_tags,
            #         user_id=user_id,
            #     )

            for group_idx, methodological_tags in enumerate(lesson_groups, 1):
                # Определяем параметры урока
                first_unit = methodological_tags[0]
                level = first_unit['cefr_level']
                skill_focus = list({unit['skill_domain'] for unit in methodological_tags})

                # Генерация урока с methodological_tags
                lesson = await self.lesson_generator.generate(
                    course=course,
                    order=current_order,
                    level=level,
                    skill_focus=skill_focus,
                    theme_tags=professional_tags,
                    methodological_tags=methodological_tags,
                    user_id=user_id,
                )
                # Сохраняем в metadata
                lesson.metadata['methodological_tags'] = methodological_tags
                await sync_to_async(lesson.save)()

                lessons.append(lesson)
                current_order += 1

                # Обновляем прогресс
                plan.generated_units += len(methodological_tags)
                plan.last_lesson_order = lesson.order
                await sync_to_async(plan.save)()

                # Генерация заданий
                tasks_per_lesson = tasks_per_lesson or (5 if level in ["A2", "B1"] else 6)
                await self.task_generator.generate(
                    lesson=lesson,
                    tasks_per_lesson=tasks_per_lesson,
                    include_media=include_media,
                    user_id=user_id,
                )

                logger.debug(
                    f"Урок {current_order - 1} ({level}): {len(methodological_tags)} юнитов, "
                    f"skills: {skill_focus}"
                )

        await self._mark_plan_complete(course)
        logger.info(f"Методплан догенерирован: {len(lessons)} уроков")
        return lessons

    async def _mark_plan_complete(self, course: Course):
        """Отметить план завершённым"""
        await sync_to_async(
            MethodologicalPlan.objects
            .filter(course=course, is_complete=False)
            .update
        )(
            is_complete=True,
            generated_units=models.F("total_units"),
        )

    def _find_resume_level(self, plan_dict: Dict, generated_units: int) -> str:
        """Определяет уровень для возобновления"""
        cumulative = 0
        for level in LEVEL_ORDER:
            level_units = sum(len(skill_units) for skill_units in plan_dict.get(level, {}).values())
            if cumulative + level_units > generated_units:
                return level
            cumulative += level_units
        return LEVEL_ORDER[-1]

    def _calc_level_stats(self, plan: Dict) -> Dict:
        stats = {}
        for level, skills in plan.items():
            stats[level] = sum(len(units) for units in skills.values())
        return stats

    def _calc_skill_stats(self, plan: Dict) -> Dict[str, int]:
        skill_count: Dict[str, int] = {}
        for level_skills in plan.values():
            for skill_name, units in level_skills.items():
                skill_count[skill_name] = skill_count.get(skill_name, 0) + len(units)
        return skill_count

    async def _generate_lessons_from_methodological_plan(
            self,
            course: Course,
            plan: Dict[str, Dict[str, List[Dict]]],
            tasks_per_lesson: Optional[int],
            include_media: bool,
            user_id: Optional[int] = None,
    ) -> List[Lesson]:
        """Генерация уроков строго по методологическому плану"""
        lessons = []
        current_order = 1  # Начинаем с 1

        # Получаем профессиональные теги
        professional_tags = await sync_to_async(
            lambda: list(course.professional_tags.values_list('description', flat=True))
        )()

        for level in LEVEL_ORDER:
            if level not in plan:
                logger.warning(f"Уровень {level} отсутствует в плане")
                continue

            # Собираем все юниты уровня в правильном порядке
            units_for_level = self._get_ordered_units_for_level(plan[level])

            if not units_for_level:
                continue

            logger.info(f"Генерация уроков уровня {level}: {len(units_for_level)} юнитов")

            # Группируем юниты в уроки (1-3 юнита на урок)
            lesson_groups = self._group_units_into_lessons(units_for_level)

            for group_idx, methodological_tags in enumerate(lesson_groups, 1):
                # Определяем параметры урока
                first_unit = methodological_tags[0]
                level = first_unit['cefr_level']
                skill_focus = list({unit['skill_domain'] for unit in methodological_tags})

                # Генерация урока с methodological_tags
                lesson = await self.lesson_generator.generate(
                    course=course,
                    order=current_order,
                    level=level,
                    skill_focus=skill_focus,
                    theme_tags=professional_tags,
                    methodological_tags=methodological_tags,
                    user_id=user_id,
                )

                # Сохраняем methodological_tags в metadata для восстановления
                lesson.metadata['methodological_tags'] = methodological_tags
                await sync_to_async(lesson.save)()

                lessons.append(lesson)
                current_order += 1

                # Генерация заданий
                tasks_per_lesson = tasks_per_lesson or (5 if level in ["A2", "B1"] else 6)
                await self.task_generator.generate(
                    lesson=lesson,
                    tasks_per_lesson=tasks_per_lesson,
                    include_media=include_media,
                    user_id=user_id,
                )

                logger.debug(
                    f"Урок {current_order - 1} ({level}): {len(methodological_tags)} юнитов, "
                    f"skills: {skill_focus}"
                )

                if current_order > 3:  # TODO временная заглушка
                    return lessons

        logger.info(f"Методплан завершен: {len(lessons)} уроков")
        return lessons

    def _get_ordered_units_for_level(self, level_plan: Dict[str, List[Dict]]) -> List[Dict]:
        """Собирает все юниты уровня в порядке: skill_order + order_in_level"""
        all_units = []
        for skill in SKILL_ORDER:
            if skill in level_plan:
                units = level_plan[skill]
                units.sort(key=lambda x: x.get('order_in_level', float('inf')))
                all_units.extend(units)
        return all_units

    def _group_units_into_lessons(self, units: List[Dict], max_per_lesson: int = 3) -> List[List[Dict]]:
        """Группирует юниты в уроки: 1-3 юнита, разнообразие skills"""
        lessons = []
        i = 0

        while i < len(units):
            lesson_units = [units[i]]
            used_skills = {units[i]['skill_domain']}

            # Добавляем до 2 дополнительных юнитов с разными skills
            j = i + 1
            while len(lesson_units) < max_per_lesson and j < len(units):
                candidate_skill = units[j]['skill_domain']
                if candidate_skill not in used_skills:
                    lesson_units.append(units[j])
                    used_skills.add(candidate_skill)
                j += 1

            lessons.append(lesson_units)
            i += len(lesson_units)

        return lessons

    # СТАРЫЙ МЕТОД _generate_lessons_for_course ОСТАЕТСЯ БЕЗ ИЗМЕНЕНИЙ
    # (fallback логика)
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
                tasks_per_lesson = tasks_per_lesson or (5 if level in ["A2", "B1"] else 6)
                await self.task_generator.generate(
                    lesson=lesson,
                    tasks_per_lesson=tasks_per_lesson,
                    include_media=include_media,
                    user_id=user_id,
                )

                logger.debug(
                    f"Урок {current_order}/{num_lessons} создан: {lesson.title} "
                    f"(уровень {level}, {tasks_per_lesson} заданий)"
                )
                if current_order > 3:  # TODO временная заглушка
                    return lessons

        return lessons


if __name__ == "__main__":
    o = ContentOrchestrator()
    asyncio.run(o.generate_full_course(theme="AI, LLM developer", user_id=2))
