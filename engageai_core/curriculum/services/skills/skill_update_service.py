from dataclasses import dataclass
from typing import Dict, List

from curriculum.models.skills.skill_snapshot import SkillSnapshot
from curriculum.models.student.enrollment import Enrollment
from curriculum.models.content.task import Task
from curriculum.models.assessment.assessment import Assessment

from curriculum.models.skills.skill_profile import CurrentSkillProfile
from curriculum.services.skills.skill_delta_calculator import SkillDeltaCalculator
from curriculum.services.skills.skill_trajectory_updater import SkillTrajectoryUpdater


@dataclass
class SkillUpdateResult:
    """
    Результат обновления навыков.

    Используется:
    - DecisionService
    - TransitionRecorder
    - Explainability
    """

    updated_skills: Dict[str, float]
    deltas: Dict[str, float]
    snapshot: SkillSnapshot
    error_events: List[str]


class SkillUpdateService:
    """
    SkillUpdateService обновляет состояние навыков студента
    на основе результата assessment.

    TODO (SkillUpdateService):

    1. Explicit Skill model
    2. Formal mapping Task → SkillSignal
    3. Weighting by ProfessionalTag
    4. LearningObjective ↔ Skill alignment
    5. Skill decay over time
    """

    def __init__(self):
        self.trajectory_updater = SkillTrajectoryUpdater()
        self.delta_calculator = SkillDeltaCalculator()

    def update(
            self,
            enrollment: Enrollment,
            task: Task,
            assessment_result: Assessment,
    ) -> SkillUpdateResult:
        """
        Основной метод обновления навыков.

        Алгоритм (v1):
        1. Загружаем текущий SkillProfile
        2. Интерпретируем assessment → skill deltas
        3. Обновляем профиль
        4. Фиксируем snapshot и trajectory
        5. Логируем ошибки
        """

        # Получаем текущий профиль
        skill_profile, _ = CurrentSkillProfile.objects.get_or_create(
            student=enrollment.student
        )

        # Получаем текущие навыки как словарь
        current_skills = skill_profile.to_dict()

        # Рассчитываем дельты
        deltas = self.delta_calculator.calculate(
            assessment=assessment_result,
            task=task,
            enrollment=enrollment,
        )

        # Обновляем навыки
        updated_skills = {}
        for skill_name, delta in deltas.items():
            if skill_name in current_skills:
                new_value = max(0.0, min(1.0, current_skills[skill_name] + delta))
                current_skills[skill_name] = new_value
                updated_skills[skill_name] = new_value

        # Сохраняем обновленные навыки
        skill_profile.update_from_dict(current_skills)
        skill_profile.save()

        # Создаем snapshot
        snapshot = SkillSnapshot.objects.create(
            student=enrollment.student,
            **current_skills
        )

        # Обновляем траекторию
        self.trajectory_updater.update(enrollment.student)

        return SkillUpdateResult(
            updated_skills=updated_skills,
            deltas=deltas,
            snapshot=snapshot,
            error_events=[]
        )

    def _calculate_skill_deltas(
            self,
            task: Task,
            assessment: Assessment,
    ) -> Dict[str, float]:
        """
        Интерпретирует structured_feedback Assessment
        в изменения навыков.

        v1:
        - используем skill-specific scores
        - baseline = 0.6
        - delta ограничена
        """

        deltas: Dict[str, float] = {}

        feedback = assessment.structured_feedback or {}

        BASELINE = 0.6
        # Это дизайнерское допущение:
        # 0.5 — “угадал”
        # 0.6 — “продемонстрировал навык”
        MAX_DELTA = 0.1

        skill_score_map = {
            "grammar": feedback.get("score_grammar"),
            "vocabulary": feedback.get("score_vocabulary"),
            "listening": feedback.get("score_listening"),
            "reading": feedback.get("score_reading"),
            "writing": feedback.get("score_writing"),
            "speaking": feedback.get("score_speaking"),
        }

        for skill, score in skill_score_map.items():
            if score is None:
                continue

            delta = score - BASELINE
            delta = max(-MAX_DELTA, min(MAX_DELTA, delta))

            deltas[skill] = delta

        return deltas
