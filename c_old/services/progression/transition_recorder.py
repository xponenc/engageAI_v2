import logging
from typing import Optional, List
from django.utils import timezone

from curriculum.models.governance.teacher_override import TeacherOverride
from curriculum.models.assessment.assessment import Assessment
from curriculum.models.progress.lesson_transition import LessonTransition
from curriculum.models.skills.skill_snapshot import SkillSnapshot
from curriculum.models.skills.skill_trajectory import SkillTrajectory
from curriculum.models.student.enrollment import Enrollment
from curriculum.models.content.task import Task
from curriculum.models.content.lesson import Lesson
from curriculum.services.decisions.decision_service import Decision

logger = logging.getLogger(__name__)


class TransitionRecorder:
    """
    TransitionRecorder фиксирует факты принятия решений в двух режимах:

    1. TASK_MODE (record):
       - Фиксирует переходы между заданиями
       - Использует для интерактивного обучения
       - Привязка к конкретному заданию

    2. LESSON_MODE (record_lesson_transition):
       - Фиксирует переходы между уроками
       - Использует для batch-обработки
       - Агрегированные данные по всему уроку

    Архитектурные принципы:
    - Не принимает решения
    - Не изменяет progression
    - Только записывает факты для аудита
    - Обеспечивает воспроизводимость обучения
    """

    def record(
            self,
            enrollment: Enrollment,
            task: Task,
            decision: Decision,
            assessment_result: Assessment,
            skill_update_result: Optional[SkillSnapshot] = None,
    ) -> LessonTransition:
        """
        Записывает переход в TASK_MODE (интерактивный режим).

        Args:
            enrollment: Зачисление студента
            task: Задание, на котором было принято решение
            decision: Принятое решение
            assessment_result: Результат оценки задания
            skill_update_result: Снимок навыков после обновления (опционально)

        Returns:
            LessonTransition: Записанный переход
        """
        return self._record_common(
            enrollment=enrollment,
            from_lesson=enrollment.current_lesson,
            to_lesson=enrollment.current_lesson,  # В task-mode урок не меняется
            task=task,
            decision=decision,
            assessment=assessment_result,
            skill_snapshot=skill_update_result,
            transition_type='TASK_LEVEL'
        )

    def record_lesson_transition(
            self,
            enrollment: Enrollment,
            lesson: Lesson,
            decision: Decision,
            skill_snapshot: SkillSnapshot,
            skill_trajectory: Optional[SkillTrajectory] = None
    ) -> LessonTransition:
        """
        Записывает переход в LESSON_MODE (batch-обработка).

        Args:
            enrollment: Зачисление студента
            lesson: Урок, по которому принималось решение
            decision: Принятое решение
            skill_snapshot: Снимок навыков по всему уроку
            skill_trajectory: Траектория навыков (опционально)

        Returns:
            LessonTransition: Записанный переход
        """
        # Определяем целевой урок на основе решения
        to_lesson = self._get_target_lesson(enrollment, decision, lesson)

        return self._record_common(
            enrollment=enrollment,
            from_lesson=lesson,
            to_lesson=to_lesson,
            task=None,  # В lesson-mode нет привязки к конкретному заданию
            decision=decision,
            assessment=None,  # Нет привязки к конкретной оценке
            skill_snapshot=skill_snapshot,
            skill_trajectory=skill_trajectory,
            transition_type='LESSON_LEVEL'
        )

    def _record_common(
            self,
            enrollment: Enrollment,
            from_lesson: Lesson,
            to_lesson: Lesson,
            task: Optional[Task],
            decision: Decision,
            assessment: Optional[Assessment],
            skill_snapshot: Optional[SkillSnapshot],
            skill_trajectory: Optional[SkillTrajectory] = None,
            transition_type: str = 'TASK_LEVEL'
    ) -> LessonTransition:
        """
        Общая логика записи перехода для обоих режимов.
        """
        # Проверяем teacher override
        teacher_override = self._get_active_teacher_override(enrollment, from_lesson)

        # Создаем переход
        transition = LessonTransition.objects.create(
            enrollment=enrollment,
            from_lesson=from_lesson,
            to_lesson=to_lesson,
            task=task,
            decision_code=decision.code,
            assessment=assessment,
            skill_snapshot=skill_snapshot,
            skill_trajectory=skill_trajectory,
            teacher_override=teacher_override is not None,
            teacher_override_id=teacher_override.pk if teacher_override else None,
            override_reason=teacher_override.reason if teacher_override else None,
            decision_confidence=decision.confidence,
            decision_rationale=decision.rationale,
            transition_type=transition_type,  # Добавляем тип перехода
            transition_at=timezone.now()
        )

        logger.info(
            f"Recorded transition {transition.id} for enrollment {enrollment.pk}: "
            f"{from_lesson.pk} → {to_lesson.pk}, decision: {decision.code}, "
            f"type: {transition_type}"
        )

        return transition

    def _get_target_lesson(
            self,
            enrollment: Enrollment,
            decision: Decision,
            current_lesson: Lesson
    ) -> Lesson:
        """
        Определяет целевой урок на основе принятого решения.
        """
        if decision.code == "ADVANCE_LESSON":
            # Находим следующий урок
            next_lesson = Lesson.objects.filter(
                course=enrollment.course,
                order__gt=current_lesson.order,
                is_active=True
            ).order_by('order').first()

            if next_lesson:
                return next_lesson

        elif decision.code == "COMPLETE_COURSE":
            # Для завершения курса оставляем текущий урок
            return current_lesson

        # Для REPEAT_LESSON и других решений остаемся на текущем уроке
        return current_lesson

    def _get_active_teacher_override(
            self,
            enrollment: Enrollment,
            lesson: Lesson
    ) -> Optional[TeacherOverride]:
        """
        Получает активный teacher override для урока.
        """
        return TeacherOverride.objects.filter(
            student=enrollment.student,
            lesson=lesson,
        ).order_by("-created_at").first()
