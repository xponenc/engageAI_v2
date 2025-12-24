import time
from pprint import pprint

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.views.generic import ListView, DetailView
from django.http import JsonResponse
from django.db.models import Prefetch, Exists, OuterRef, Subquery

from curriculum.config.dependency_factory import CurriculumServiceFactory
from curriculum.models.content.course import Course
from curriculum.models.content.lesson import Lesson
from curriculum.models.student.enrollment import Enrollment
from curriculum.services.curriculum_query import CurriculumQueryService
from curriculum.config.dependency_factory import CurriculumServiceFactory


class CourseListView(LoginRequiredMixin, ListView):
    """
    Представление для отображения списка всех курсов с уроками.
    Для аутентифицированных пользователей показывает информацию о зачислении.
    """
    model = Course
    template_name = 'curriculum/course_list.html'
    context_object_name = 'courses'
    paginate_by = 10

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.learning_service = CurriculumServiceFactory().create_learning_service()

    def get_queryset(self):
        # Предзагружаем уроки для каждого курса, отсортированные по порядку
        queryset = Course.objects.filter(is_active=True).prefetch_related(
            Prefetch('lessons',
                     queryset=Lesson.objects.filter(is_active=True).order_by('order'),
                     to_attr='ordered_lessons')
        )

        # Если пользователь аутентифицирован, предзагружаем его enrollment
        if self.request.user.is_authenticated:
            student = getattr(self.request.user, 'student', None)
            if student:
                queryset = queryset.annotate(
                    has_enrollment=Exists(
                        Enrollment.objects.filter(
                            student=student,
                            course=OuterRef('pk'),
                            is_active=True
                        )
                    ),
                    enrollment_id=Subquery(
                        Enrollment.objects.filter(
                            student=student,
                            course=OuterRef('pk'),
                            is_active=True
                        ).values('id')[:1]
                    )
                )

        return queryset.order_by('title')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if hasattr(self.request.user, 'student'):
            student = self.request.user.student
            context['enrollments'] = self.learning_service.enrollment_service.get_student_enrollments(student)

        return context


class CourseDetailView(LoginRequiredMixin, DetailView):
    """
    Детальное представление курса с уроками и информацией о зачислении.
    """
    model = Course
    template_name = 'curriculum/course_detail.html'
    context_object_name = 'course'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        factory = CurriculumServiceFactory()
        self.learning_service = factory.create_learning_service()
        self.enrollment_service = self.learning_service.enrollment_service

    def get_queryset(self):
        return Course.objects.filter(is_active=True).prefetch_related(
            Prefetch('lessons',
                     queryset=Lesson.objects.filter(is_active=True).order_by('order'),
                     to_attr='ordered_lessons')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        course = self.object
        student = getattr(self.request.user, 'student', None)

        # Получаем enrollment для текущего студента и курса
        enrollment = None
        if student:
            try:
                enrollment = Enrollment.objects.get(
                    student=student,
                    course=course,
                    is_active=True
                )
            except Enrollment.DoesNotExist:
                enrollment = None

        context['enrollment'] = enrollment
        context['student'] = student

        if enrollment:
            context['progress_details'] = self.enrollment_service.get_course_progress(enrollment)
            context['current_lesson'] = enrollment.current_lesson

            # Получаем следующее задание
            context['next_task'] = self.learning_service.get_next_task(enrollment.id)
        pprint(context)
        return context


@login_required
def enroll_in_course(request, course_id):
    """
    Обрабатывает запрос на зачисление студента на курс.
    """
    student = getattr(request.user, 'student', None)
    if not student:
        return JsonResponse({'error': 'User is not a student'}, status=400)

    try:
        course = Course.objects.get(id=course_id, is_active=True)
    except Course.DoesNotExist:
        return JsonResponse({'error': 'Course not found or inactive'}, status=404)

    learning_service = CurriculumServiceFactory().create_learning_service()
    enrollment_service = learning_service.enrollment_service

    enrollment = enrollment_service.enroll_student(student=student, course=course)

    return JsonResponse({
        'message': 'Successfully enrolled in course',
        'enrollment_id': enrollment.id,
        'redirect_url': f'/curriculum/course/{course_id}/'
    })


@login_required
def course_list_api(request):
    """
    API endpoint для получения списка курсов в формате JSON.
    Используется для AJAX-запросов и мобильных приложений.
    """
    student = getattr(request.user, 'student', None)

    # Предзагружаем уроки для каждого курса
    courses = Course.objects.filter(is_active=True).prefetch_related(
        Prefetch('lessons',
                 queryset=Lesson.objects.filter(is_active=True).order_by('order'),
                 to_attr='ordered_lessons')
    )

    # Аннотируем информацию о зачислении для аутентифицированных пользователей
    if student:
        courses = courses.annotate(
            has_enrollment=Exists(
                Enrollment.objects.filter(
                    student=student,
                    course=OuterRef('pk'),
                    is_active=True
                )
            ),
            enrollment_id=Subquery(
                Enrollment.objects.filter(
                    student=student,
                    course=OuterRef('pk'),
                    is_active=True
                ).values('id')[:1]
            )
        )

    # Формируем сериализованный ответ
    courses_data = []
    for course in courses.order_by('title'):
        course_data = {
            'id': course.id,
            'title': course.title,
            'description': course.description,
            'target_cefr_from': course.get_target_cefr_from_display(),
            'target_cefr_to': course.get_target_cefr_to_display(),
            'estimated_duration': course.estimated_duration,
            'lessons_count': len(course.ordered_lessons),
            'is_enrolled': getattr(course, 'has_enrollment', False),
            'enrollment_id': getattr(course, 'enrollment_id', None),
            'progress_percent': 0
        }

        # Если есть зачисление, рассчитываем прогресс
        if getattr(course, 'has_enrollment', False) and course.enrollment_id:
            try:
                enrollment = Enrollment.objects.get(id=course.enrollment_id)
                course_data['progress_percent'] = round(
                    (enrollment.current_lesson.order / course.lessons.filter(is_active=True).count()) * 100,
                    1
                ) if enrollment.current_lesson else 0
            except Enrollment.DoesNotExist:
                pass

        courses_data.append(course_data)

    return JsonResponse({'courses': courses_data})
