from typing import Optional

from curriculum.models.governance.teacher_override import TeacherOverride
from curriculum.models.assessment.assessment import Assessment
from curriculum.models.progress.lesson_transition import LessonTransition
from curriculum.models.skills.skill_snapshot import SkillSnapshot
from curriculum.models.student.enrollment import Enrollment
from curriculum.models.content.task import Task

from curriculum.services.decisions.decision_service import Decision


class TransitionRecorder:
    """
    TransitionRecorder фиксирует факт принятия решения и его основания.

    Он НЕ:
    - принимает решения
    - изменяет progression
    - интерпретирует результаты

    Он:
    - записывает transition как audit-log

    Он записывает:
        ЧТО произошло (какое решение)
        КОГДА
        В КАКОМ КОНТЕКСТЕ
        НА ОСНОВАНИИ ЧЕГО (assessment, skills, overrides)

    TODO (TransitionRecorder):

    1. Поддержка multi-decision transitions (compound decisions)
    2. Версионирование decision engine
    3. Явное хранение metrics snapshot
    4. Поддержка rollback / correction transitions
    """

    def record(
        self,
        enrollment: Enrollment,
        task: Task,
        decision: Decision,
        assessment_result: Assessment,
        skill_update_result: Optional[SkillSnapshot] = None,
    ) -> LessonTransition:
        """
        Записывает LessonTransition.

        Параметры:
        - enrollment: текущее зачисление студента
        - task: задание, на котором было принято решение
        - decision: принятое решение (ADVANCE / REPEAT / etc)
        - assessment_result: результат оценки
        - skill_update_result: snapshot навыков после обновления
        """

        from_lesson = enrollment.current_lesson

        # Пытаемся определить целевой урок
        to_lesson = None
        if decision.code == "ADVANCE_LESSON":
            to_lesson = enrollment.current_lesson
        elif decision.code == "REPEAT_LESSON":
            to_lesson = enrollment.current_lesson
        else:
            # для task-level решений урок не меняется
            to_lesson = enrollment.current_lesson

        # Проверяем, был ли teacher override
        teacher_override = (
            TeacherOverride.objects
            .filter(
                lesson=enrollment.current_lesson,
                student=enrollment.student
            )
            .order_by("-created_at")
            .first()
        )

        transition = LessonTransition.objects.create(
            enrollment=enrollment,
            from_lesson=from_lesson,
            to_lesson=to_lesson,
            task=task,
            decision_code=decision.code,
            assessment=assessment_result,
            skill_snapshot=skill_update_result,
            teacher_override=True if teacher_override else False,
        )

        return transition
