from curriculum.models.progress.lesson_transition import LessonTransition
from curriculum.services.explainability.admin_explainer import AdminExplainabilityService
from curriculum.services.explainability.lesson_explainer import LessonExplainer
from curriculum.services.feedback.student_explanation_builder import StudentExplanationBuilder


class ExplainabilityService:
    def __init__(
            self,
            lesson_explainer: LessonExplainer,
            admin_explainer: AdminExplainabilityService,
            student_explainer: StudentExplanationBuilder
    ):
        self.lesson_explainer = lesson_explainer
        self.admin_explainer = admin_explainer
        self.student_explainer = student_explainer

    def explain_for_admin(self, transition_id):
        transition = LessonTransition.objects.get(id=transition_id)
        return self.lesson_explainer.explain(transition)

    def explain_for_student(self, transition_id, tone_strategy):
        transition = LessonTransition.objects.get(id=transition_id)
        metrics = self._extract_metrics(transition)
        decision = self._get_decision(transition)
        return self.student_explainer.build(decision, metrics, tone_strategy)