import json
import logging
from typing import Optional

from asgiref.sync import sync_to_async
from django.db import transaction

from curriculum.models.content.course import Course
from curriculum.models.content.balance import CourseBalance, DEFAULT_COURSE_BALANCE
from curriculum.models.systematization.professional_tag import ProfessionalTag
from curriculum.services.content_generation.base_generator import BaseContentGenerator
from llm_logger.models import LLMRequestType

logger = logging.getLogger(__name__)


class CourseGenerationService(BaseContentGenerator):
    """
    Сервис генерации курсов с привязкой профессиональных тегов и баланса уроков.
    Ответственность: только создание курса и его метаданных.
    """

    async def generate(self,
                       theme: str,
                       user_id: Optional[int] = None,
                       ) -> Course:
        """
        Полный цикл создания курса с детальным логированием и гарантией атомарности.
        Соответствует требованиям ТЗ: Задача 2.1 (надёжность), Задача 5.1 (логирование для анализа аномалий).
        """

        # Шаг 1: Генерация данных курса
        try:
            course_data = await self._generate_course_data(theme=theme, user_id=user_id)
        except Exception as e:
            self.logger.exception(
                f"КРИТИЧЕСКАЯ ОШИБКА: не удалось сгенерировать данные курса для темы '{theme}'",
                extra={
                    "theme": theme,
                    "error_type": type(e).__name__,
                    "error_message": str(e)[:200]
                }
            )
            raise  # Пробрасываем для отката транзакции на уровне оркестратора

        # Шаг 2: Сохранение курса
        try:
            course = await self._create_course(course_data)
            self.logger.info(
                f"Курс успешно создан: {course.title} (ID: {course.id})",
                extra={"course_id": course.id, "theme": theme}
            )
        except Exception as e:
            self.logger.exception(
                f"Ошибка сохранения курса в БД для темы '{theme}'",
                extra={
                    "theme": theme,
                    "course_title": course_data.get("title", "N/A"),
                    "error_type": type(e).__name__
                }
            )
            raise

        # Шаг 3: Генерация тегов
        try:
            tags_data = await self._generate_professional_tags_data(theme=theme, course=course, user_id=user_id)
        except Exception as e:
            self.logger.exception(
                f"КРИТИЧЕСКАЯ ОШИБКА: не удалось сгенерировать теги для курса '{course.title}'",
                extra={
                    "course_id": course.id,
                    "theme": theme,
                    "error_type": type(e).__name__
                }
            )
            raise

        # Шаг 4: Привязка тегов
        try:
            await self._create_and_attach_tags(tags_data, course)
            self.logger.info(
                f"Успешно привязано {len(tags_data)} тегов к курсу '{course.title}'",
                extra={"course_id": course.id, "tags_count": len(tags_data)}
            )
        except Exception as e:
            self.logger.exception(
                f"Ошибка привязки тегов к курсу '{course.title}'",
                extra={
                    "course_id": course.id,
                    "tags_count": len(tags_data),
                    "error_type": type(e).__name__
                }
            )
            raise

        # Шаг 5: Баланс уроков
        try:
            await self._create_course_balance(course)
            self.logger.info(
                f"Баланс уроков создан для курса '{course.title}'",
                extra={"course_id": course.id}
            )
        except Exception as e:
            self.logger.exception(
                f"Ошибка создания баланса уроков для курса '{course.title}'",
                extra={"course_id": course.id, "error_type": type(e).__name__}
            )
            raise

        return course

    async def _generate_course_data(self, theme: str, user_id: Optional[int] = None,) -> dict:
        system_prompt = ("Ты опытный и талантливый проектировщик курсов повышения уровня английского языка. "
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
        context = {
            "user_id": user_id,
            "request_type": LLMRequestType.COURSE_GENERATION.value,
        }

        return await self._safe_llm_call(system_prompt=system_prompt, user_message=user_message,
                                         context=context, temperature=0.3, response_format=dict)

    @sync_to_async
    @transaction.atomic
    def _create_course(self, course_data: dict) -> Course:
        return Course.objects.create(
            title=course_data["title"],
            description=course_data["description"],
            is_active=True
        )

    async def _generate_professional_tags_data(self, theme: str, course: Course, user_id: Optional[int] = None,) -> list[str]:
        system_prompt = """
        You are an expert curriculum designer for professional English courses.

        Your task is to generate structured data for Professional Tags
        used to personalize English learning for working professionals.

        A Professional Tag represents:
        - a job role
        - a work context
        - or a recurring professional activity
        that affects language usage.
        """
        user_message = f"""
        Generate 10 professional tags for the following course theme:

        "{theme}"

        Rules for each tag:
        - name:
          - lowercase
          - kebab-case (use hyphens)
          - no spaces
          - max 50 characters
          - unique
          - suitable as a database identifier
        - description:
          - short human-readable explanation
          - describes the professional context or activity
          - max 200 characters

        Do NOT include:
        - student levels
        - language skills (grammar, vocabulary, etc.)
        - abstract soft skills

        Return ONLY valid JSON matching this structure:
        {{
        "tags": [
            {{
                "name": "backend",
                "description": "Backend development tasks and communication"
            }}
          ]
        }}
        """
        context = {
            "user_id": user_id,
            "course_id": course.pk,
            "request_type": LLMRequestType.COURSE_GENERATION.value,
        }
        data = await self._safe_llm_call(
            system_prompt=system_prompt, user_message=user_message, temperature=0.4,
            context=context, response_format=dict
        )

        if "tags" not in data or not isinstance(data["tags"], list):
            raise ValueError(f"Invalid tags format: {data}")

        return data["tags"]

    @sync_to_async
    @transaction.atomic
    def _create_and_attach_tags(self, tags_data: list[dict], course: Course):
        tags = []
        for tag in tags_data:
            name = tag["name"].lower()
            description = tag["description"]
            tag, _ = ProfessionalTag.objects.get_or_create(
                name=name,
                defaults={"description": description}
            )
            tags.append(tag)

        course.professional_tags.set(tags)
        return tags

    @sync_to_async
    @transaction.atomic
    def _create_course_balance(self, course: Course):
        return CourseBalance.objects.create(
            course=course,
            total_lessons=DEFAULT_COURSE_BALANCE["total_lessons"],
            level_distribution=DEFAULT_COURSE_BALANCE["levels"],
            skill_distribution=DEFAULT_COURSE_BALANCE["skills"],
            frozen=True
        )
