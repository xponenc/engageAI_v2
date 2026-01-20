from curriculum.models.governance.teacher_override import TeacherOverride


class TeacherOverrideService:
    """
    Управляет переопределениями преподавателя.
    """

    def apply_override(
        self,
        teacher,
        student,
        lesson,
        system_decision,
        overridden_decision,
        reason: str
    ) -> TeacherOverride:
        """
        Фиксирует override и возвращает его.
        """

        return TeacherOverride.objects.create(
            teacher=teacher,
            student=student,
            lesson=lesson,
            original_decision=system_decision.outcome,
            overridden_decision=overridden_decision,
            reason=reason
        )
