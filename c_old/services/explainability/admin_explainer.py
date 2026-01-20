from typing import Dict, Any

from curriculum.models.skills.skill_trajectory import SkillTrajectory
from curriculum.models.student.enrollment import Enrollment
from curriculum.services.explainability.explainability_engine import ExplainabilityEngine


class AdminExplainabilityService:
    """
    Сервис объяснимости для преподавателя / администратора.

    Назначение:
    - агрегирует explainability данные в одном месте
    - не содержит HTTP логики
    - не сериализует данные
    - используется в views и (позже) background reports
    """

    def build_for_student(self, student) -> Dict[str, Any]:
        """
        Собирает полный explainability-контекст по студенту.

        Используется:
        - админка
        - teacher dashboard
        - audit logs
        """

        enrollment = Enrollment.objects.filter(
            student=student,
            is_active=True
        ).select_related(
            "course", "current_lesson"
        ).first()

        if not enrollment:
            return {
                "error": "Student is not enrolled in any active course"
            }

        # Последний outcome урока (результат адаптации)
        last_outcome = enrollment.last_lesson_outcome

        explanation = ExplainabilityEngine().explain_lesson_outcome(
            student=student,
            outcome=last_outcome
        )

        trajectories = SkillTrajectory.objects.filter(
            student=student
        )

        return {
            "student": student,
            "course": enrollment.course,
            "current_lesson": enrollment.current_lesson,
            "last_outcome": last_outcome,
            "explanation": explanation,
            "skill_trajectories": trajectories,
        }
