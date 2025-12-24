from typing import Optional

from django.db.models import OuterRef, Exists

from curriculum.models import StudentTaskResponse
from curriculum.models.student.enrollment import Enrollment
from curriculum.models.content.lesson import Lesson
from curriculum.models.content.task import Task


class CurriculumQueryService:
    """
    Read-only сервис доступа к учебному контенту.

    Инкапсулирует правила:
    - выбора текущего урока
    - порядка заданий
    - фильтрации неактивного контента

    TODO (CurriculumQueryService):

    1. Поддержка diagnostic lessons
    2. Фильтрация задач по ProfessionalTag (через weighting, не exclude)
    3. Поддержка branching curriculum
    4. Предзагрузка related (performance)
    """

    # ------------------------------------------------------------------
    # LESSON
    # ------------------------------------------------------------------

    def get_current_lesson(self, enrollment: Enrollment) -> Lesson:
        """
        Возвращает текущий урок для enrollment.

        Если текущий урок не установлен — выбирается первый доступный.
        """

        if enrollment.current_lesson:
            return enrollment.current_lesson

        first_lesson = (
            Lesson.objects
            .filter(course=enrollment.course, is_active=True)
            .order_by("order")
            .first()
        )

        return first_lesson

    # TASKS

    def get_next_task(self, enrollment: Enrollment) -> Optional[Task]:
        """
        Возвращает следующее невыполненное задание
        для студента в текущем уроке.
        """
        if not enrollment.current_lesson:
            return None

        student_responses = StudentTaskResponse.objects.filter(
            student=enrollment.student,
            task=OuterRef('pk'),
        )

        return (
            Task.objects
            .filter(
                lesson=enrollment.current_lesson,
                is_active=True,
            )
            .annotate(
                has_response=Exists(student_responses)
            )
            .filter(has_response=False)
            .order_by('order')
            .first()
        )

    def get_lesson_history(self, enrollment: Enrollment, lesson: Lesson) -> list:
        """
        Возвращает историю ответов студента по уроку.

        Возвращает список словарей с информацией о каждом задании и ответе:
        {
            'task': Task,
            'response': StudentTaskResponse,
            'assessment': Assessment,
            'is_completed': bool,
            'score': float,
            'feedback': str
        }
        """
        # Получаем все задания урока
        tasks = list(Task.objects.filter(lesson=lesson, is_active=True).order_by('order'))

        # Получаем все ответы студента по уроку
        responses = StudentTaskResponse.objects.filter(
            student=enrollment.student,
            task__lesson=lesson
        ).select_related(
            'task', 'assessment'
        ).prefetch_related(
            'assessment__error_tags'
        ).order_by('created_at')

        # Создаем словарь для быстрого поиска ответов по task_id
        responses_by_task = {response.task_id: response for response in responses}

        # Формируем результат
        history = []
        for task in tasks:
            response = responses_by_task.get(task.id)
            assessment = response.assessment if response else None

            history.append({
                'task': task,
                'response': response,
                'assessment': assessment,
                'is_completed': response is not None,
                'score': assessment.score if assessment else None,
                'feedback': assessment.feedback.get('message', '') if assessment and assessment.feedback else '',
                'created_at': response.created_at if response else None
            })

        return history

    def get_completed_lessons(self, enrollment: Enrollment) -> list:
        """
        Возвращает список пройденных уроков с информацией о прогрессе.

        Возвращает список словарей:
        {
            'lesson': Lesson,
            'completed_tasks': int,
            'total_tasks': int,
            'completion_percent': float,
            'last_response_date': datetime
        }
        """
        if not enrollment.current_lesson:
            return []

        # Получаем все уроки курса до текущего
        completed_lessons = Lesson.objects.filter(
            course=enrollment.course,
            is_active=True,
            order__lt=enrollment.current_lesson.order
        ).order_by('order').prefetch_related('tasks')

        result = []
        for lesson in completed_lessons:
            # Считаем общее количество заданий в уроке
            total_tasks = lesson.tasks.filter(is_active=True).count()

            # Считаем количество выполненных заданий
            completed_tasks = StudentTaskResponse.objects.filter(
                student=enrollment.student,
                task__lesson=lesson,
                task__is_active=True
            ).count()

            # Получаем дату последнего ответа
            last_response = StudentTaskResponse.objects.filter(
                student=enrollment.student,
                task__lesson=lesson
            ).order_by('-created_at').first()

            completion_percent = round((completed_tasks / total_tasks) * 100, 1) if total_tasks > 0 else 0

            result.append({
                'lesson': lesson,
                'completed_tasks': completed_tasks,
                'total_tasks': total_tasks,
                'completion_percent': completion_percent,
                'last_response_date': last_response.created_at if last_response else None
            })

        return result
