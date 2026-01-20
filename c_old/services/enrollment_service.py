from django.db import transaction
from django.utils import timezone

from curriculum.models.student.enrollment import Enrollment
from curriculum.models.content.course import Course
from curriculum.services.curriculum_query import CurriculumQueryService
from users.models import Student


class EnrollmentService:
    """
    Service для управления зачислением студентов на курсы.
    """

    def __init__(self, curriculum_query: CurriculumQueryService):
        self.curriculum_query = curriculum_query

    def enroll_student(self, student: Student, course: Course) -> Enrollment:
        """
        Зачисляет студента на курс.

        Args:
            student: Студент для зачисления
            course: Курс, на который нужно зачислить студента

        Returns:
            Enrollment: Объект зачисления

        Raises:
            ValueError: Если курс не имеет активных уроков
        """
        # Проверяем, не зачислен ли уже студент на этот курс
        existing_enrollment = Enrollment.objects.filter(
            student=student,
            course=course,
            is_active=True
        ).first()

        if existing_enrollment:
            return existing_enrollment

        # Создаем новое зачисление
        enrollment = Enrollment(
            student=student,
            course=course,
        )

        first_lesson = self.curriculum_query.get_current_lesson(enrollment)

        if not first_lesson:
            raise ValueError(f"Course {course.pk} has no active lessons")

        enrollment.current_lesson = first_lesson
        enrollment.save()

        return enrollment

    @transaction.atomic
    def complete_course(self, enrollment: Enrollment) -> Enrollment:
        """
        Завершает курс для студента.

        Args:
            enrollment: Объект зачисления для завершения

        Returns:
            Enrollment: Обновленный объект зачисления
        """
        enrollment.is_active = False
        enrollment.completed_at = timezone.now()  # Добавляем время завершения
        enrollment.save(update_fields=['is_active', 'completed_at'])
        return enrollment

    def get_student_enrollments(self, student: Student) -> list[Enrollment]:
        """
        Возвращает все активные зачисления студента.

        Args:
            student: Студент

        Returns:
            list[Enrollment]: Список активных зачислений
        """
        return Enrollment.objects.filter(
            student=student,
            is_active=True
        ).select_related(
            'course',
            'current_lesson',
            'current_lesson__course'
        ).prefetch_related(
            'current_lesson__tasks'
        ).order_by('course__target_cefr_from')

    # def calculate_progress(self, enrollment: Enrollment) -> float:
    #     """
    #     Рассчитывает процент прогресса студента в курсе.
    #
    #     Args:
    #         enrollment: Объект зачисления
    #
    #     Returns:
    #         float: Процент прогресса (0.0 - 100.0)
    #     """
    #     if not enrollment.current_lesson:
    #         return 0.0
    #
    #     # Получаем общее количество активных уроков в курсе
    #     total_lessons = enrollment.course.lessons.filter(is_active=True).count()
    #     if not total_lessons:
    #         return 0.0
    #
    #     # Рассчитываем прогресс на основе порядка текущего урока
    #     current_lesson_order = enrollment.current_lesson.order
    #     return (current_lesson_order / total_lessons) * 100.0

    def get_course_progress(self, enrollment: Enrollment) -> dict:
        """
        Возвращает детальную информацию о прогрессе в курсе.

        Корректная семантика:
        - completed_lessons: количество ПОЛНОСТЬЮ ЗАВЕРШЕННЫХ уроков
        - current_lesson: текущий активный урок (может быть не завершен)
        - progress_percent: процент завершенных уроков

        Пример:
        - 5 уроков в курсе
        - Студент на уроке 3
        - completed_lessons = 2 (уроки 1 и 2 завершены)
        - progress_percent = 40% (2/5)
        """
        # Получаем все активные уроки курса
        active_lessons = enrollment.course.lessons.filter(is_active=True).order_by('order')
        total_lessons = active_lessons.count()

        if not total_lessons:
            return {
                'progress_percent': 0,
                'completed_lessons': 0,
                'total_lessons': 0,
                'current_lesson': None,
                'next_lesson': None,
                'is_course_completed': False
            }

        current_lesson = enrollment.current_lesson

        # Рассчитываем завершенные уроки
        completed_lessons = 0
        if current_lesson:
            # Все уроки с order < текущего считаются завершенными
            completed_lessons = active_lessons.filter(order__lt=current_lesson.order).count()

        # Рассчитываем прогресс (только завершенные уроки)
        progress_percent = (completed_lessons / total_lessons) * 100 if total_lessons > 0 else 0

        # Определяем следующий урок (только если текущий завершен)
        next_lesson = None
        is_course_completed = False

        if current_lesson:
            # Проверяем, завершен ли текущий урок
            # (в реальной системе здесь должна быть логика проверки завершенности урока)
            current_lesson_completed = self._is_lesson_completed(enrollment, current_lesson)

            if current_lesson_completed:
                # Ищем следующий урок
                next_lesson = active_lessons.filter(order__gt=current_lesson.order).first()
                if not next_lesson:
                    is_course_completed = True
        else:
            # Если нет текущего урока, начинаем с первого
            next_lesson = active_lessons.first()
        return {
            'progress_percent': int(progress_percent),
            'completed_lessons': completed_lessons,
            'total_lessons': total_lessons,
            'current_lesson': current_lesson,
            'next_lesson': next_lesson,
            'is_course_completed': is_course_completed,
            'all_lessons_completed': completed_lessons == total_lessons
        }

    def _is_lesson_completed(self, enrollment: Enrollment, lesson) -> bool:
        """
        Проверяет, завершен ли урок для данного зачисления.

        В реальной системе здесь должна быть логика:
        - Проверка завершения всех заданий в уроке
        - Проверка достижения минимального score
        - Проверка прохождения всех required заданий

        Для MVP возвращаем False, чтобы не усложнять логику.
        """
        # TODO: Реализовать реальную проверку завершенности урока
        return False
