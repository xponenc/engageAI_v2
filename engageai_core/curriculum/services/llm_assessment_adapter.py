import asyncio
import json
import logging
from typing import Type, TypeVar, Optional, Dict, Any, Union

from asgiref.sync import async_to_sync

from ai.llm_service.factory import llm_factory
from assessment.models import TestAnswer
from curriculum.models.assessment.assessment_result import AssessmentResult
from curriculum.models.content.task import Task, ResponseFormat
from curriculum.models.student.student_response import StudentTaskResponse
from curriculum.services.base_assessment_adapter import AssessmentPort
from curriculum.validation.task_schemas import TASK_CONTENT_SCHEMAS
from curriculum.validators import SkillDomain
from llm_logger.models import LLMRequestType

T = TypeVar("T")

SYSTEM_PROMPT = """
Вы — эксперт по оценке английского языка по шкале CEFR. Оцените ответ студента **только по навыкам,
проверяемым заданием**. Используйте шкалу 0.0–1.0. Если навык не проверялся — укажите null.

Верните ТОЛЬКО валидный JSON по схеме:
{
  "is_correct": True|False правильный или неправильный ответ
  "skill_evaluation": {
    "grammar": {"score": число|null, "confidence": число|null, "evidence": []},
    "vocabulary": {"score": число|null, "confidence": число|null, "evidence": []},
    "reading": {"score": число|null, "confidence": число|null, "evidence": []},
    "listening": {"score": число|null, "confidence": число|null, "evidence": []},
    "writing": {"score": число|null, "confidence": число|null, "evidence": []},
    "speaking": {"score": число|null, "confidence": число|null, "evidence": []}
  },
  "summary": {
    "text": "1–3 предложения, роль наставника с объяснениями",
    "advice": ["практический совет", "..."]
  }
}
Никаких пояснений вне JSON. Только JSON.
"""


class LLMAssessmentAdapter(AssessmentPort):
    """
    Адаптер для оценки с использованием LLM через llm_factory
    """

    def __init__(self):
        # Используем глобальный экземпляр llm_factory
        self.llm = llm_factory

    def assess_task(self, task: Task, response: Union[StudentTaskResponse, TestAnswer]) -> AssessmentResult:
        """Assess a single task with LLM"""
        try:
            user_message = self._build_user_message(task, response)
            if isinstance(response, StudentTaskResponse):
                lesson = task.lesson
                course = lesson.course
                user = response.student.user
                context = {
                    "course_id": course.pk,
                    "lesson_id": lesson.pk,
                    "task_id": task.pk,
                    "user_id": user.id,
                    "request_type": LLMRequestType.TASK_REVIEW,
                }
            else:  # TestAnswer
                user = response.question.session.user
                test_session = response.question.session
                task = response.question.task
                context = {
                    "test_session_id": test_session.pk,
                    "task_id": task.pk,
                    "user_id": user.id,
                    "request_type": LLMRequestType.TEST_TASK_REVIEW,
                }

            print(user_message)

            result = self._safe_llm_call(
                system_prompt=SYSTEM_PROMPT,
                user_message=user_message,
                temperature=0.2,
                context=context,
                response_format=dict
            )

            print(f"\n{result=}\n")

            return self._parse_llm_response(payload=result, task=task)
        except Exception as exc:
            self.logger.error(f"LLM assessment failed: {exc}")
            return AssessmentResult(
                is_correct=False,
                task_id=task.pk,
                cefr_target=task.difficulty_cefr,
                skill_evaluation={
                    skill: {"score": 0.5, "confidence": 0.5, "evidence": []}
                    for skill in ["grammar", "vocabulary", "reading", "listening", "writing", "speaking"]
                },
                summary={"text": "No valid assessment could be generated.", "advice": []},
                metadata={"error": "invalid_llm_response", }
            )

    def _build_user_message(self, task: Task, response: StudentTaskResponse) -> str:
        lesson = task.lesson

        task_schema_info = self._get_task_schema_info(task.content_schema_version)
        if task_schema_info:
            task_schema_info = "Дополнительная информация по заданию:\n" + task_schema_info

        # Определяем текст ответа
        student_response = response.response_text
        if task.response_format == ResponseFormat.AUDIO:
            student_response = getattr(response, "transcript", None)

        # Обработка отсутствующего/некорректного ответа
        if not student_response or not student_response.strip():
            student_response = "[No valid student response provided]"

        prompt = f"""
Оцените ответ ученика
        
Урок:
Lesson title: {lesson.title}
Lesson description: {lesson.description}
Lesson CEFR level: {lesson.required_cefr}

Оцениваемое задание:
CEFR level: {task.difficulty_cefr}
Content: {task.content}

{task_schema_info}

Ответ студента:
{student_response}
        """
        return prompt

    def _get_task_schema_info(self, schema_name: str) -> str:
        """
        Возвращает данные о схеме задачи из TASK_CONTENT_SCHEMAS
        """
        task_schema = TASK_CONTENT_SCHEMAS.get(schema_name, {})
        parts: list[str] = []

        skills = task_schema.get("supported_skills")
        if skills:
            parts.append(f"Assessed skills: {', '.join(skills)}")

        response_format = task_schema.get("response_format")
        if response_format:
            parts.append(f"Expected response format: {response_format}")

        description = task_schema.get("description")
        if description:
            parts.append(f"Task goal for the learner: {description}")

        return "\n".join(parts)

    def _safe_llm_call(self,
                       system_prompt: str,
                       user_message: str,
                       response_format: Type[T],
                       temperature: Optional[float] = None,
                       context: Optional[dict] = None) -> T:
        """
        Безопасный вызов LLM с обработкой ошибок и логированием.
        """
        try:
            result = async_to_sync(self.llm.generate_json_response)(
                system_prompt=system_prompt,
                user_message=user_message,
                temperature=temperature,
                context=context
            )

            if result.error:
                self.logger.error(f"LLM error: {result.error}", extra={"raw_response": result.raw_provider_response})
                raise ValueError(f"LLM generation failed: {result.error}")

            data = result.response.message
            if not isinstance(data, response_format):
                raise ValueError(f"Invalid LLM response format: expected {response_format}, got {type(data).__name__}")

            return data

        except Exception as e:
            self.logger.exception("Critical error during LLM call",
                                  extra={"system_prompt": system_prompt[:100], "user_message": user_message[:100],
                                         "context": context})
            raise

    def _parse_llm_response(self, payload: dict, task: Task) -> AssessmentResult:
        """
        Конвертация ответа LLM в валидный AssessmentResult
        """

        # Проверка наличия ключевых полей
        if "skill_evaluation" not in payload or "summary" not in payload or "is_correct" not in payload:
            self.logger.warning(
                f"Invalid LLM response format for task_id {task.pk}: missing 'skill_evaluation' or 'summary' "
                f"or 'is_correct': {payload}",
            )
            # Возвращаем нейтральный AssessmentResult
            return AssessmentResult(
                is_correct=False,
                task_id=task.pk,
                cefr_target=task.difficulty_cefr,
                skill_evaluation={
                    skill: {"score": 0.5, "confidence": 0.5, "evidence": []}
                    for skill in ["grammar", "vocabulary", "reading", "listening", "writing", "speaking"]
                },
                summary={"text": "No valid assessment could be generated.", "advice": []},
                metadata={"error": "invalid_llm_response", "raw_llm": payload}
            )

        # Валидация и создание AssessmentResult
        return AssessmentResult(
            is_correct=payload.get("is_correct"),
            task_id=task.pk,
            cefr_target=task.difficulty_cefr,
            skill_evaluation=self.normalize_skill_evaluation(payload.get("skill_evaluation")),
            summary=payload["summary"],
            metadata={"raw_llm": payload}  # сохраняем весь ответ для аудита
        )

    @staticmethod
    def normalize_skill_evaluation(
            raw: Dict[str, Any] | None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Приводит LLM-ответ к полной и валидной структуре skill_evaluation.
        Гарантирует наличие всех SkillDomain.
        """
        raw = raw or {}
        normalized: Dict[str, Dict[str, Any]] = {}

        for skill in SkillDomain.values:
            value = raw.get(skill)

            if not isinstance(value, dict):
                normalized[skill] = {
                    "score": None,
                    "confidence": None,
                    "evidence": [],
                }
            else:
                normalized[skill] = {
                    "score": value.get("score"),
                    "confidence": value.get("confidence"),
                    "evidence": value.get("evidence") or [],
                }

        return normalized

    # MEDIA CONTEXT

    def _get_media_context(self, task: Task) -> list[dict]:
        if not hasattr(task, "media_files"):
            return []

        context = []
        for media in task.media_files.all():
            context.append(
                {
                    "type": media.media_type,
                    "url": getattr(media.file, "url", None),
                }
            )
        return context
