import logging
from django.db import transaction
from typing import List, Dict, Any, Optional

from curriculum.models.assessment.assessment import Assessment
from curriculum.models.assessment.student_response import StudentTaskResponse
from curriculum.models.student.enrollment import Enrollment
from curriculum.services.assessment.assessment_service import AssessmentService
from curriculum.services.skills.skill_update_service import SkillUpdateService
from curriculum.services.decisions.decision_service import DecisionService
from curriculum.services.progression.progression_service import ProgressionService
from curriculum.services.progression.transition_recorder import TransitionRecorder
from curriculum.exceptions import AssessmentError, LearningProcessError

logger = logging.getLogger(__name__)


class LessonAssessmentService:
    """
    LessonAssessmentService обрабатывает оценку целых уроков в фоновом режиме.

    Отличия от LearningService:
    1. Работает только в LESSON_MODE (batch-обработка)
    2. Не предназначен для интерактивного использования
    3. Фокусируется на агрегации данных по всему уроку
    4. Обеспечивает отказоустойчивость для долгих операций

    Архитектурные принципы:
    - Единая ответственность: только оценка уроков
    - Изоляция от веб-слоя: не зависит от request/response
    - Атомарность: все операции в одной транзакции
    - Восстановление после сбоев
    """

    def __init__(
            self,
            assessment_service: AssessmentService,
            skill_update_service: SkillUpdateService,
            decision_service: DecisionService,
            progression_service: ProgressionService,
            transition_recorder: TransitionRecorder
    ):
        self.assessment_service = assessment_service
        self.skill_update_service = skill_update_service
        self.decision_service = decision_service
        self.progression_service = progression_service
        self.transition_recorder = transition_recorder

    def assess_lesson(
            self,
            enrollment: Enrollment,
            responses: List[StudentTaskResponse]
    ) -> Dict[str, Any]:
        """
        Оценивает все задания в уроке и принимает решение о дальнейшем продвижении.

        Алгоритм:
        1. Оцениваем все ответы студента
        2. Создаем агрегированный снимок навыков
        3. Принимаем решение о завершении урока
        4. Применяем прогрессию
        5. Записываем переход для аудита

        Args:
            enrollment: Зачисление студента
            responses: Список ответов студента по всем заданиям урока

        Returns:
            Dict[str, Any]: Результат обработки:
                {
                    'decision': str,
                    'transition_id': int,
                    'skill_snapshot_id': int,
                    'assessments_count': int,
                    'next_lesson_id': int,
                    'skill_progress': dict
                }
        """
        try:
            with transaction.atomic():
                # 1. Оцениваем все ответы
                assessments = self._assess_all_responses(responses, enrollment)
                for assessment in assessments:
                    print(f"{assessment.__dict__}")

                if not assessments:
                    raise ValueError(f"No assessments created for enrollment {enrollment.pk}")

                # 2. Создаем снимок навыков по уроку
                skill_snapshot_result = self.skill_update_service.create_lesson_snapshot(
                    enrollment=enrollment,
                    assessments=assessments,
                    lesson_context={
                        'assessment_count': len(assessments),
                        'task_ids': [r.task.id for r in responses],
                        'batch_processed': True
                    }
                )
                print(f"{skill_snapshot_result=}")

                # 3. Принимаем решение о завершении урока
                decision = self.decision_service.decide_lesson_completion(
                    enrollment=enrollment,
                    lesson=enrollment.current_lesson,
                    skill_snapshot_result=skill_snapshot_result
                )
                print(f"{decision=}")

                # 4. Применяем решение к прогрессии
                progression_result = self.progression_service.apply_lesson_decision(
                    enrollment=enrollment,
                    decision=decision
                )
                print(f"{progression_result=}")

                # 5. Записываем переход для аудита
                transition = self.transition_recorder.record_lesson_transition(
                    enrollment=enrollment,
                    lesson=enrollment.current_lesson,
                    decision=decision,
                    skill_snapshot=skill_snapshot_result.snapshot,
                    skill_trajectory=skill_snapshot_result.trajectories[0]
                    if skill_snapshot_result.trajectories else None
                )

                print(f"{transition=}")

                # 6. Обновляем статус зачисления
                enrollment.lesson_status = 'COMPLETED'
                enrollment.save(update_fields=['lesson_status'])

                return {
                    'success': True,
                    'decision': decision.code,
                    'transition_id': transition.id if transition else None,
                    'skill_snapshot_id': skill_snapshot_result.snapshot.pk,
                    'assessments_count': len(assessments),
                    'skill_progress': skill_snapshot_result.skill_progress,
                    'next_lesson_id': progression_result.next_lesson_id if progression_result else None
                }

        except Exception as e:
            logger.error(f"Critical error in assess_lesson: {str(e)}", exc_info=True)
            self._handle_assessment_error(enrollment, str(e))
            raise LearningProcessError(f"Lesson assessment failed: {str(e)}", enrollment_id=enrollment.pk) from e

    def _assess_all_responses(
            self,
            responses: List[StudentTaskResponse],
            enrollment: Enrollment
    ) -> List[Assessment]:
        """
        Оценивает все ответы студента в уроке.
        Продолжает оценку даже при ошибках в отдельных заданиях.
        """
        assessments = []
        error_count = 0

        for response in responses:
            try:
                assessment = self.assessment_service.assess(response)
                assessments.append(assessment)
                logger.debug(f"Created assessment {assessment.pk} for response {response.pk}")
            except AssessmentError as e:
                error_count += 1
                logger.warning(f"Assessment failed for response {response.pk}: {str(e)}")
                # Продолжаем оценку остальных заданий
            except Exception as e:
                error_count += 1
                logger.error(f"Critical assessment error for response {response.pk}: {str(e)}", exc_info=True)

        if error_count == len(responses):
            raise AssessmentError("All assessments failed for this lesson")

        return assessments

    def _handle_assessment_error(self, enrollment: Enrollment, error_message: str):
        """
        Обрабатывает ошибки во время оценки урока.
        Обновляет статус зачисления и логирует ошибку.
        """
        try:
            enrollment.lesson_status = 'ASSESSMENT_ERROR'
            enrollment.save(update_fields=['lesson_status'])

            logger.error(
                f"Assessment error for enrollment {enrollment.pk}: {error_message}",
                extra={
                    'enrollment_id': enrollment.pk,
                    'student_id': enrollment.student.pk,
                    'lesson_id': enrollment.current_lesson.pk,
                    'error_type': 'ASSESSMENT_ERROR'
                }
            )
        except Exception as e:
            logger.critical(f"Failed to handle assessment error: {str(e)}", exc_info=True)