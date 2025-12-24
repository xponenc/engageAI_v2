from curriculum.models.assessment.assessment import Assessment
from curriculum.models.content.lesson import Lesson
from curriculum.models.progress.lesson_transition import LessonTransition
from curriculum.models.skills.skill_snapshot import SkillSnapshot


class LessonExplainer:
    """
    LessonExplainer формирует объяснение transition.
    """

    def explain(
        self,
        transition: LessonTransition
    ) -> dict:
        """
        Основной метод объяснения.
        """

        assessment: Assessment = transition.assessment
        snapshot: SkillSnapshot | None = transition.skill_snapshot
        lesson: Lesson = transition.from_lesson

        objectives = [
            obj.identifier
            for obj in lesson.learning_objectives.all()
        ]

        professional_context = [
            tag.name
            for task in lesson.tasks.all()
            for tag in task.professional_tags.all()
        ]

        skill_changes = snapshot.to_dict()

        return {
            "lesson_id": lesson.pk,
            "decision_code": transition.decision_code,
            "objectives": objectives,
            "professional_context": professional_context,
            "skill_changes": skill_changes if skill_changes else {},
            "assessment_summary": assessment.structured_feedback,
        }
