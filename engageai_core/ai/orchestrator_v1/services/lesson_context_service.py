from asgiref.sync import sync_to_async
from django.db.models import Count, Q

from curriculum.models import LessonAssessmentResult, TaskAssessmentResult, Task
from curriculum.models.assessment.lesson_assesment import AssessmentStatus
from curriculum.models.content.lesson import Lesson
from curriculum.models.student.enrollment import Enrollment
from ai.orchestrator_v1.context.lesson_context import LessonContext


class LessonContextService:
    @classmethod
    async def get_context(cls, lesson_id: int, user_id: int, user_message: str = "") -> LessonContext:
        # 1. Урок + курс
        lesson = await Lesson.objects.select_related("course").aget(id=lesson_id)
        course = lesson.course

        # 2. Количество задач урока (без загрузки самих объектов)
        total_tasks = await Task.objects.filter(lesson_id=lesson.id).acount()

        # 3. Enrollment по цепочке User → Student → Enrollment → Course
        enrollment = await Enrollment.objects.select_related(
            "student",
            "student__user",
            "course",
        ).filter(
            student__user_id=user_id,
            course=course,
            is_active=True,
        ).afirst()

        completed_tasks = 0
        correct_tasks = 0
        incorrect_tasks = 0
        last_task_result = None

        if enrollment:
            # Агрегаты по оценкам задач урока
            stats = await sync_to_async(
                lambda: TaskAssessmentResult.objects.filter(
                    enrollment=enrollment,
                    task__lesson_id=lesson.id,
                ).aggregate(
                    total=Count("id"),
                    correct=Count("id", filter=Q(is_correct=True)),
                    incorrect=Count("id", filter=Q(is_correct=False)),
                )
            )()

            completed_tasks = stats["total"] or 0
            correct_tasks = stats["correct"] or 0
            incorrect_tasks = stats["incorrect"] or 0

            # Последний результат по времени оценки
            last_assessment = await TaskAssessmentResult.objects.filter(
                enrollment=enrollment,
                task__lesson_id=lesson.id,
            ).order_by("-evaluated_at").afirst()

            if last_assessment:
                if last_assessment.is_correct is True:
                    last_task_result = "correct"
                elif last_assessment.is_correct is False:
                    last_task_result = "incorrect"

        # 4. Статус оценки урока
        lesson_assessment = None
        if enrollment:
            lesson_assessment = await LessonAssessmentResult.objects.filter(
                enrollment=enrollment,
                lesson=lesson,
            ).order_by("-completed_at").afirst()

        # Состояние урока
        if lesson_assessment and lesson_assessment.status == AssessmentStatus.COMPLETED:
            state = "COMPLETED"
            progress_percent = 100.0
        elif completed_tasks > 0 and total_tasks > 0:
            state = "IN_PROGRESS"
            progress_percent = min(100.0, (completed_tasks / total_tasks) * 100)
        else:
            state = "OPEN"
            progress_percent = 0.0

        # 5. Ремедиация / следующий урок
        needs_remediation = False
        remediation_reason = None
        next_lesson_id = None
        next_lesson_is_remedial = False

        if lesson_assessment and lesson_assessment.status == AssessmentStatus.COMPLETED:
            if lesson_assessment.overall_score is not None and lesson_assessment.overall_score < 0.6:
                needs_remediation = True
                remediation_reason = "low_overall_score"
                next_lesson_is_remedial = True

                # TODO: здесь, вероятно, должен быть ремедиальный урок,
                # сейчас просто берём следующий по порядку или спец-урок, если он помечен is_remedial
                next_lesson = await Lesson.objects.filter(
                    course=course,
                    order__gt=lesson.order,
                    is_remedial=True,
                ).order_by("order").afirst()
                if next_lesson:
                    next_lesson_id = next_lesson.id
            else:
                # Успешное завершение — следующий обычный урок в курсе
                next_lesson = await Lesson.objects.filter(
                    course=course,
                    order__gt=lesson.order,
                    is_remedial=False,
                ).order_by("order").afirst()
                if next_lesson:
                    next_lesson_id = next_lesson.id

        # 6. Формируем контекст
        professional_tags = await sync_to_async(
            lambda: list(course.professional_tags.values_list("name", flat=True))
        )()

        return LessonContext(
            lesson_id=lesson.id,
            lesson_title=lesson.title,
            lesson_type=lesson.skill_focus[0] if lesson.skill_focus else "general",
            lesson_content=lesson.content,
            course_id=course.id,
            course_title=course.title,
            cefr_level=lesson.required_cefr,
            professional_tags=professional_tags,
            skill_focus=lesson.skill_focus,
            duration_minutes=lesson.duration_minutes,
            state=state,
            progress_percent=progress_percent,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            correct_tasks=correct_tasks,
            incorrect_tasks=incorrect_tasks,
            last_task_result=last_task_result,
            needs_remediation=needs_remediation,
            remediation_reason=remediation_reason,
            next_lesson_id=next_lesson_id,
            next_lesson_is_remedial=next_lesson_is_remedial,
            adaptive_parameters=lesson.adaptive_parameters or {},
        )
