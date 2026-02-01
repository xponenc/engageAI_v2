# curriculum/services/lesson_context_service.py
"""
LessonContextService: ЕДИНСТВЕННАЯ ТОЧКА ВХОДА для получения контекста урока.
Содержит ВСЮ логику получения данных из БД и анализа состояния.
Соответствует ТЗ Задача 2.1: Синхронизация данных через единый сервис.
"""
from asgiref.sync import sync_to_async
from typing import Optional

from curriculum.models import LessonAssessmentResult, TaskAssessmentResult
from curriculum.models.assessment.lesson_assesment import AssessmentStatus
from curriculum.models.content.lesson import Lesson
from curriculum.models.content.task import Task
from curriculum.services.frustration_analyzer import FrustrationAnalyzer
from ai.orchestrator_v1.context.lesson_context import LessonContext


class LessonContextService:
    """
    Сервис получения контекста урока.

    Ответственность:
    - Единая точка доступа к данным урока
    - Интеграция с оценками заданий и урока
    - Расчёт состояния урока (прогресс, ремедиация)
    - Формирование контекста для агентов

    НЕ ответственность:
    - Хранение данных (это задача LessonContext)
    - Бизнес-логика маршрутизации (это задача агентов)
    """

    @classmethod
    async def get_context(cls, lesson_id: int, user_id: int, user_message: str = "") -> LessonContext:
        """
        Единственная точка входа для получения контекста урока.

        Алгоритм:
        1. Получаем урок и его курс
        2. Получаем прогресс по заданиям (из TaskAssessmentResult)
        3. Получаем статус оценки урока (из LessonAssessmentResult)
        4. Рассчитываем состояние урока и ремедиацию
        5. Возвращаем чистый контейнер данных

        ВАЖНО: НЕТ зависимостей от несуществующих сервисов!
        """
        # Шаг 1: Получаем урок с курсом
        lesson = await Lesson.objects.select_related('course').aget(id=lesson_id)

        # Шаг 2: Получаем задания урока
        tasks = await sync_to_async(
            Task.objects.filter(lesson=lesson).order_by)('order')
        total_tasks = len(tasks)

        # Шаг 3: Получаем оценки заданий студента по этому уроку
        # Находим enrollment студента для этого курса (упрощённо — первый активный)
        from curriculum.models.student.enrollment import Enrollment
        enrollment = await Enrollment.objects.filter(
            student_id=user_id,
            course=lesson.course,
            is_active=True
        ).afirst()

        completed_tasks = 0
        correct_tasks = 0
        incorrect_tasks = 0
        last_task_result = None

        if enrollment:
            # Получаем оценки заданий по этому уроку
            assessments = await sync_to_async(list)(
                TaskAssessmentResult.objects.filter(
                    enrollment=enrollment,
                    task__lesson=lesson
                ).select_related('task').order_by('-evaluated_at')
            )

            completed_tasks = len(assessments)

            # Считаем правильные/неправильные
            for assessment in assessments:
                if assessment.is_correct is True:
                    correct_tasks += 1
                elif assessment.is_correct is False:
                    incorrect_tasks += 1

            # Последний результат
            if assessments:
                last_assessment = assessments[0]
                if last_assessment.is_correct is True:
                    last_task_result = "correct"
                elif last_assessment.is_correct is False:
                    last_task_result = "incorrect"

        # Шаг 4: Получаем статус оценки урока
        lesson_assessment = None
        if enrollment:
            lesson_assessment = await LessonAssessmentResult.objects.filter(
                enrollment=enrollment,
                lesson=lesson
            ).order_by('-completed_at').afirst()

        # Определяем состояние урока
        if lesson_assessment and lesson_assessment.status == AssessmentStatus.COMPLETED:
            state = "COMPLETED"
            progress_percent = 100.0
        elif completed_tasks > 0:
            state = "IN_PROGRESS"
            progress_percent = min(100.0, (completed_tasks / total_tasks) * 100)
        else:
            state = "OPEN"
            progress_percent = 0.0

        # Шаг 5: Анализ ремедиации
        needs_remediation = False
        remediation_reason = None
        next_lesson_id = None
        next_lesson_is_remedial = False

        if lesson_assessment and lesson_assessment.status == AssessmentStatus.COMPLETED:
            if lesson_assessment.overall_score is not None and lesson_assessment.overall_score < 0.6:
                needs_remediation = True
                remediation_reason = "low_overall_score"
                next_lesson_is_remedial = True
                # В реальной системе: определение следующего урока через адаптивную маршрутизацию
                # Для пилота: следующий урок в том же курсе
                next_lesson = await Lesson.objects.filter(
                    course=lesson.course,
                    order=lesson.order
                ).afirst()
                if next_lesson:
                    next_lesson_id = next_lesson.id
            else:
                # Успешное завершение — следующий урок в курсе
                next_lesson = await Lesson.objects.filter(
                    course=lesson.course,
                    order__gt=lesson.order
                ).order_by('order').afirst()
                if next_lesson:
                    next_lesson_id = next_lesson.id

        # Шаг 6: Анализ фрустрации в рамках урока
        frustration_signals = 0
        is_critically_frustrated = False
        # TODO считать ли тут фрустрацию или вынести в отдельного агента?
        # if enrollment:
        #     # Анализируем только ошибки в рамках этого урока
        #     lesson_frustration = await sync_to_async(
        #         FrustrationAnalyzer.analyze_lesson_frustration
        #     )(enrollment.id, lesson_id, user_message)
        #
        #     frustration_signals = lesson_frustration.score
        #     is_critically_frustrated = lesson_frustration.is_critical

        # Шаг 7: Формируем контекст (чистый контейнер данных)
        return LessonContext(
            lesson_id=lesson.id,
            lesson_title=lesson.title,
            lesson_type=lesson.skill_focus[0] if lesson.skill_focus else "general",
            course_id=lesson.course.id,
            course_title=lesson.course.title,
            cefr_level=lesson.required_cefr,
            professional_tags=[
                tag.name for tag in await sync_to_async(lesson.course.professional_tags.all)()
            ],
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
            frustration_signals=frustration_signals,
            is_critically_frustrated=is_critically_frustrated,
        )