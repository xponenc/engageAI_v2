import logging
from typing import Any, Dict

from django.db.models import OuterRef, Exists
from django.utils import timezone

from curriculum.exceptions import InvalidResponseError, InvalidTaskError, LearningProcessError, AssessmentError
from curriculum.infrastructure.adapters.auto_assessment_adapter import AutoAssessorAdapter
from curriculum.infrastructure.adapters.llm_assessment_adapter import LLMAssessmentAdapter
from curriculum.models import LessonTransition
from curriculum.models.assessment.assessment import Assessment
from curriculum.models.progress.lesson_transition import LessonTransition
from curriculum.models.skills.skill_snapshot import SkillSnapshot
from curriculum.models.student.enrollment import Enrollment
from curriculum.models.content.task import Task, ResponseFormat
from curriculum.models.assessment.student_response import StudentTaskResponse
from curriculum.services.assessment.assessment_service import AssessmentService

from curriculum.services.curriculum_query import CurriculumQueryService
from curriculum.services.decisions.decision_service import DecisionService, Decision
from curriculum.services.enrollment_service import EnrollmentService
from curriculum.services.progression.progression_service import ProgressionService, ProgressionResult
from curriculum.services.progression.transition_recorder import TransitionRecorder
from curriculum.services.skills.skill_update_service import SkillUpdateService, SkillUpdateResult

logger = logging.getLogger(__name__)


class LearningService:
    """
    LearningService — stateless координатор одного шага обучения.

    Он НЕ:
    - хранит состояние
    - принимает бизнес-решения
    - знает про UI / LLM / Orchestrator

    Он:
    - извлекает текущее состояние обучения
    - координирует оценку, обновление навыков и прогресса
    - возвращает структурированный результат шага
    """

    def __init__(
            self,
            curriculum_query: CurriculumQueryService | None = None,
            assessment_service: AssessmentService | None = None,
            skill_update_service: SkillUpdateService | None = None,
            decision_service: DecisionService | None = None,
            progression_service: ProgressionService | None = None,
            transition_recorder: TransitionRecorder | None = None,
            enrollment_service: EnrollmentService | None = None,
    ):
        """
        Все зависимости внедряются явно.

        Это позволяет:
        - тестировать сервис изолированно
        - подменять реализации (auto → llm)
        - не привязываться к DI-фреймворку
        """

        self.curriculum_query = curriculum_query or CurriculumQueryService()
        self.assessment_service = assessment_service or AssessmentService(
            llm_adapter=LLMAssessmentAdapter(),
            auto_adapter=AutoAssessorAdapter(),
        )
        self.skill_update_service = skill_update_service or SkillUpdateService()
        self.decision_service = decision_service or DecisionService()
        self.progression_service = progression_service or ProgressionService()
        self.transition_recorder = transition_recorder or TransitionRecorder()
        self.enrollment_service = enrollment_service or EnrollmentService(
            curriculum_query=self.curriculum_query
        )

    # ---------------------------------------------------------------------
    # READ API
    # ---------------------------------------------------------------------

    def get_current_state(self, enrollment_id: int) -> Dict[str, Any]:
        """
        Возвращает текущее состояние обучения для Orchestrator / UI.

        Используется для:
        - восстановления сессии
        - отображения прогресса

        Пример входа / выхода
        {
          "enrollment_id": 42,
          "task_id": 101,
          "response": {
            "text": "I has finished my work"
          }
        }
        ==>
        {
          "decision": "REPEAT",
          "next_action": "RETRY_TASK",
          "next_task_id": 101,
          "feedback": {
            "error_type": "grammar",
            "hint": "Check verb agreement"
          }
        }

        TODO (LearningService):
        - учитывать TeacherOverride перед DecisionService
        - расширить get_current_state для explainability
        - добавить support multi-task lessons
        """

        enrollment = Enrollment.objects.select_related(
            "student",
            "course",
            "current_lesson"
        ).get(id=enrollment_id)

        # Получаем последний SkillSnapshot для студента
        latest_snapshot = SkillSnapshot.objects.filter(
            student=enrollment.student
        ).order_by('-snapshot_at').first()

        # Формируем данные урока с нужными полями
        lesson_data = None
        if enrollment.current_lesson:
            lesson_data = {
                "id": enrollment.current_lesson.id,
                "order": enrollment.current_lesson.order,
                "title": enrollment.current_lesson.title,
                "total_tasks": enrollment.current_lesson.tasks.count()
            }

        # Формируем данные задачи
        task_data = None
        student_responses = StudentTaskResponse.objects.filter(
            student=enrollment.student,
            task=OuterRef('pk'),
        )

        current_task = (
            Task.objects
            .filter(
                lesson=enrollment.current_lesson,
                is_active=True,
            )
            .annotate(
                has_response=Exists(student_responses)
            )
            .filter(has_response=False)
            .order_by('order')
            .first()
        )
        print(f"{current_task=}")
        if current_task:
            task_data = {
                "id": current_task.id,
                "type": current_task.task_type,
                # "position": enrollment.current_task.position
            }

        skills_data = latest_snapshot.to_dict() if latest_snapshot else {
            "grammar": 0.0,
            "vocabulary": 0.0,
            "listening": 0.0,
            "reading": 0.0,
            "writing": 0.0,
            "speaking": 0.0
        }

        return {
            "enrollment_id": enrollment.id,
            "course": {
                "id": enrollment.course.id,
                "title": enrollment.course.title,
            },
            "current_lesson": lesson_data,
            "current_task": task_data,
            "skills": skills_data,
            # "progress": {
            #     "lesson_progress": enrollment.lesson_progress,
            #     "course_completion": enrollment.course_completion
            # }
        }
    #
    # def get_next_task(self, enrollment_id: int) -> Task:
    #     """
    #     Возвращает следующее задание, которое студент должен выполнить.
    #
    #     Важно:
    #     - НЕ принимает решений
    #     - только читает текущее состояние
    #     """
    #
    #     enrollment = Enrollment.objects.get(id=enrollment_id)
    #
    #     return self.curriculum_query.get_next_task(enrollment)

    # ---------------------------------------------------------------------
    # WRITE API (основной flow)
    # ---------------------------------------------------------------------

    def submit_task_response(
            self,
            enrollment_id: int,
            task_id: int,
            response_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Основной метод учебного шага с полной функциональностью.

        Алгоритм:
        1. Валидация входных данных
        2. Фиксация ответа студента (event)
        3. Запуск assessment с обработкой ошибок
        4. Обновление skills с логированием изменений
        5. Принятие решения с учетом контекста
        6. Обновление progression с защитой от некорректных состояний
        7. Запись transition для аудита и объяснимости
        8. Возврат структурированного результата с метаданными

        Args:
            enrollment_id: ID зачисления студента
            task_id: ID задания
            response_payload: Ответ студента:
                - Для текста: {"text": "ответ студента"}
                - Для аудио: {"audio_file": file_object}

        Returns:
            Dict[str, Any]: Результат обработки:
                {
                    "decision": "ADVANCE_TASK",
                    "next_action": "NEXT_TASK",
                    "next_task_id": 102,
                    "feedback": {...},
                    "assessment": Assessment,
                    "transition": LessonTransition
                }

        Raises:
            LearningProcessError: При ошибках в учебном процессе
            AssessmentError: При ошибках оценки
            SkillUpdateError: При ошибках обновления навыков
        """

        print(f"{enrollment_id=}")
        print(f"{task_id=}")
        print(f"{response_payload=}")
        try:
            # 1. Валидация и получение данных
            enrollment = self._get_enrollment_with_prefetch(enrollment_id)
            task = self._get_task_with_validation(task_id, enrollment)

            # 2. Фиксируем ответ студента (event)
            student_response = self._create_student_response(
                enrollment=enrollment,
                task=task,
                response_payload=response_payload
            )

            # 3. Assessment с детальным логированием
            assessment_result = self._perform_assessment(
                student_response=student_response,
                task=task
            )

            # 4. Update skills & error logs
            skill_updates = self._update_skills(
                enrollment=enrollment,
                task=task,
                assessment_result=assessment_result
            )

            # 5. Decision с учетом всех факторов
            decision = self._make_decision(
                enrollment=enrollment,
                skill_update_result=skill_updates
            )

            # 6. Apply progression
            progression_result = self._apply_progression(
                enrollment=enrollment,
                decision=decision
            )

            # 7. Record transition (audit & explainability)
            transition = self._record_transition(
                enrollment=enrollment,
                task=task,
                decision=decision,
                assessment_result=assessment_result,
                skill_update_result=skill_updates
            )

            # 8. Обновление времени последней активности
            self._update_last_activity(enrollment)

            # 9. Возвращаем полный результат
            return {
                "decision": decision.code,
                "next_action": progression_result.next_action,
                "next_task_id": progression_result.next_task_id,
                "feedback": assessment_result.structured_feedback if hasattr(
                    assessment_result, 'structured_feedback') else "",
                "assessment_id": assessment_result.id if hasattr(assessment_result, 'id') else None,
                "transition_id": transition.id if transition and hasattr(transition, 'id') else None,
                "skill_updates": skill_updates
            }

        except Exception as e:
            logger.error(
                f"Error in LearningService.submit_task_response: {str(e)}",
                extra={
                    "enrollment_id": enrollment_id,
                    "task_id": task_id,
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            raise LearningProcessError(f"Failed to process task response: {str(e)}",
                                       enrollment_id=enrollment_id) from e

    def get_course_history(self, enrollment_id: int) -> dict:
        """
        Возвращает историю пройденных уроков в курсе.

        Args:
            enrollment_id: ID зачисления

        Returns:
            dict: {
                'course': Course,
                'completed_lessons': list,  # Список пройденных уроков
                'enrollment': Enrollment,
                'overall_progress': float
            }
        """
        enrollment = Enrollment.objects.get(id=enrollment_id, is_active=True)
        completed_lessons = self.curriculum_query.get_completed_lessons(enrollment)
        overall_progress = self.enrollment_service.get_course_progress(enrollment)

        return {
            'course': enrollment.course,
            'completed_lessons': completed_lessons,
            'enrollment': enrollment,
            'overall_progress': overall_progress
        }

    def _get_enrollment_with_prefetch(self, enrollment_id: int) -> Enrollment:
        """Получение зачисления с предзагрузкой связанных данных"""
        return Enrollment.objects.select_related(
            "student",
            "course",
            "current_lesson",
            "current_lesson__course"
        ).prefetch_related(
            "current_lesson__tasks",
            "current_lesson__learning_objectives",
            "student__skill_profile"
        ).get(id=enrollment_id, is_active=True)

    def _get_task_with_validation(self, task_id: int, enrollment: Enrollment) -> Task:
        """Получение и валидация задания"""
        task = Task.objects.select_related(
            "lesson",
            "lesson__course"
        ).prefetch_related(
            "professional_tags",
            "media_files"
        ).get(id=task_id)

        # Проверка принадлежности задания к текущему уроку
        if task.lesson != enrollment.current_lesson:
            raise InvalidTaskError(
                f"Task {task_id} does not belong to current lesson {enrollment.current_lesson.pk}"
            )

        return task

    def _create_student_response(
            self,
            enrollment: Enrollment,
            task: Task,
            response_payload: Dict[str, Any]
    ) -> StudentTaskResponse:
        """Создание ответа студента с валидацией"""
        if task.response_format == ResponseFormat.AUDIO:
            if 'audio_file' not in response_payload:
                raise InvalidResponseError(
                    "Audio response requires 'audio_file' field", task_type=task.task_type)

            # Валидация файла
            audio_file = response_payload['audio_file']
            if not hasattr(audio_file, 'content_type') or audio_file.content_type not in ['audio/mpeg', 'audio/wav',
                                                                                          'audio/ogg']:
                raise InvalidResponseError("Invalid audio file format", task_type=task.task_type)

            # # Ограничение размера файла
            # if hasattr(audio_file, 'size') and audio_file.size > settings.MAX_AUDIO_FILE_SIZE:
            #     raise InvalidResponseError(
            #         f"Audio file exceeds maximum size of {settings.MAX_AUDIO_FILE_SIZE // 1024 // 1024}MB")

            return StudentTaskResponse.objects.create(
                student=enrollment.student,
                task=task,
                audio_file=audio_file
            )

        # Для текстовых ответов
        text_response = response_payload.get('text', '').strip()
        if not text_response:
            raise InvalidResponseError("Text response cannot be empty", task_type=task.task_type)

        # Ограничение длины для разных форматов
        # if task.response_format == ResponseFormat.FREE_TEXT:
        #     if len(text_response) > settings.MAX_FREE_TEXT_LENGTH:
        #         raise InvalidResponseError(
        #             f"Text response exceeds maximum length of {settings.MAX_FREE_TEXT_LENGTH} characters")
        # elif task.response_format == ResponseFormat.SHORT_TEXT:
        #     if len(text_response) > settings.MAX_SHORT_TEXT_LENGTH:
        #         raise InvalidResponseError(
        #             f"Text response exceeds maximum length of {settings.MAX_SHORT_TEXT_LENGTH} characters")

        return StudentTaskResponse.objects.create(
            student=enrollment.student,
            task=task,
            response_text=text_response
        )

    def _perform_assessment(
            self,
            student_response: StudentTaskResponse,
            task: Task
    ) -> Assessment:
        """Выполнение оценки с обработкой ошибок"""
        try:
            assessment = self.assessment_service.assess(
                student_response=student_response
            )

            return assessment
        except AssessmentError as e:
            logger.warning(f"Assessment failed, using fallback: {str(e)}")
            # Создаем fallback assessment
            return self._create_fallback_assessment(student_response, task, str(e))
        except Exception as e:
            logger.error(f"Critical assessment error: {str(e)}")
            raise AssessmentError(f"Critical assessment error: {str(e)}") from e

    def _create_fallback_assessment(
            self,
            student_response: StudentTaskResponse,
            task: Task,
            error: str
    ) -> Assessment:
        """Создание fallback assessment при ошибках"""
        return Assessment.objects.create(
            task_response=student_response,
            score=0.5,  # Нейтральная оценка
            is_correct=None,
            error_tags=["assessment_failed", "fallback_used"],
            feedback={
                "message": "Произошла временная ошибка при оценке. Ваш ответ будет проверен дополнительно.",
                "error": error
            },
            raw_output={
                "error": error,
                "fallback": True,
                "timestamp": timezone.now().isoformat()
            },
            llm_version="fallback"
        )

    def _update_skills(
            self,
            enrollment: Enrollment,
            task: Task,
            assessment_result: Assessment
    ) -> SkillUpdateResult:
        """Обновление навыков с логированием"""
        try:
            return self.skill_update_service.update(
                enrollment=enrollment,
                task=task,
                assessment_result=assessment_result,
            )
        except Exception as e:
            logger.error(f"Skill update failed: {str(e)}")
            # Не прерываем процесс обучения при ошибках обновления навыков
            return SkillUpdateResult(
                updated_skills={},
                deltas={},
                snapshot=None,
                error_events=[str(e)]
            )

    def _make_decision(
            self,
            enrollment: Enrollment,
            skill_update_result: SkillUpdateResult
    ) -> Decision:
        """Принятие решения с учетом всех факторов"""
        try:
            return self.decision_service.decide(
                enrollment=enrollment,
                lesson=enrollment.current_lesson,
                skill_profile_update=skill_update_result,
            )
        except Exception as e:
            logger.error(f"Decision making failed: {str(e)}")
            # Fallback решение - продолжать обучение
            return Decision(
                code="ADVANCE_TASK",
                confidence=0.5,
                rationale={
                    "reason": "fallback_decision",
                    "error": str(e)
                }
            )

    def _apply_progression(
            self,
            enrollment: Enrollment,
            decision: Decision
    ) -> ProgressionResult:
        """Применение решения к прогрессу"""
        try:
            return self.progression_service.apply_decision(
                enrollment=enrollment,
                decision=decision,
            )
        except Exception as e:
            logger.error(f"Progression update failed: {str(e)}")
            # Fallback - оставляем текущее состояние

            current_task = self.curriculum_query

            return ProgressionResult(
                next_action="RETRY_TASK",
                next_task_id=current_task.pk if current_task else None
            )

    def _record_transition(
            self,
            enrollment: Enrollment,
            task: Task,
            decision: Decision,
            assessment_result: Assessment,
            skill_update_result: SkillUpdateResult
    ) -> LessonTransition | None:
        """Запись перехода для аудита и объяснимости"""
        try:
            return self.transition_recorder.record(
                enrollment=enrollment,
                task=task,
                decision=decision,
                assessment_result=assessment_result,
                skill_update_result=skill_update_result.snapshot
            )
        except Exception as e:
            logger.warning(f"Failed to record transition: {str(e)}")
            return None

    def _update_last_activity(self, enrollment: Enrollment):
        """Обновление времени последней активности"""
        try:
            enrollment.last_activity = timezone.now()
            enrollment.save(update_fields=["last_activity"])
        except Exception as e:
            logger.warning(f"Failed to update last activity: {str(e)}")
