# import logging
#
# from django.utils import timezone
#
# from curriculum.application.ports.assessment_port import AssessmentPort
# from curriculum.infrastructure.adapters.auto_assessment_adapter import AutoAssessorAdapter
# from curriculum.infrastructure.adapters.llm_assessment_adapter import LLMAssessmentAdapter
# from curriculum.infrastructure.repositories.assessment_repository import AssessmentRepository
# from curriculum.models.assessment.assessment import Assessment
# from curriculum.models.assessment.student_response import StudentTaskResponse
# from curriculum.models.content.task import Task
#
# logger = logging.getLogger(__name__)
#
#
# class AssessmentService:
#     """
#     AssessmentService координирует процесс оценки ответа студента.
#
#     Он:
#     - выбирает стратегию оценки
#     - нормализует результат
#     - сохраняет Assessment как факт
#
#     TODO (AssessmentService):
#
#     1. LLM-based assessment
#     2. Hybrid assessment (auto + llm)
#     3. Teacher validation of assessment
#     4. Confidence scoring
#     5. Bias tracking by ProfessionalTag
#     """
#
#     def __init__(
#             self,
#             auto_adapter: AutoAssessorAdapter,
#             llm_adapter: LLMAssessmentAdapter
#     ):
#         self.assessment_port = auto_adapter
#         self.llm_adapter = llm_adapter
#
#     def assess(self, student_response: StudentTaskResponse) -> Assessment:
#         """
#         Полный цикл оценки с нормализацией результатов.
#         """
#         task = student_response.task
#
#         try:
#             assessment_result = self.assessment_port.assess_task(task, student_response)
#             print(f"Assessment service assess{assessment_result=}")
#
#             raw_output = {
#                 "source": assessment_result.source,  # "llm", "rule_based", "hybrid"
#                 "confidence": assessment_result.confidence,
#                 "raw_response": assessment_result.raw_response,  # полный ответ от LLM
#                 "processing_time": assessment_result.processing_time,
#                 "model_version": assessment_result.model_version,
#                 "metadata": assessment_result.metadata,
#                 "timestamp": timezone.now().isoformat()
#             }
#
#             assessment = Assessment.objects.create(
#                 task_response=student_response,
#                 score=assessment_result.score,
#                 is_correct=assessment_result.is_correct,
#                 error_tags=assessment_result.error_tags,
#                 feedback=assessment_result.feedback,
#                 raw_output=raw_output,  # ПОЛНЫЕ СЫРЫЕ ДАННЫЕ
#                 llm_version=assessment_result.model_version or "auto"
#             )
#
#             return assessment
#
#         except Exception as e:
#             logger.error(f"Assessment failed for task {task.pk}, response {student_response.id}: {str(e)}")
#             return self._create_error_assessment(
#                 task=task,
#                 response=student_response,
#                 error=str(e),
#                 exception_type=type(e).__name__
#             )
#
#     def _create_error_assessment(
#             self,
#             task: Task,
#             response: StudentTaskResponse,
#             error: str,
#             exception_type: str = None
#     ) -> Assessment:
#         """
#         Создает Assessment с информацией об ошибке, но НЕ прерывает учебный процесс
#         """
#         logger.error(f"Assessment error for task {task.pk}: {error}")
#
#         # Формируем детальное raw_output для ошибки
#         raw_output = {
#             "error": error,
#             "exception_type": exception_type,
#             "task_id": task.pk,
#             "response_id": response.id,
#             "timestamp": timezone.now().isoformat(),
#             "retry_count": getattr(response, 'retry_count', 0) + 1
#         }
#
#         # Создаем Assessment с пометкой об ошибке
#         assessment = Assessment.objects.create(
#             task_response=response,
#             score=0.5,  # Нейтральное значение вместо 0.0
#             is_correct=None,  # Не определено из-за ошибки
#             error_tags=["processing_error", exception_type.lower() if exception_type else "unknown"],
#             feedback={
#                 "error": f"Ошибка при автоматической оценке: {error}",
#                 "message": "Ваш ответ был сохранен и будет проверен преподавателем вручную.",
#                 "note": "Это не повлияет на ваш прогресс в обучении."
#             },
#             raw_output=raw_output,
#             llm_version="error-handler"
#         )
#
#         # Отправляем уведомление администратору
#         self._notify_admin_about_assessment_error(task, response, error)
#
#         return assessment
#
#     def _notify_admin_about_assessment_error(self, task, response, error):
#         """Отправка уведомления администратору об ошибке"""
#         try:
#             # В реальной системе здесь будет отправка email
#             admin_email = "admin@edu-platform.com"
#             subject = f"Ошибка оценки задания #{task.pk}"
#             message = f"""
#             Произошла ошибка при автоматической оценке ответа студента:
#             - Задание: {task.pk}
#             - Студент: {response.student.id}
#             - Ошибка: {error}
#             - Ответ сохранен в БД: {response.id}
#             """
#             # TODO send_mail(admin_email, subject, message)  # Реальная отправка
#             logger.warning(f"Admin notification sent about error: {error}")
#         except Exception as notify_error:
#             logger.error(f"Failed to notify admin: {str(notify_error)}")

import logging
from django.utils import timezone
from curriculum.application.ports.assessment_port import AssessmentPort
from curriculum.infrastructure.adapters.auto_assessment_adapter import AutoAssessorAdapter
from curriculum.infrastructure.adapters.llm_assessment_adapter import LLMAssessmentAdapter
from curriculum.models.assessment.assessment import Assessment
from curriculum.models.assessment.student_response import StudentTaskResponse
from curriculum.models.content.task import Task, ResponseFormat

logger = logging.getLogger(__name__)


class AssessmentService:
    """
    AssessmentService координирует процесс оценки ответа студента.
    """

    def __init__(self, auto_adapter: AutoAssessorAdapter, llm_adapter: LLMAssessmentAdapter):
        self.auto_adapter = auto_adapter
        self.llm_adapter = llm_adapter

    def assess(self, student_response: StudentTaskResponse) -> Assessment:
        print(f"ОБРАБОТКА ОТВЕТА 7. AssessmentService # создание assessment\n\n", )
        task = student_response.task

        try:
            # Выбор адаптера в зависимости от формата задания
            adapter = self._select_adapter(task)
            print(f"ОБРАБОТКА ОТВЕТА 7. AssessmentService # выбран адаптер оценки:\n{adapter}\n\n", )
            assessment_result = adapter.assess_task(task, student_response)

            assessment_data = assessment_result.metadata
            llm_version = assessment_data.get("llm_version", "-")

            # Правильное формирование structured_feedback
            # structured_feedback = self._build_structured_feedback(assessment_result, task) # TODO отложено на потом

            assessment = Assessment.objects.create(
                task_response=student_response,
                llm_version=llm_version,
                raw_output=assessment_data,
                structured_feedback=assessment_data,
            )
            print(f"ОБРАБОТКА ОТВЕТА 7. AssessmentService # создан Assessment:\n{assessment}\n\n", )

            return assessment

        except Exception as e:
            logger.error(f"Assessment failed for task {task.pk}: {str(e)}", exc_info=True)
            return self._create_error_assessment(
                task=task,
                response=student_response,
                error=str(e),
                exception_type=type(e).__name__
            )

    def _select_adapter(self, task: Task) -> AssessmentPort:
        if task.response_format in [
            ResponseFormat.SINGLE_CHOICE,
            ResponseFormat.MULTIPLE_CHOICE,
            ResponseFormat.SHORT_TEXT
        ]:
            return self.auto_adapter
        return self.llm_adapter

    def _build_structured_feedback(self, assessment_result, task: Task) -> dict:
        # Создаем базовую структуру с правильными полями
        structured = {
            "score_grammar": 0.5,
            "score_vocabulary": 0.5,
            "errors": [],
            "strengths": [],
            "suggestions": [],
            "metadata": {
                # "overall_score": assessment_result.score,
                # "confidence": assessment_result.confidence,
                # "is_correct": assessment_result.is_correct
            }
        }

        # Обновляем поля в зависимости от типа задания
        # if task.task_type == "grammar":
        #     structured["score_grammar"] = assessment_result.score
        # elif task.task_type == "vocabulary":
        #     structured["score_vocabulary"] = assessment_result.score

        # Добавляем ошибки если они есть #TODO смотреть отдельно потом ошибки
        # if assessment_result.error_tags:
        #     for tag in assessment_result.error_tags:
        #         structured["errors"].append({
        #             "type": tag,
        #             "example": "",
        #             "correction": ""
        #         })

        # Добавляем фидбек если он есть
        if assessment_result.structured_feedback:
            if "strengths" in assessment_result.structured_feedback:
                structured["strengths"] = assessment_result.structured_feedback["strengths"]
            if "suggestions" in assessment_result.structured_feedback:
                structured["suggestions"] = assessment_result.structured_feedback["suggestions"]

        return structured

    def _create_error_assessment(self, task: Task, response: StudentTaskResponse, error: str,
                                 exception_type: str = None) -> Assessment:
        # Создаем structured_feedback в правильном формате
        structured_feedback = {
            "score_grammar": 0.5,
            "score_vocabulary": 0.5,
            "errors": [{
                "type": "processing_error",
                "example": error,
                "correction": "Будет проверено преподавателем"
            }],
            "strengths": [],
            "suggestions": ["Ваш ответ был сохранен и будет проверен вручную"],
            "metadata": {
                "overall_score": 0.5,
                "confidence": 0.3,
                "is_correct": None,
                "error_type": exception_type or "unknown"
            }
        }

        assessment, created = Assessment.objects.get_or_create(
            task_response=response,
            defaults={
                "llm_version": "error-handler",
                "raw_output": {
                    "error": error,
                    "exception_type": exception_type,
                    "task_id": task.pk,
                    "response_id": response.pk,
                    "timestamp": timezone.now().isoformat()
                },
                "structured_feedback": structured_feedback,
            }
        )

        # Отправляем уведомление администратору (асинхронно в продакшене)
        self._notify_admin_about_assessment_error(task, response, error)

        return assessment

    def _notify_admin_about_assessment_error(self, task, response, error):
        """Отправка уведомления администратору об ошибке"""
        try:
            # В реальной системе здесь будет отправка email/уведомления
            logger.warning(
                f"Admin notification about assessment error - "
                f"task: {task.pk}, student: {response.student.id}, error: {error}"
            )
        except Exception as notify_error:
            logger.error(f"Failed to notify admin: {str(notify_error)}")