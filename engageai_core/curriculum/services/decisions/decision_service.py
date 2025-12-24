from dataclasses import dataclass
from typing import Dict, Any, Optional

from curriculum.models.student.enrollment import Enrollment
from curriculum.models.content.lesson import Lesson
from curriculum.models.governance.teacher_override import TeacherOverride
from curriculum.services.skills.skill_update_service import SkillUpdateResult

"""
Пример решения

Вход
{
  "updated_skills": {
    "grammar": 0.42
  },
  "deltas": {
    "grammar": -0.1
  }
}
Выход

{
  "code": "ADVANCE_TASK",
  "confidence": 0.6,
  "rationale": {
    "reason": "default_progression"
  }
}
"""


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
    и принимает решение о следующем шаге.

    TODO (DecisionService):

    1. Weighting decisions by ProfessionalTag
    2. LearningObjective-aware completion logic
    3. Probabilistic decision model
    4. Confidence calibration
    5. Decision simulation / replay
    """

    def decide(
        self,
        enrollment: Enrollment,
        lesson: Lesson,
        skill_profile_update: SkillUpdateResult,
    ) -> Decision:
        """
        Основной метод принятия решения.

        Алгоритм (v1):
        1. Проверка TeacherOverride
        2. Проверка completion урока
        3. Анализ skill deltas
        """

        # Teacher override — абсолютный приоритет
        override = self._get_active_teacher_override(enrollment)
        print(f"ОБРАБОТКА ОТВЕТА 9. DecisionService # override:\n{override}\n\n", )

        if override:
            return Decision(
                code=override.decision_code,
                confidence=1.0,
                rationale={
                    "source": "teacher_override",
                    "override_id": override.id,
                },
            )

        # 2️⃣ Проверка завершения урока
        if self._lesson_completed(lesson, skill_profile_update):
            return Decision(
                code="ADVANCE_LESSON",
                confidence=0.8,
                rationale={
                    "reason": "lesson_completed",
                    "skills": skill_profile_update.updated_skills,
                },
            )

        # 3️⃣ Анализ ухудшения навыков
        if self._significant_skill_drop(skill_profile_update):
            return Decision(
                code="REPEAT_LESSON",
                confidence=0.7,
                rationale={
                    "reason": "skill_regression",
                    "deltas": skill_profile_update.deltas,
                },
            )

        # 4️⃣ По умолчанию — двигаемся дальше по заданиям
        return Decision(
            code="ADVANCE_TASK",
            confidence=0.6,
            rationale={
                "reason": "default_progression",
            },
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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

    def _lesson_completed(
        self,
        lesson: Lesson,
        skill_update: SkillUpdateResult
    ) -> bool:
        """
        Проверяет, можно ли считать урок завершённым.

        ⚠️ v1: эвристика
        """

        # Используем skill_focus урока, если он есть
        if hasattr(lesson, "skill_focus") and lesson.skill_focus:
            for skill in lesson.skill_focus:
                if skill_update.updated_skills.get(skill, 0) < 0.6:
                    return False
            return True

        # Fallback: если нет явного фокуса
        return True

    def _significant_skill_drop(
        self,
        skill_update: SkillUpdateResult
    ) -> bool:
        """
        Проверяет, есть ли существенная деградация навыков.
        """

        for delta in skill_update.deltas.values():
            if delta < -0.2:
                return True
        return False
