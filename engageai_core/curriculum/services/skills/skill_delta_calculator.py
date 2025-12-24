from typing import Dict, Optional

from curriculum.models.assessment.assessment import Assessment
from curriculum.models.content.task import Task
from curriculum.models.skills.skill_trajectory import SkillTrajectory
from curriculum.models.student.enrollment import Enrollment


class SkillDeltaCalculator:
    """
    Рассчитывает изменения навыков (skill deltas)
    на основе Assessment и контекста обучения.

    v2:
    - skill-specific scores
    - baseline policy
    - stability-aware damping
    """

    BASELINE_DEFAULT = 0.6
    MAX_DELTA = 0.1

    SKILL_SCORE_MAP = {
        "grammar": "score_grammar",
        "vocabulary": "score_vocabulary",
        "listening": "score_listening",
        "reading": "score_reading",
        "writing": "score_writing",
        "speaking": "score_speaking",
    }

    def calculate(
            self,
            *,
            assessment: Assessment,
            task: Task,
            enrollment: Enrollment,
    ) -> Dict[str, float]:
        """
        Основной метод.

        Возвращает:
            skill_name → delta
        """

        deltas: Dict[str, float] = {}

        feedback = assessment.structured_feedback or {}

        for skill, score_key in self.SKILL_SCORE_MAP.items():
            score = feedback.get(score_key)
            if score is None:
                continue

            baseline = self._baseline_for_skill(
                task=task,
            )

            raw_delta = score - baseline

            stability = self._get_skill_stability(
                student=enrollment.student,
                skill=skill,
            )

            effective_delta = raw_delta * (1 - stability)

            delta = self._clamp(effective_delta)

            if delta != 0.0:
                deltas[skill] = delta

        return deltas

    def _baseline_for_skill(
            self,
            *,
            task: Task,
    ) -> float:
        """
        Policy-based baseline.

        v2 (простой вариант):
        - диагностические задания → ниже baseline
        - обычные → default
        """

        if getattr(task, "is_diagnostic", False):
            return 0.5

        return self.BASELINE_DEFAULT

    def _get_skill_stability(
            self,
            *,
            student,
            skill: str,
    ) -> float:
        """
        Возвращает stability навыка из SkillTrajectory.
        Если данных нет — считаем навык нестабильным.
        """

        try:
            trajectory = SkillTrajectory.objects.get(
                student=student,
                skill=skill
            )
            return trajectory.stability
        except SkillTrajectory.DoesNotExist:
            return 0.0

    def _clamp(self, value: float) -> float:
        """
        Ограничивает влияние одного задания.
        """

        if value > self.MAX_DELTA:
            return self.MAX_DELTA
        if value < -self.MAX_DELTA:
            return -self.MAX_DELTA
        return value
