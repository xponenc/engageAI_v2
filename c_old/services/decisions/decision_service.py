import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from curriculum.models.student.enrollment import Enrollment
from curriculum.models.content.lesson import Lesson
from curriculum.models.governance.teacher_override import TeacherOverride
from curriculum.services.skills.skill_update_service import LessonSkillSnapshotResult

logger = logging.getLogger(__name__)

ALLOWED_DECISION_CODES = {
    "ADVANCE_LESSON",
    "COMPLETE_COURSE",
    "REPEAT_LESSON",
    "ADAPTIVE_REPEAT_LESSON"
}


@dataclass
class Decision:
    """
    Value object, описывающий принятое решение.
    """
    code: str
    confidence: float
    rationale: Dict[str, Any]


class DecisionService:
    """
    DecisionService интерпретирует состояние обучения
    и принимает решения о следующем шаге после завершения урока.

    Работает только в LESSON_MODE:
    - На основе агрегированных данных всего урока
    - Использует LessonSkillSnapshotResult
    - Принимает решения о переходе между уроками

    УДАЛЕННЫЕ ФУНКЦИИ:
    - Single-task режим (устарел)
    - SkillUpdateResult (заменен на LessonSkillSnapshotResult)
    """

    def decide_lesson_completion(
            self,
            enrollment: Enrollment,
            lesson: Lesson,
            skill_snapshot_result: LessonSkillSnapshotResult,
    ) -> Decision:
        """
        Основной метод принятия решения о завершении урока.

        Алгоритм (v1):
        1. Проверка TeacherOverride
        2. Проверка критериев завершения урока
        3. Анализ прогресса по навыкам
        4. Проверка деградации навыков
        5. Фолбэк решение

        Args:
            enrollment: Зачисление студента
            lesson: Текущий урок
            skill_snapshot_result: Результат агрегации по уроку

        Returns:
            Decision: Принятое решение
        """
        # 1. Teacher override — абсолютный приоритет
        override = self._get_active_teacher_override(enrollment)
        if override:
            # Валидация переопределенного решения
            if override.overridden_decision not in ALLOWED_DECISION_CODES:
                logger.warning(
                    f"Invalid overridden decision '{override.overridden_decision}' "
                    f"in override {override.pk}. Using default fallback."
                )
                return self._default_fallback_decision(enrollment, lesson, skill_snapshot_result)

            logger.info(
                f"Teacher override found for enrollment {enrollment.pk}, "
                f"override: {override.original_decision} → {override.overridden_decision}"
            )
            return Decision(
                code=override.overridden_decision,  # ИСПРАВЛЕНО: используем overridden_decision
                confidence=1.0,
                rationale={
                    "source": "teacher_override",
                    "override_id": override.pk,
                    "original_decision": override.original_decision,
                    "overridden_decision": override.overridden_decision,
                    "reason": override.reason[:100] + "..." if len(override.reason) > 100 else override.reason,
                    "created_at": override.created_at.isoformat()
                },
            )

        # 2. Проверка критериев завершения урока
        if self._lesson_passing_criteria_met(lesson, skill_snapshot_result):
            logger.info(f"Lesson completion criteria met for enrollment {enrollment.pk}, lesson {lesson.pk}")

            # 2a. Проверка завершения всего курса
            if self._course_completed(enrollment, lesson):
                return Decision(
                    code="COMPLETE_COURSE",
                    confidence=0.9,
                    rationale={
                        "reason": "course_completed",
                        "lesson_progress": skill_snapshot_result.aggregated_scores,
                        "skill_progress": skill_snapshot_result.skill_progress
                    },
                )

            return Decision(
                code="ADVANCE_LESSON",
                confidence=0.85,
                rationale={
                    "reason": "lesson_completed",
                    "lesson_id": lesson.pk,
                    "completion_metrics": {
                        "aggregated_scores": skill_snapshot_result.aggregated_scores,
                        "skill_progress": skill_snapshot_result.skill_progress,
                        "error_tags": skill_snapshot_result.error_events
                    }
                },
            )

        # 3. Проверка критической деградации навыков
        if self._critical_skill_regression(skill_snapshot_result):
            logger.warning(f"Critical skill regression detected for enrollment {enrollment.pk}")
            return Decision(
                code="REPEAT_LESSON",
                confidence=0.9,
                rationale={
                    "reason": "critical_skill_regression",
                    "regressed_skills": self._get_regressed_skills(skill_snapshot_result),
                    "skill_progress": skill_snapshot_result.skill_progress
                },
            )

        # 4. Проверка частичного прогресса
        if self._partial_progress_detected(lesson, skill_snapshot_result):
            logger.info(f"Partial progress detected for enrollment {enrollment.pk}")
            return Decision(
                code="ADAPTIVE_REPEAT_LESSON",
                confidence=0.75,
                rationale={
                    "reason": "partial_progress",
                    "progress_metrics": self._calculate_progress_metrics(skill_snapshot_result),
                    "weak_skills": self._identify_weak_skills(skill_snapshot_result)
                },
            )

        # 5. Фолбэк: повтор урока
        logger.info(f"Default fallback decision for enrollment {enrollment.pk}")
        return Decision(
            code="REPEAT_LESSON",
            confidence=0.6,
            rationale={
                "reason": "default_fallback",
                "lesson_id": lesson.pk,
                "snapshot_id": skill_snapshot_result.snapshot.pk if skill_snapshot_result.snapshot else None
            },
        )

    def _default_fallback_decision(
            self,
            enrollment: Enrollment,
            lesson: Lesson,
            skill_snapshot_result: LessonSkillSnapshotResult
    ) -> Decision:
        """Фолбэк решение при ошибках валидации"""
        logger.warning(f"Using default fallback decision for enrollment {enrollment.pk}")
        return Decision(
            code="REPEAT_LESSON",
            confidence=0.5,
            rationale={
                "reason": "validation_fallback",
                "original_override_decision": getattr(skill_snapshot_result, 'overridden_decision', None),
                "lesson_id": lesson.pk
            }
        )
    def _get_active_teacher_override(
            self,
            enrollment: Enrollment
    ) -> Optional[TeacherOverride]:
        """
        Возвращает активный teacher override, если есть.
        """
        return (
            TeacherOverride.objects.filter(
                student=enrollment.student,
                lesson=enrollment.current_lesson,
            ).order_by("-created_at").first()
        )

    def _lesson_passing_criteria_met(self, lesson: Lesson, skill_snapshot_result: LessonSkillSnapshotResult) -> bool:
        """Проверяет, соответствует ли прогресс студента критериям завершения урока."""
        # 1. Целевые навыки
        target_skills = getattr(lesson, 'skill_focus', []) or ['grammar', 'vocabulary']
        for skill in target_skills:
            if skill_snapshot_result.aggregated_scores.get(skill, 0) < 0.7:
                logger.debug(
                    f"Target skill {skill} not sufficient (score: {skill_snapshot_result.aggregated_scores.get(skill, 0)} < 0.7)")
                return False

        # 2. Прогресс по целевым навыкам
        for skill in target_skills:
            progress = skill_snapshot_result.skill_progress.get(skill, {})
            delta = progress.get('delta', 0)
            if delta < 0.1:  # можно подкорректировать порог
                logger.debug(f"Target skill {skill} progress too low (delta: {delta} < 0.1)")
                return False

        # 3. Критические ошибки
        critical_errors = ['concept_gap', 'system_failure']
        for error in skill_snapshot_result.error_events:
            if any(ce in error.lower() for ce in critical_errors):
                logger.debug(f"Critical error found: {error}")
                return False

        return True

    def _critical_skill_regression(
            self,
            skill_snapshot_result: LessonSkillSnapshotResult
    ) -> bool:
        """
        Проверяет наличие критической деградации навыков (падение более чем на 0.3).
        """
        for skill, progress in skill_snapshot_result.skill_progress.items():
            delta = progress.get('delta', 0)
            if delta < -0.3:
                logger.debug(f"Critical regression detected in skill {skill}: delta={delta}")
                return True
        return False

    def _get_regressed_skills(
            self,
            skill_snapshot_result: LessonSkillSnapshotResult
    ) -> List[dict]:
        """
        Возвращает список навыков с критической регрессией.
        """
        regressed = []
        for skill, progress in skill_snapshot_result.skill_progress.items():
            delta = progress.get('delta', 0)
            if delta < -0.3:
                regressed.append({
                    'skill': skill,
                    'delta': delta,
                    'before': progress.get('before', 0),
                    'after': progress.get('after', 0)
                })
        return regressed

    def _partial_progress_detected(
            self,
            lesson: Lesson,
            skill_snapshot_result: LessonSkillSnapshotResult
    ) -> bool:
        """
        Проверяет наличие частичного прогресса (некоторые навыки улучшились).
        """
        improved_skills = 0
        target_skills = getattr(lesson, 'skill_focus', []) or ['grammar', 'vocabulary']

        for skill in target_skills:
            progress = skill_snapshot_result.skill_progress.get(skill, {})
            delta = progress.get('delta', 0)
            if delta > 0.05:  # Улучшение более чем на 0.05
                improved_skills += 1

        has_progress = improved_skills > 0 and improved_skills < len(target_skills)
        logger.debug(
            f"Partial progress check: improved_skills={improved_skills}, target_skills={len(target_skills)}, has_progress={has_progress}")
        return has_progress

    def _calculate_progress_metrics(
            self,
            skill_snapshot_result: LessonSkillSnapshotResult
    ) -> dict:
        """
        Рассчитывает метрики прогресса для частичного прохождения.
        """
        metrics = {
            'average_delta': 0.0,
            'improved_skills': 0,
            'regressed_skills': 0,
            'stable_skills': 0
        }

        deltas = []
        for progress in skill_snapshot_result.skill_progress.values():
            delta = progress.get('delta', 0)
            deltas.append(delta)

            if delta > 0.05:
                metrics['improved_skills'] += 1
            elif delta < -0.05:
                metrics['regressed_skills'] += 1
            else:
                metrics['stable_skills'] += 1

        if deltas:
            metrics['average_delta'] = sum(deltas) / len(deltas)

        return metrics

    def _identify_weak_skills(
            self,
            skill_snapshot_result: LessonSkillSnapshotResult
    ) -> List[dict]:
        """
        Определяет слабые навыки для адаптивного повторения.
        """
        weak_skills = []
        for skill, score in skill_snapshot_result.aggregated_scores.items():
            if score < 0.6:  # Порог для слабого навыка
                weak_skills.append({
                    'skill': skill,
                    'score': score,
                    'progress': skill_snapshot_result.skill_progress.get(skill, {})
                })
        return sorted(weak_skills, key=lambda x: x['score'])

    def _course_completed(self, enrollment: Enrollment, lesson: Lesson) -> bool:
        """
        Проверяет, завершен ли курс (последний урок).
        """
        next_lesson = (
            Lesson.objects.filter(
                course=lesson.course,
                order__gt=lesson.order,
                is_active=True
            ).order_by('order').first()
        )
        completed = next_lesson is None
        logger.debug(f"Course completion check: next_lesson exists={next_lesson is not None}, completed={completed}")
        return completed