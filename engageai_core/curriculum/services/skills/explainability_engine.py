from progress.models import SkillTrajectory


class ExplainabilityEngine:
    """
    Интерпретирует SkillTrajectory и объясняет решения системы.

  - читает SkillTrajectory
    - объясняет решения AdaptiveDecisionEngine
    - возвращает структурированные причины
    - НЕ принимает решений
    - НЕ изменяет данные
    - Только объясняет.

    SkillSnapshot
    ↓
    SkillTrajectory
    ↓
    ExplainabilityEngine   ← ТЫ ЗДЕСЬ
    ↓
    AdaptiveDecisionEngine
    ↓
    FeedbackBuilder / UI / Logs
    ↓
    ToneAdapter
    ↓
    YAML template
    ↓
    User message

    пример выдачи
    {
        "decision": "SIMPLIFY",
        "primary_reason": "Обнаружено снижение навыков: grammar, listening",
        "supporting_factors": [
            {
                  "type": "decline",
                  "skills": ["grammar", "listening"]
            },
            {
                  "type": "instability",
                  "skills": ["speaking"]
            }
        ],
        "skill_insights": [
            {"skill": "grammar", "direction": "declining"},
            {"skill": "listening", "direction": "declining"},
            {"skill": "speaking", "direction": "stable"}
        ],
        "confidence": 0.81
    }
    """

    def explain_lesson_outcome(self, student, outcome):
        """Формирует полное объяснение принятого решения на основе траекторий навыков."""

        trajectories = SkillTrajectory.objects.filter(student=student)

        skill_insights = []
        unstable_skills = []
        declining_skills = []

        for traj in trajectories:
            insight = self._analyze_skill(traj)
            skill_insights.append(insight)

            if insight["trend"] < -0.1:
                declining_skills.append(traj.skill)

            if insight["stability"] < 0.4:
                unstable_skills.append(traj.skill)

        explanation = {
            "decision": outcome,
            "primary_reason": self._primary_reason(outcome, declining_skills, unstable_skills),
            "supporting_factors": self._supporting_factors(declining_skills, unstable_skills),
            "skill_insights": skill_insights,
            "confidence": self._explanation_confidence(skill_insights),
        }

        return explanation

    def _analyze_skill(self, trajectory):
        """
        Переводит числовые параметры навыка в человекочитаемое состояние.
        """

        if trajectory.trend > 0.15:
            direction = "improving"
        elif trajectory.trend < -0.15:
            direction = "declining"
        else:
            direction = "stable"

        return {
            "skill": trajectory.skill,
            "trend": trajectory.trend,
            "stability": trajectory.stability,
            "direction": direction,
        }

    def _primary_reason(self, outcome, declining, unstable):
        """Определяет главную причину решения.

        """
        if outcome == "SIMPLIFY" and declining:
            return f"Обнаружено снижение навыков: {', '.join(declining)}"

        if outcome == "REPEAT" and unstable:
            return f"Навыки нестабильны: {', '.join(unstable)}"

        if outcome == "ADVANCE":
            return "Навыки растут стабильно"

        return "Недостаточно данных для чёткого вывода"

    def _supporting_factors(self, declining, unstable):
        """Добавляет вторичные факторы, подтверждающие решение."""
        factors = []

        if declining:
            factors.append({
                "type": "decline",
                "skills": declining
            })

        if unstable:
            factors.append({
                "type": "instability",
                "skills": unstable
            })

        return factors

    def _explanation_confidence(self, insights):
        """
        Оценивает, насколько можно доверять объяснению.
        Текущая логика
        средняя stability по навыкам
        0.0 → мало данных
        1.0 → стабильная картина
                """
        if not insights:
            return 0.0

        avg_stability = sum(i["stability"] for i in insights) / len(insights)
        return round(avg_stability, 2)


