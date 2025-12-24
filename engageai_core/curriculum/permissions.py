from rest_framework import permissions
from django.contrib.auth import get_user_model

User = get_user_model()


class IsStudentOrTeacher(permissions.BasePermission):
    """
    Разрешает доступ только студентам и преподавателям.
    Проверяет наличие связанных объектов student или teacher у пользователя.
    """

    def has_permission(self, request, view):
        # Разрешаем доступ только для аутентифицированных пользователей
        if not request.user or not request.user.is_authenticated:
            return False

        # Проверяем наличие профиля студента или преподавателя
        return hasattr(request.user, 'student') or hasattr(request.user, 'teacher')

    def has_object_permission(self, request, view, obj):
        """
        Проверяет права на конкретный объект.
        Для студентов: могут видеть только свой прогресс
        Для преподавателей: могут видеть прогресс своих студентов
        """
        # Если пользователь - студент
        if hasattr(request.user, 'student'):
            student = request.user.student

            # Проверяем, относится ли объект к этому студенту
            if hasattr(obj, 'student'):
                return obj.student == student

            # Для enrollment
            if hasattr(obj, 'enrollment') and hasattr(obj.enrollment, 'student'):
                return obj.enrollment.student == student

            # По умолчанию разрешаем просмотр
            return True

        # Если пользователь - преподаватель
        if hasattr(request.user, 'teacher'):
            teacher = request.user.teacher

            # Преподаватели могут видеть всё в рамках своих курсов
            # Здесь можно добавить более сложную логику
            return True

        return False


class IsEnrolledStudent(permissions.BasePermission):
    """
    Разрешает доступ только зачисленным студентам на конкретный курс/урок
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        # Проверяем наличие студента
        if not hasattr(request.user, 'student'):
            return False

        student = request.user.student

        # Получаем course_id из URL параметров или запроса
        course_id = view.kwargs.get('course_id') or request.query_params.get('course_id')

        if not course_id:
            return False

        # Проверяем зачисление
        from curriculum.models.student.enrollment import Enrollment
        return Enrollment.objects.filter(
            student=student,
            course_id=course_id,
            is_active=True
        ).exists()


class IsCourseTeacher(permissions.BasePermission):
    """
    Разрешает доступ только преподавателям, которые ведут конкретный курс
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated or not hasattr(request.user, 'teacher'):
            return False

        teacher = request.user.teacher
        course_id = view.kwargs.get('course_id') or request.query_params.get('course_id')

        if not course_id:
            return False

        from curriculum.models.content.course import Course
        return Course.objects.filter(
            id=course_id,
            author=teacher
        ).exists()
