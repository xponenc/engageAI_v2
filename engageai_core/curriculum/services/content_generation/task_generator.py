import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

from asgiref.sync import sync_to_async
from django.core.exceptions import ValidationError

# --- добавляем корень проекта в PYTHONPATH ---
BASE_DIR = Path(__file__).resolve().parents[3]

sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "engageai_core.settings"
)

import django

django.setup()

from django.db import transaction

from curriculum.models.content.task import Task, TaskType, ResponseFormat
from curriculum.services.content_generation.base_generator import BaseContentGenerator
from curriculum.validation.task_schemas import TASK_CONTENT_SCHEMAS
from llm_logger.models import LLMRequestType
from curriculum.models import Lesson, LearningObjective

logger = logging.getLogger(__name__)


class TaskGenerationService(BaseContentGenerator):
    """
    Сервис генерации заданий для уроков.
    Ответственность: создание заданий всех типов с детальным логированием.
    """

    async def generate(
            self,
            lesson: Lesson,
            tasks_per_lesson: Optional[int] = None,
            include_media: bool = True,
            user_id: Optional[int] = None,
    ) -> list[Task]:
        """Единая точка входа"""
        return await self._generate_tasks_for_lesson(
            lesson=lesson,
            tasks_per_lesson=tasks_per_lesson,
            include_media=include_media,
            user_id=user_id,
            )

    async def _generate_tasks_for_lesson(
            self,
            lesson: Lesson,
            tasks_per_lesson: Optional[int] = None,
            include_media: bool = True,
            user_id: Optional[int] = None,
            **kwargs
    ) -> list[Task]:
        """
        Генерация заданий для урока
        """
        # Этап 1: Подготовка контекста урока
        try:
            lesson_context = await self._prepare_lesson_context(lesson)
        except Exception as e:
            self.logger.exception(
                f"КРИТИЧЕСКАЯ ОШИБКА: не удалось подготовить контекст урока для генерации заданий",
                extra={
                    "lesson_id": lesson.pk,
                    "error_type": type(e).__name__,
                    "error_message": str(e)[:200]
                }
            )
            raise

        # Этап 2: Определение количества заданий
        if tasks_per_lesson is None:
            tasks_per_lesson = 5 if lesson.required_cefr in ["A1", "A2", "B1"] else 6

        # Этап 3: Генерация данных заданий через LLM
        try:
            tasks_data = await self._llm_generate_tasks_data(
                lesson=lesson,
                lesson_context=lesson_context,
                tasks_per_lesson=tasks_per_lesson,
                user_id=user_id,
            )
        except Exception as e:
            self.logger.exception(
                f"КРИТИЧЕСКАЯ ОШИБКА: не удалось сгенерировать данные заданий для урока",
                extra={
                    "lesson_id": lesson.pk,
                    "lesson_title": lesson.title,
                    "tasks_per_lesson": tasks_per_lesson,
                    "error_type": type(e).__name__,
                    "error_message": str(e)[:200]
                }
            )
            raise

        # Этап 4: Создание заданий в БД
        created_tasks = []
        failed_tasks = 0

        for i, task_data in enumerate(tasks_data, start=1):
            try:
                task = await self._create_task_in_db(lesson, task_data, order=i)
                created_tasks.append(task)

                # Обработка медиа (заглушка для будущей интеграции)
                if include_media and task_data.get("requires_media"):
                    await self._handle_media_requirement(task, task_data)

            except Exception as e:
                failed_tasks += 1
                self.logger.error(
                    f"Ошибка создания задания #{i + 1}/{len(tasks_data)} для урока {lesson.pk}",
                    extra={
                        "lesson_id": lesson.pk,
                        "task_index": i,
                        "task_type": task_data.get("task_type", "unknown"),
                        "error_type": type(e).__name__,
                        "error_message": str(e)[:200],
                        "task_data": {k: v for k, v in task_data.items() if k != "content"}  # Без контента для лога
                    },
                    exc_info=True
                )
                continue  # Продолжаем создание остальных заданий

        # Финальный лог
        if failed_tasks > 0:
            self.logger.warning(
                f"Создано {len(created_tasks)}/{len(tasks_data)} заданий для урока '{lesson.title}' "
                f"({failed_tasks} неудачных попыток)",
                extra={
                    "lesson_id": lesson.pk,
                    "success_count": len(created_tasks),
                    "failed_count": failed_tasks,
                    "total_requested": len(tasks_data)
                }
            )
        else:
            self.logger.info(
                f"Успешно создано {len(created_tasks)} заданий для урока '{lesson.title}'",
                extra={
                    "lesson_id": lesson.pk,
                    "task_count": len(created_tasks)
                }
            )

        return created_tasks

    async def _prepare_lesson_context(self, lesson) -> dict:
        """Подготовка контекста урока для LLM"""
        objectives = await self._atomic_db_operation(
            lambda: list(lesson.learning_objectives.values(
                'name', 'description', 'skill_domain', 'cefr_level', 'identifier'
            ))
        )

        professional_tags = await self._atomic_db_operation(
            lambda: list(lesson.course.professional_tags.values_list('name', flat=True))
        )

        return {
            "title": lesson.title,
            "description": lesson.description,
            "theory_content": lesson.content[:1500],
            "level": lesson.required_cefr,
            "skill_focus": lesson.skill_focus,
            "learning_objectives": objectives,
            "professional_tags": list(professional_tags),
            "duration_minutes": lesson.duration_minutes
        }

    async def _llm_generate_tasks_data(self, lesson, lesson_context: dict,
                                       tasks_per_lesson: int, user_id: Optional[int] = None) -> list[dict]:
        """Генерация данных заданий через LLM"""
        # Определение доступных типов заданий
        available_schemas = self._get_available_schemas(lesson_context["skill_focus"])
        schemas_info = {
            name: {
                "version": name,
                "response_format": schema["response_format"],
                "description": schema["description"],
                "example": schema["example"],
            }
            for name, schema in TASK_CONTENT_SCHEMAS.items()
            if name in available_schemas
        }

        system_prompt = """
You are an expert English assessment designer.

Your task is to generate high-quality lesson exercises that:
- strictly match the provided exercise schemas
- assess the specified language skills
- are appropriate for the given CEFR level
- can be validated automatically without manual fixes

You follow instructions precisely and return only valid JSON.
"""
#         user_message = f"""
# Lesson: "{lesson_context['title']}" (CEFR Level: {lesson_context['level']})
#
# Skills assessed in this lesson:
# {', '.join(lesson_context['skill_focus'])}
#
# Professional Context:
# {', '.join(lesson_context['professional_tags']) or 'general'}
#
# Learning Objectives:
# {self._format_objectives(lesson_context['learning_objectives'])}
#
# Theory Snippet:
# {self.remove_html_tags(lesson_context['theory_content'])}
#
# Available exercise types:
# Each exercise type below defines:
# - a validation version ("version")
# - a response format
# - an example that represents the exact required content structure
# {json.dumps(schemas_info, indent=2, ensure_ascii=False)}
#
# Generate exactly {tasks_per_lesson} diverse exercises covering all lesson objectives.
# RULES (STRICT):
# 1. Each exercise MUST include:
#    - task_type: one of [{', '.join(lesson_context['skill_focus'])}]
#    - version: one of the available exercise type keys
#    - response_format: must match the response_format of the chosen version
#    - content: MUST strictly match the example structure of that version
# 2. All fields shown in the example are REQUIRED.
# 3. Do NOT add extra fields inside "content".
# 4. Field names must match the example exactly.
# 5. Use only the provided versions. Do NOT invent new versions.
# 6. Exercises must collectively cover ALL listed learning objectives.
# 7. Listening exercises are NOT required for this lesson.
#
# MEDIA RULES:
# - requires_media:  boolean (true if the exercise is a listening task, false otherwise)
# - media_script: string (the transcript for listening exercises; empty string "" if not applicable)
#
# Return ONLY valid JSON in the following format:
#
# {{
#   "exercises": [
#     {{
#       "task_type": "grammar",
#       "version": "scq_v1",
#       "response_format": "single_choice",
#       "content": {{
#         "...": "exactly as in the example of the chosen version"
#       }},
#       "requires_media": false,
#       "media_script": null
#     }}
#   ]
# }}
#         """

        user_message = f"""
Lesson: "{lesson_context['title']}" (CEFR Level: {lesson_context['level']})

Skills assessed in this lesson:
{', '.join(lesson_context['skill_focus'])}

Professional Context:
{', '.join(lesson_context['professional_tags']) or 'general'}

Learning Objectives:
{self._format_objectives(lesson_context['learning_objectives'])}

Theory Snippet:
{self.remove_html_tags(lesson_context['theory_content'])}

Available exercise types:
Each exercise type below defines:
- a validation version ("version")
- a response format
- an example that represents the exact required content structure
{json.dumps(schemas_info, indent=2, ensure_ascii=False)}

Choose the optimal number of exercises for objective lesson assessment 
(NOT LESS THAN {tasks_per_lesson}). 

RECOMMENDED:
- Each learning objective should have 1-2 dedicated exercises
- Mix exercise types within skill domains when possible

RULES (STRICT):
1. Each exercise MUST include:
   - task_type: one of [{', '.join(lesson_context['skill_focus'])}]
   - version: one of the available exercise type keys
   - response_format: must match the response_format of the chosen version
   - content: MUST strictly match the example structure of that version
2. All fields shown in the example are REQUIRED.
3. Do NOT add extra fields inside "content".
4. Field names must match the example exactly.
5. Use only the provided versions. Do NOT invent new versions.
6. Exercises must collectively cover ALL listed learning objectives.
7. Listening exercises are NOT required for this lesson.
8. Each exercise MUST explicitly reference which learning objective(s) it assesses.
9. You MUST use ONLY the learning objectives listed above.
10. Use the field:
    "content" field MUST strictly match the structure of the example for the selected version.
    "learning_objectives": ["<identifier>", "..."] Lus identifiers from the Learning Objectives used for this task
    "content": The 'content' assignment should be clearly and unambiguously understood. The assignment should also 
    be understandable when viewed outside of the lesson context.
11. Each exercise should normally assess exactly ONE learning objective.
    Use multiple objectives only if strictly necessary.


MEDIA RULES:
- requires_media:  boolean (true if the exercise is a listening task, false otherwise)
- media_script: string (the transcript for listening exercises; empty string "" if not applicable)

Return ONLY valid JSON in the following format:

{{
  "exercises": [
    {{
      "task_type": "grammar",
      "version": "scq_v1",
      "response_format": "single_choice",
      "learning_objectives": ["grammar-B1-01"],
      "content": {{
        "...": "exactly as in the example of the chosen version"
      }},
      "requires_media": false,
      "media_script": null
    }}
  ]
}}
        """
        context = {
            "course_id": lesson.course.pk,
            "lesson_id": lesson.pk,
            "user_id": user_id,
            "request_type": LLMRequestType.TASK_GENERATION.value,
        }

        tasks_data = await self._safe_llm_call(system_prompt=system_prompt, user_message=user_message,
                                               context=context, temperature=0.35, response_format=dict)
        if "exercises" not in tasks_data or not isinstance(tasks_data["exercises"], list):
            raise ValueError(f"Invalid tags format: {tasks_data}"[:200])

        await sync_to_async(self._validate_task_learning_objectives)(
            task_data=tasks_data["exercises"], lesson=lesson
        )

        return tasks_data["exercises"]

    @staticmethod
    def _validate_task_learning_objectives(task_data, lesson):
        """Проверяет что задаче назначен LearningObjective из LO урока"""
        lesson_lo_ids = set(
            lesson.learning_objectives.values_list("identifier", flat=True)
        )
        print(lesson_lo_ids)
        print(task_data)
        for task in task_data:
            for lo_id in task["learning_objectives"]:
                if lo_id not in lesson_lo_ids:
                    raise ValidationError(
                        f"Invalid learning objective {lo_id} for lesson {lesson.id}"
                    )

    def _get_available_schemas(self, skill_focus: list[str]) -> list[str]:
        """
        Определяет доступные схемы заданий по навыкам урока
        на основе TASK_CONTENT_SCHEMAS.supported_skills
        схема берется на генерацию только если is_generation_enabled
        """
        lesson_skills = set(skill_focus)

        return [
            schema_name
            for schema_name, schema in TASK_CONTENT_SCHEMAS.items()
            if schema.get("is_generation_enabled", False)
            if lesson_skills & schema.get("supported_skills", set())
        ]

    @staticmethod
    def remove_html_tags(text):
        clean = re.compile('<.*?>')
        return re.sub(clean, '', text)

    def _format_objectives(self, objectives: list) -> str:
        if not objectives:
            return "No specific objectives"
        return "\n".join([
            f"- {obj['name']} ({obj['skill_domain']}, {obj['cefr_level']})(identifier: {obj['identifier']}): {obj['description']}"
            for obj in objectives
        ])


    @sync_to_async
    @transaction.atomic
    def _create_task_in_db(self, lesson, task_data: dict, order: int) -> Task:
        """Атомарное создание задания в БД"""
        content = task_data["content"]
        response_format = task_data["response_format"]
        schema_version = task_data["version"]
        task_type = task_data["task_type"]

        task = Task.objects.create(
            lesson=lesson,
            task_type=task_type,
            response_format=response_format,
            content=content,
            content_schema_version=schema_version,
            difficulty_cefr=lesson.required_cefr,
            is_diagnostic=False,
            is_active=True,
            order=order
        )

        learning_objectives = task_data["learning_objectives"]
        task.learning_objectives.set(
            LearningObjective.objects.filter(
                identifier__in=learning_objectives
            )
        )

        # TODO обработка и создание фалов для listening заданий
        media_script = task_data["media_script"]
        requires_media = task_data["requires_media"]

        # Привязка профессиональных тегов курса
        if lesson.course:
            tags = list(lesson.course.professional_tags.all())
            if tags:
                task.professional_tags.add(*tags)

        return task

    async def _handle_media_requirement(self, task: Task, task_data: dict):
        """Обработка требований к медиа (заглушка для интеграции с TTS)"""
        if task_data.get("media_script"):
            self.logger.info(
                f"Требуется аудио для задания {task.pk}: {task_data['media_script'][:100]}...",
                extra={
                    "task_id": task.pk,
                    "task_type": task.task_type,
                    "media_type": "audio"
                }
            )
            # TODO: Интеграция с TTS сервисом
            # После генерации:
            # await self._create_task_media(task, audio_path, MediaType.AUDIO)


if __name__ == "__main__":
    tgs = TaskGenerationService()
    asyncio.run(tgs.generate(lesson=Lesson.objects.get(id=27), user_id=2))