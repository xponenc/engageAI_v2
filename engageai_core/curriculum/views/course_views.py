from pprint import pprint

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import ListView, DetailView, CreateView
from django.http import JsonResponse
from django.db.models import Prefetch, Exists, OuterRef, Subquery

from chat.views import ChatContextMixin
from curriculum.models.content.course import Course
from curriculum.models.content.lesson import Lesson
# from curriculum.models.learning_process.lesson_event_service import LessonEventService
from curriculum.models.student.enrollment import Enrollment
# from curriculum.config.dependency_factory import CurriculumServiceFactory

from curriculum.models.student.skill_snapshot import SkillSnapshot
from curriculum.services.path_generation_service import PathGenerationService


class CourseListView(LoginRequiredMixin, ChatContextMixin, ListView):
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
        # self.learning_service = CurriculumServiceFactory().create_learning_service()

    def get_queryset(self):
        # Предзагружаем уроки для каждого курса, отсортированные по порядку
        queryset = Course.objects.filter(is_active=True).prefetch_related(
            Prefetch('lessons',
                     queryset=Lesson.objects.filter(is_active=True).order_by('order'),
                     to_attr='ordered_lessons')
        )

        # Если пользователь аутентифицирован, предзагружаем его enrollment
        if self.request.user.is_authenticated and hasattr(self.request.user, 'student'):
            student = self.request.user.student
            enrollment_qs = Enrollment.objects.filter(
                student=student,
                course=OuterRef('pk'),
                is_active=True
            )

            queryset = queryset.annotate(
                has_enrollment=Exists(enrollment_qs),
                enrollment_id=Subquery(enrollment_qs.values('id')[:1]),
                current_lesson_title=Subquery(
                    enrollment_qs.values('current_lesson__title')[:1]
                ),
            )

        return queryset.order_by('title')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.get_chat_context(request=self.request))

        if hasattr(self.request.user, 'student'):
            student = self.request.user.student
            context['enrollments'] = self.learning_service.enrollment_service.get_student_enrollments(student)

        return context


class CourseDetailView(LoginRequiredMixin, ChatContextMixin, DetailView):
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
        self.curriculum_query = self.learning_service.curriculum_query

    def get_queryset(self):
        return Course.objects.filter(is_active=True).prefetch_related(
            Prefetch('lessons',
                     queryset=Lesson.objects.filter(is_active=True).order_by('order'),
                     to_attr='ordered_lessons')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.get_chat_context(request=self.request))
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

        pprint(context)
        print(course.learning_objectives.all())

        return context


# @login_required
# def enroll_in_course(request, course_id):
#     """
#     Обрабатывает запрос на зачисление студента на курс.
#     """
#     student = getattr(request.user, 'student', None)
#     if not student:
#         return JsonResponse({'error': 'User is not a student'}, status=400)
#
#     try:
#         course = Course.objects.get(id=course_id, is_active=True)
#     except Course.DoesNotExist:
#         return JsonResponse({'error': 'Course not found or inactive'}, status=404)
#
#     learning_service = CurriculumServiceFactory().create_learning_service()
#     enrollment_service = learning_service.enrollment_service
#
#     enrollment = enrollment_service.enroll_student(student=student, course=course)
#
#     return JsonResponse({
#         'message': 'Successfully enrolled in course',
#         'enrollment_id': enrollment.id,
#         'redirect_url': f'/curriculum/course/{course_id}/'
#     })


class EnrollInCourseView(LoginRequiredMixin, CreateView):
    """
    Class-Based View для зачисления на курс.
    Поддерживает:
    - AJAX (JSON response) — для React и Telegram-бота
    - Обычный POST (редирект + messages) — для fallback веб-форм
    """
    model = Enrollment
    fields = []  # Мы создаём объект вручную, не через форму
    template_name = 'curriculum/enroll_confirm.html'  # Опционально, если нужен GET с подтверждением

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['course'] = get_object_or_404(Course, id=self.kwargs['course_id'], is_active=True)
        return context

    def form_valid(self, form):
        student = self.request.user.student
        course = get_object_or_404(Course, id=self.kwargs['course_id'], is_active=True)

        # 1. Проверка дубликата
        if Enrollment.objects.filter(student=student, course=course, is_active=True).exists():
            if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest' or self.request.content_type == 'application/json':
                return JsonResponse({
                    'error': 'Вы уже зачислены на этот курс',
                    'already_enrolled': True
                }, status=400)

            messages.warning(self.request, f"Вы уже зачислены на курс «{course.title}»")
            return redirect('curriculum:course_detail', pk=course.id)

        # 2. Создание Enrollment
        enrollment = Enrollment.objects.create(
            student=student,
            course=course,
        )

        # 3. Baseline SkillSnapshot
        latest_snapshot = student.skill_snapshots.order_by("-snapshot_at").first()
        baseline_skills = latest_snapshot.skills if latest_snapshot else {
            "grammar": 0.5, "vocabulary": 0.5, "listening": 0.5,
            "reading": 0.5, "writing": 0.5, "speaking": 0.5
        }

        SkillSnapshot.objects.create(
            student=student,
            enrollment=enrollment,
            associated_lesson=None,
            snapshot_context="PLACEMENT",
            skills=baseline_skills,
            metadata={"source": "enrollment_baseline"}
        )

        # 4. Генерация LearningPath
        try:
            learning_path = PathGenerationService.generate_personalized_path(enrollment)
            path_type = learning_path.path_type
        except Exception:
            learning_path = PathGenerationService.generate_linear_fallback(enrollment)
            path_type = "LINEAR (fallback)"

        # 5. Логирование события
        LessonEventService.create_event(
            student=student,
            enrollment=enrollment,
            lesson=None,
            event_type="ENROLLMENT_START",
            channel="WEB" if not self.request.headers.get('X-Requested-With') else "AJAX",
            metadata={
                "course_id": course.id,
                "course_title": course.title,
                "path_type": path_type,
                "nodes_count": len(learning_path.nodes)
            }
        )

        # 6. Формирование ответа
        is_ajax = (
            self.request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
            self.request.content_type == 'application/json'
        )

        if is_ajax:
            response_data = {
                'message': 'Successfully enrolled in course',
                'enrollment_id': enrollment.id,
                'path_type': path_type,
                'first_lesson_id': learning_path.current_node["lesson_id"] if learning_path.current_node else None,
                'redirect_url': reverse_lazy('curriculum:learning_session', kwargs={'pk': enrollment.id})
            }
            return JsonResponse(response_data)

        # Обычный HTML-ответ
        messages.success(
            self.request,
            f"Вы успешно зачислены на курс «{course.title}»! "
            f"Сгенерирован {path_type.lower()} учебный путь. Приятного обучения! 🚀"
        )

        if learning_path.current_node:
            return redirect('curriculum:learning_session', pk=enrollment.id)
        return redirect('curriculum:course_detail', pk=course.id)

    def get_success_url(self):
        # Не используется напрямую — мы редиректим вручную
        return reverse_lazy('curriculum:course_list')
