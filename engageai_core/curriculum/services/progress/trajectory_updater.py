from curriculum.models import SkillSnapshot, SkillTrajectory
from curriculum.services.progress.utils.trajectory_math import calculate_trend, calculate_stability


class SkillTrajectoryUpdater:
    """
    Обновляет SkillTrajectory на основе истории SkillSnapshot.

    Используется:
    - после завершения урока
    - после диагностики
    - периодически (batch)

    Task
    ↓
    StudentTaskResponse
    ↓
    Assessment
    ↓
    SkillStateUpdater        (CurrentSkill)
    ↓
    [Lesson completed]
    ↓
    SkillSnapshotCreator    (SkillSnapshot)
    ↓
    SkillTrajectoryUpdater  ← ВОТ ОН
    ↓
    AdaptiveDecisionEngine
    ↓
    LearningAgent
    """

    MIN_SNAPSHOTS = 3

    def update(self, student):
        snapshots = SkillSnapshot.objects.filter(
            student=student
        ).order_by("snapshot_at")

        if snapshots.count() < self.MIN_SNAPSHOTS:
            return  # недостаточно данных

        skill_values = {
            "grammar": [],
            "vocabulary": [],
            "listening": [],
            "reading": [],
            "writing": [],
            "speaking": [],
        }

        for snap in snapshots:
            for skill in skill_values.keys():
                skill_values[skill].append(getattr(snap, skill))

        for skill, values in skill_values.items():
            trend = calculate_trend(values)
            stability = calculate_stability(values)

            obj, _ = SkillTrajectory.objects.get_or_create(
                student=student,
                skill=skill
            )

            obj.trend = trend
            obj.stability = stability
            obj.save()
