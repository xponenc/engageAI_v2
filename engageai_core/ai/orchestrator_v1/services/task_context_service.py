from asgiref.sync import sync_to_async
from django.core.exceptions import ObjectDoesNotExist

from ai.orchestrator_v1.context.task_context import TaskContext
from curriculum.models import TaskAssessmentResult
from curriculum.models.content.task import Task
from curriculum.models.student.enrollment import Enrollment


class TaskContextService:
    """
    TaskContextService — сервис формирования контекста задачи (TaskContext)
    для AI-оркестратора.

    Версия: baseline v1 (без истории попыток)

    Архитектурные инварианты:
    -------------------------
    1. Task всегда принадлежит Lesson, а Lesson — Course.
    2. Для пары (student, course) существует не более одного активного Enrollment.
    3. В рамках одного Enrollment и одной Task может существовать
       не более одного TaskAssessmentResult.
    4. История попыток (retries) НЕ поддерживается.
       attempts_count ∈ {0, 1}.
    """

    @classmethod
    async def get_context(cls, task_id: int, user_id: int) -> TaskContext:
        """
        Единственная точка входа для получения контекста задачи.

        Алгоритм:
        ----------
        1. Загружаем задачу вместе с Lesson и Course.
        2. Пытаемся найти активный Enrollment студента на курс задачи.
        3. Если Enrollment найден — получаем финальный результат оценки задачи.
        4. Определяем состояние задачи (NOT_STARTED / COMPLETED / FAILED).
        5. Собираем справочные данные (теги, цели обучения).
        6. Формируем неизменяемый TaskContext.

        Ограничения версии:
        -------------------
        - Одна задача → один результат оценки.
        - attempts_count зарезервирован под будущую поддержку retries.
        """

        # ---------------------------------------------------------------------
        # 1. Task → Lesson → Course
        # ---------------------------------------------------------------------
        # Загружаем задачу и связанные сущности одним SQL-запросом.
        task = await Task.objects.select_related(
            "lesson",
            "lesson__course",
        ).aget(id=task_id)

        lesson = task.lesson
        course = lesson.course

        # ---------------------------------------------------------------------
        # 2. Enrollment
        # ---------------------------------------------------------------------
        # Ищем активное зачисление студента на курс задачи.
        # По модели данных гарантировано:
        #   - либо 0,
        #   - либо ровно 1 активный Enrollment.
        try:
            enrollment = await Enrollment.objects.select_related(
                "student",
                "student__user",
                "course",
            ).aget(
                student__user_id=user_id,
                course=course,
                is_active=True,
            )
        except Enrollment.DoesNotExist:
            enrollment = None

        # ---------------------------------------------------------------------
        # 3. Результат оценки задачи
        # ---------------------------------------------------------------------
        # В baseline v1 допускается не более одного TaskAssessmentResult
        # на (enrollment, task).
        task_assessment = None

        is_completed = False
        is_correct = None
        score = None
        attempts_count = 0  # зарезервировано под будущие retries
        last_feedback = None

        if enrollment:
            task_assessment = await TaskAssessmentResult.objects.filter(
                enrollment=enrollment,
                task=task,
            ).afirst()

        if task_assessment:
            is_completed = True
            is_correct = task_assessment.is_correct
            score = task_assessment.score

            # В v1 feedback считается финальным
            last_feedback = task_assessment.feedback or ""


        # ---------------------------------------------------------------------
        # 4. Состояние задачи
        # ---------------------------------------------------------------------
        # В baseline v1 возможны только следующие состояния:
        # - NOT_STARTED  — результата нет
        # - COMPLETED    — результат есть и is_correct=True
        # - FAILED       — результат есть и is_correct=False
        if is_completed:
            task_state = "COMPLETED" if is_correct else "FAILED"
        elif attempts_count > 0:
            # Зарезервировано под будущую модель попыток
            task_state = "IN_PROGRESS"
        else:
            task_state = "NOT_STARTED"

        # ---------------------------------------------------------------------
        # 5. Профессиональные теги курса
        # ---------------------------------------------------------------------
        # M2M данные загружаются отдельным запросом.
        professional_tags = await sync_to_async(
            lambda: list(
                course.professional_tags.values_list("name", flat=True)
            )
        )()

        professional_context = (
            ", ".join(professional_tags)
            if professional_tags
            else "general professional context"
        )

        # ---------------------------------------------------------------------
        # 6. Цели обучения задачи
        # ---------------------------------------------------------------------
        learning_objectives = await sync_to_async(
            lambda: list(
                task.lesson.learning_objectives.values_list("name", flat=True)
            )
        )()

        # ---------------------------------------------------------------------
        # 7. Ошибки и рекомендации (structured_feedback)
        # ---------------------------------------------------------------------
        common_errors = []
        improvement_suggestions = []

        if task_assessment and getattr(task_assessment, "structured_feedback", None):
            structured_feedback = task_assessment.structured_feedback or {}

            errors = structured_feedback.get("errors", [])
            if isinstance(errors, list):
                common_errors = errors
            elif isinstance(errors, dict):
                common_errors = list(errors.keys())

            suggestions = structured_feedback.get("suggestions", [])
            if isinstance(suggestions, list):
                improvement_suggestions = suggestions

        # ---------------------------------------------------------------------
        # 8. Формирование TaskContext
        # ---------------------------------------------------------------------
        # TaskContext является чистым контейнером данных
        # и не содержит бизнес-логики.
        return TaskContext(
            # --- Task ---
            task_id=task.id,
            task_title=f"Task #{task.order}",
            task_type=task.task_type,
            response_format=task.response_format,
            difficulty_cefr=task.difficulty_cefr,

            # --- Lesson / Course ---
            lesson_id=lesson.id,
            lesson_title=lesson.title,
            lesson_type=lesson.skill_focus[0] if lesson.skill_focus else "general",
            course_id=course.id,
            course_title=course.title,
            lesson_cefr_level=lesson.required_cefr,
            lesson_professional_tags=professional_tags,
            lesson_skill_focus=lesson.skill_focus or [],

            # --- State ---
            task_state=task_state,
            is_completed=is_completed,
            is_correct=is_correct,
            score=score,
            attempts_count=attempts_count,

            # --- Feedback ---
            last_feedback=last_feedback,
            common_errors=common_errors,
            improvement_suggestions=improvement_suggestions,

            # --- AI Context ---
            content_schema=task.content_schema_version,
            professional_context=professional_context,
            learning_objectives=learning_objectives,

            # --- Metadata ---
            metadata={
                "task_order": task.order,
                "is_diagnostic": task.is_diagnostic,
                "has_media": await sync_to_async(
                    lambda: task.media_files.exists() if hasattr(task, "media_files") else False
                )(),
            },
        )
