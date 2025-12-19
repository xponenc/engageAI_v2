from curriculum.models import CurrentSkill


class SkillStateUpdater:
    """
    Обновляет текущее состояние навыков студента
    после Assessment.

    Использует экспоненциальное сглаживание (EMA),
    чтобы навык отражал устойчивый прогресс, а не один ответ.

    Task → Response
    ↓
    Assessment (LLM)
    ↓
    SkillStateUpdater
    ↓
    LessonMetricsCalculator
    ↓
    AdaptiveDecisionEngine
    """

    BASE_ALPHA = 0.2

    def update_from_assessment(self, student, assessment):
        feedback = assessment.structured_feedback
        scores = feedback.get("scores", {})
        confidence = feedback.get("confidence", 0.5)

        alpha = self.BASE_ALPHA * confidence

        for skill, value in scores.items():
            if value is None:
                continue

            obj, _ = CurrentSkill.objects.get_or_create(
                student=student,
                skill=skill
            )

            obj.score = obj.score * (1 - alpha) + value * alpha
            obj.confidence = max(obj.confidence, confidence)
            obj.save()