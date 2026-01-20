class AdaptiveDecision:
    """
    Структурированное решение системы.
    """

    def __init__(self, outcome, confidence, reasons):
        self.outcome = outcome
        self.confidence = confidence
        self.reasons = reasons


class AdaptiveDecisionEngine:
    """
    Принимает решение по уроку на основе метрик.
    """

    def decide(self, metrics) -> AdaptiveDecision:
        if metrics.failure_streak >= 3:
            return AdaptiveDecision(
                outcome="SIMPLIFY",
                confidence=0.85,
                reasons=["Высокая серия неудач"]
            )

        if metrics.success_ratio > 0.9:
            return AdaptiveDecision(
                outcome="ADVANCE",
                confidence=0.92,
                reasons=["Высокая успешность"]
            )

        return AdaptiveDecision(
            outcome="REPEAT",
            confidence=0.6,
            reasons=["Недостаточная устойчивость"]
        )
