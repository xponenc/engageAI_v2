class StudentExplanationBuilder:
    """
    Формирует упрощённое, мотивирующее объяснение
    решений системы для студента.

    Назначение
        объяснить почему следующий шаг такой
        формирует доверие
        снижает тревожность
        подготавливает ожидания

    Содержит
        explanation (1–2 предложения)
        expectation (что будет дальше)
        reassurance (опционально)

    НЕ содержит
        highlights
        оценок
        сравнений навыков
    """

    def build(self, decision, metrics, tone):
        """
        decision: AdaptiveDecision
        metrics: LessonMetrics
        tone: ToneStrategy
        """

        if decision.outcome == "ADVANCE":
            return self._advance_explanation(tone)

        if decision.outcome == "REPEAT":
            return self._repeat_explanation(tone)

        if decision.outcome == "SIMPLIFY":
            return self._simplify_explanation(tone)

        return self._neutral_explanation(tone)

    def _advance_explanation(self, tone):
        return {
            "title": "Отличная работа 🚀",
            "message": tone.praise(),
            "explanation": (
                "Ты уверенно справляешься с этим материалом, "
                "поэтому мы идём дальше."
            ),
            "expectation": "В следующем уроке будет чуть больше вызова."
        }

    def _repeat_explanation(self, tone):
        return {
            "title": "Давай закрепим 💪",
            "message": tone.retry(),
            "explanation": (
                "Этот материал почти освоен. "
                "Повторим его ещё раз с новыми примерами."
            ),
            "expectation": "После этого станет заметно легче."
        }

    def _simplify_explanation(self, tone):
        return {
            "title": "Ничего страшного 🙂",
            "message": tone.support(),
            "explanation": (
                "Мы немного упростим следующий шаг, "
                "чтобы ты чувствовал себя увереннее."
            ),
            "expectation": "Ты быстро вернёшься к более сложным заданиям."
        }

    def _neutral_explanation(self, tone):
        return {
            "title": "Продолжаем",
            "message": tone.neutral(),
            "explanation": "Идём дальше шаг за шагом.",
            "expectation": None
        }
