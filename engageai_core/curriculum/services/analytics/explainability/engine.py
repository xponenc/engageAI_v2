class ExplainabilityEngine:
    """
    Формирует объяснение решений системы.
    """

    def explain_decision(
        self,
        decision,
        metrics,
        counterfactual=None
    ):
        explanation = {
            "decision": decision.outcome,
            "confidence": decision.confidence,
            "reasons": decision.reasons,
        }

        if counterfactual:
            explanation["counterfactual"] = {
                "alternative": counterfactual.decision,
                "effect": counterfactual.predicted_effect
            }

        return explanation
