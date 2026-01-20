# curriculum/services/progression/progression_service.py
import logging
from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.utils import timezone

from curriculum.models.student.enrollment import Enrollment
from curriculum.models.content.lesson import Lesson
from curriculum.services.curriculum_query import CurriculumQueryService
from curriculum.services.decisions.decision_service import Decision

logger = logging.getLogger(__name__)


@dataclass
class ProgressionResult:
    """
    Результат применения решения к Enrollment в LESSON_MODE.

    Поля:
    - next_action: Тип следующего действия
    - next_lesson_id: ID следующего урока (опционально)
    - restart_required: Требуется ли повторное прохождение урока
    """
    next_action: str
    next_lesson_id: Optional[int] = None
    restart_required: bool = False
    message: str = ""


class ProgressionService:
    """
    ProgressionService применяет решения для продвижения обучения
    в режиме LESSON_MODE (batch-обработка уроков).

    Отличия от task-level режима:
    1. Работает с уроками, а не отдельными заданиями
    2. Не управляет состоянием заданий
    3. Фокусируется на переходах между уроками
    4. Поддерживает адаптивные сценарии повторения

    Архитектурные принципы:
    - Инвариант: один вызов = один урок
    - Атомарность: все изменения в одной транзакции
    - Идемпотентность: повторный вызов дает тот же результат
    """

    def __init__(
            self,
            curriculum_query: CurriculumQueryService | None = None,
    ):
        self.curriculum_query = curriculum_query or CurriculumQueryService()

    def apply_lesson_decision(
            self,
            enrollment: Enrollment,
            decision: Decision,
    ) -> ProgressionResult:
        """
        Применяет решение к состоянию зачисления на уровне урока.

        Поддерживаемые решения:
        - ADVANCE_LESSON: Переход к следующему уроку
        - COMPLETE_COURSE: Завершение курса
        - REPEAT_LESSON: Повтор текущего урока
        - ADAPTIVE_REPEAT_LESSON: Адаптивное повторение с фокусом на слабых навыках

        Args:
            enrollment: Зачисление студента
            decision: Принятое решение

        Returns:
            ProgressionResult: Результат применения решения
        """
        try:
            with transaction.atomic():
                if decision.code == "ADVANCE_LESSON":
                    return self._advance_to_next_lesson(enrollment)
                elif decision.code == "COMPLETE_COURSE":
                    return self._complete_course(enrollment)
                elif decision.code == "REPEAT_LESSON":
                    return self._repeat_lesson(enrollment)
                elif decision.code == "ADAPTIVE_REPEAT_LESSON":
                    return self._adaptive_repeat_lesson(enrollment, decision.rationale)
                else:
                    logger.warning(f"Unknown decision code: {decision.code}. Using default behavior.")
                    return self._default_fallback(enrollment, decision)
        except Exception as e:
            logger.error(f"Error applying lesson decision: {str(e)}", exc_info=True)
            return self._error_fallback(enrollment, str(e))

    # ------------------------------------------------------------------
    # Lesson-level decision handlers
    # ------------------------------------------------------------------

    def _advance_to_next_lesson(self, enrollment: Enrollment) -> ProgressionResult:
        """
        Переход к следующему уроку в курсе.

        Алгоритм:
        1. Находим следующий активный урок
        2. Обновляем current_lesson
        3. Возвращаем результат с ID следующего урока
        """
        current_lesson = enrollment.current_lesson

        next_lesson = (
            Lesson.objects.filter(
                course=enrollment.course,
                order__gt=current_lesson.order,
                is_active=True
            ).order_by('order').first()
        )

        if not next_lesson:
            logger.error(f"No next lesson found for enrollment {enrollment.pk}, current lesson {current_lesson.id}")
            raise ValueError("Next lesson not found in course")

        enrollment.current_lesson = next_lesson
        enrollment.save(update_fields=['current_lesson'])

        logger.info(f"Advanced to next lesson {next_lesson.id} for enrollment {enrollment.pk}")

        return ProgressionResult(
            next_action="ADVANCE_LESSON",
            next_lesson_id=next_lesson.id,
            message=f"Переход к уроку {next_lesson.order}: {next_lesson.title}"
        )

    def _complete_course(self, enrollment: Enrollment) -> ProgressionResult:
        """
        Завершение курса.

        Алгоритм:
        1. Помечаем зачисление как неактивное
        2. Устанавливаем время завершения
        3. Возвращаем результат с флагом завершения
        """
        enrollment.is_active = False
        enrollment.completed_at = timezone.now()
        enrollment.save(update_fields=['is_active', 'completed_at'])

        logger.info(f"Course completed for enrollment {enrollment.pk}")

        return ProgressionResult(
            next_action="COMPLETE_COURSE",
            message="Курс успешно завершен!"
        )

    def _repeat_lesson(self, enrollment: Enrollment) -> ProgressionResult:
        """
        Повтор текущего урока.

        Важно: В batch-режиме мы не сбрасываем ответы студента,
        так как это нарушит аудит и историю обучения.
        Вместо этого система предложит студенту пройти урок снова,
        но сохранит предыдущие результаты для аналитики.
        """
        logger.info(f"Repeating lesson {enrollment.current_lesson.id} for enrollment {enrollment.pk}")

        return ProgressionResult(
            next_action="REPEAT_LESSON",
            restart_required=True,
            message="Урок будет предложен для повторного прохождения"
        )

    def _adaptive_repeat_lesson(
            self,
            enrollment: Enrollment,
            rationale: dict
    ) -> ProgressionResult:
        """
        Адаптивное повторение урока с фокусом на слабых навыках.

        Алгоритм:
        1. Извлекаем слабые навыки из rationale
        2. Формируем сообщение с фокусом на этих навыках
        3. Возвращаем результат с флагом адаптивного повторения
        """
        weak_skills = rationale.get('weak_skills', [])
        skill_names = [ws['skill'] for ws in weak_skills if isinstance(ws, dict) and 'skill' in ws]

        if not skill_names:
            skill_names = ['grammar', 'vocabulary']  # Фолбэк навыки

        logger.info(
            f"Adaptive repeat for lesson {enrollment.current_lesson.id}, "
            f"focus skills: {', '.join(skill_names)}"
        )

        return ProgressionResult(
            next_action="ADAPTIVE_REPEAT_LESSON",
            restart_required=True,
            message=f"Адаптивное повторение урока с фокусом на навыках: {', '.join(skill_names)}"
        )

    def _default_fallback(self, enrollment: Enrollment, decision: Decision) -> ProgressionResult:
        """
        Фолбэк при неизвестном коде решения.
        """
        logger.warning(f"Default fallback for decision {decision.code} in enrollment {enrollment.pk}")
        return ProgressionResult(
            next_action="REPEAT_LESSON",
            restart_required=True,
            message="Неизвестное решение. Требуется повторное прохождение урока."
        )

    def _error_fallback(self, enrollment: Enrollment, error: str) -> ProgressionResult:
        """
        Фолбэк при ошибке применения решения.
        """
        logger.error(f"Error fallback for enrollment {enrollment.pk}: {error}")
        return ProgressionResult(
            next_action="ERROR_FALLBACK",
            restart_required=True,
            message=f"Ошибка при применении решения: {error[:50]}..."
        )