import json
import logging
from typing import Optional

from asgiref.sync import sync_to_async
from django.db import transaction

from curriculum.models.content.task import Task, TaskType, ResponseFormat
from curriculum.services.content_generation.base_generator import BaseContentGenerator
from curriculum.validation.task_schemas import TASK_CONTENT_SCHEMAS
from llm_logger.models import LLMRequestType

logger = logging.getLogger(__name__)


class TaskGenerationService(BaseContentGenerator):
    """
    Сервис генерации заданий для уроков.
    Ответственность: создание заданий всех типов с детальным логированием.
    """

    async def generate(self, lesson, **kwargs) -> list[Task]:
        """Единая точка входа"""
        return await self.generate_tasks_for_lesson(lesson, **kwargs)

    async def generate_tasks_for_lesson(
            self,
            lesson,
            num_tasks: Optional[int] = None,
            include_media: bool = True,
            user_id: Optional[int] = None,

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
        if num_tasks is None:
            num_tasks = 5 if lesson.required_cefr in ["A1", "A2", "B1"] else 6

        # Этап 3: Генерация данных заданий через LLM
        try:
            tasks_data = await self._llm_generate_tasks_data(
                lesson=lesson,
                lesson_context=lesson_context,
                num_tasks=num_tasks,
                user_id=user_id,
            )
        except Exception as e:
            self.logger.exception(
                f"КРИТИЧЕСКАЯ ОШИБКА: не удалось сгенерировать данные заданий для урока",
                extra={
                    "lesson_id": lesson.pk,
                    "lesson_title": lesson.title,
                    "num_requested": num_tasks,
                    "error_type": type(e).__name__,
                    "error_message": str(e)[:200]
                }
            )
            raise

        # Этап 4: Создание заданий в БД
        created_tasks = []
        failed_tasks = 0

        for i, task_data in enumerate(tasks_data):
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
                'name', 'description', 'skill_domain', 'cefr_level'
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
                                       num_tasks: int, user_id: Optional[int] = None) -> list[dict]:
        """Генерация данных заданий через LLM"""
        # Определение доступных типов заданий
        available_schemas = self._get_available_schemas(lesson_context["skill_focus"])
        schemas_info = {
            name: {
                "description": schema["description"],
                "required_fields": list(schema["required"]),
                "example": self._get_schema_example(name)
            }
            for name, schema in TASK_CONTENT_SCHEMAS.items()
            if name in available_schemas
        }

        system_prompt = """You are an expert English assessment designer. Create exercises that test lesson objectives."""
        user_message = f"""
        Lesson: "{lesson_context['title']}" ({lesson_context['level']})
        Skills: {', '.join(lesson_context['skill_focus'])}
        Professional Context: {', '.join(lesson_context['professional_tags']) or 'general'}

        Learning Objectives:
        {self._format_objectives(lesson_context['learning_objectives'])}

        Theory Snippet:
        {lesson_context['theory_content']}

        Available Exercise Types:
        {json.dumps(schemas_info, indent=2, ensure_ascii=False)}

        Generate exactly {num_tasks} diverse exercises covering all lesson objectives.
        For listening exercises: set "requires_media": true and provide "media_script".

        Return ONLY valid JSON (no comments, no text):

        {{
          "exercises": [
            {{
              "task_type": "grammar",
              "response_format": "single_choice",
              "content": {{
                "prompt": "string",
                "options": ["string"]
              }},
              "requires_media": false,
              "media_script": null
            }}
            ...
          ]
        }}
        """
        print(user_message)

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

        return tasks_data["exercises"]

    def _get_available_schemas(self, skill_focus: list[str]) -> list[str]:
        """Определяет доступные схемы заданий по навыкам урока"""
        mapping = {
            "grammar": ["scq_v1", "mcq_v1", "short_text_v1"],
            "vocabulary": ["scq_v1", "mcq_v1", "short_text_v1"],
            "reading": ["scq_v1", "mcq_v1", "short_text_v1"],
            "listening": ["short_text_v1"],
            "writing": ["free_text_v1"],
            "speaking": ["audio_v1"]
        }

        schemas = []
        for skill in skill_focus:
            schemas.extend(mapping.get(skill, []))

        return list(set(schemas))

    def _get_schema_example(self, schema_name: str) -> dict:
        examples = {
            "scq_v1": {
                "prompt": "Which sentence is correct?",
                "options": ["I have went...", "I went...", "I have go..."],
                "correct_idx": 1,
                "explanation": "Past Simple for completed actions"
            },
            "mcq_v1": {
                "prompt": "Select all professional email phrases:",
                "options": ["Hey dude", "Dear Mr. Smith", "See ya", "Please find attached"],
                "correct_indices": [1, 3],
                "min_selections": 1,
                "max_selections": 2
            },
            "short_text_v1": {
                "prompt": "Past tense of 'write'?",
                "correct_answers": ["wrote"],
                "case_sensitive": False
            },
            "free_text_v1": {
                "prompt": "Write email requesting day off",
                "context_prompt": "Be polite and professional",
                "min_words": 80,
                "max_words": 150
            },
            "audio_v1": {
                "prompt": "Describe your project in 45 seconds",
                "context_prompt": "Explain to a new colleague",
                "min_duration_sec": 30,
                "max_duration_sec": 60
            }
        }
        return examples.get(schema_name, {})

    def _format_objectives(self, objectives: list) -> str:
        if not objectives:
            return "No specific objectives"
        return "\n".join([
            f"- {obj['name']} ({obj['skill_domain']}, {obj['cefr_level']}): {obj['description'][:80]}..."
            for obj in objectives
        ])

    def _determine_response_format(self, task_data: dict, content: dict) -> str:
        """Определяет формат ответа по структуре контента"""
        schema_map = {
            "scq_v1": ResponseFormat.SINGLE_CHOICE,
            "mcq_v1": ResponseFormat.MULTIPLE_CHOICE,
            "short_text_v1": ResponseFormat.SHORT_TEXT,
            "free_text_v1": ResponseFormat.FREE_TEXT,
            "audio_v1": ResponseFormat.AUDIO
        }

        schema = self._detect_schema(content)
        return schema_map.get(schema, ResponseFormat.SHORT_TEXT)

    def _detect_schema(self, content: dict) -> str:
        """Определяет схему по структуре контента"""
        if "options" in content:
            return "scq_v1" if "correct_idx" in content else "mcq_v1"
        elif "correct_answers" in content:
            return "short_text_v1"
        elif "min_words" in content and "max_words" in content:
            return "free_text_v1"
        elif "min_duration_sec" in content and "max_duration_sec" in content:
            return "audio_v1"
        return "scq_v1"

    @sync_to_async
    @transaction.atomic
    def _create_task_in_db(self, lesson, task_data: dict, order: int) -> Task:
        """Атомарное создание задания в БД"""
        content = task_data["content"]
        schema_version = self._detect_schema(content)
        response_format = self._determine_response_format(task_data, content)
        task_type = self._map_to_task_type(task_data["task_type"])

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

        # Привязка профессиональных тегов курса
        if lesson.course:
            tags = list(lesson.course.professional_tags.all())
            if tags:
                task.professional_tags.add(*tags)

        return task

    def _map_to_task_type(self, raw_type: str) -> str:
        """Маппинг строкового типа в константы модели"""
        mapping = {
            "grammar": TaskType.GRAMMAR,
            "vocabulary": TaskType.VOCABULARY,
            "reading": TaskType.READING,
            "listening": TaskType.LISTENING,
            "writing": TaskType.WRITING,
            "speaking": TaskType.SPEAKING
        }
        return mapping.get(raw_type, TaskType.VOCABULARY)

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
