class CounterfactualResult:
    """
    Результат альтернативного сценария.
    """

    def __init__(self, decision, predicted_effect):
        self.decision = decision
        self.predicted_effect = predicted_effect


class CounterfactualAnalyzer:
    """
    Анализирует альтернативные решения.
    """

    def analyze(self, metrics, alternative_decision) -> CounterfactualResult:
        """
        Не принимает решение — только симулирует последствия.
        """

        if alternative_decision == "ADVANCE":
            effect = "Риск снижения мотивации при недостаточной устойчивости"

        elif alternative_decision == "SIMPLIFY":
            effect = "Вероятное повышение уверенности, но замедление прогресса"

        else:
            effect = "Консолидация навыка без изменения сложности"

        return CounterfactualResult(
            decision=alternative_decision,
            predicted_effect=effect
        )
