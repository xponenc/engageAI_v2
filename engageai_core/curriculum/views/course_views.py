import logging
from pprint import pprint

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import ListView, DetailView, CreateView
from django.http import JsonResponse
from django.db.models import Prefetch, Exists, OuterRef, Subquery, Q, Sum, Count

from chat.views import ChatContextMixin
from curriculum.models.content.course import Course
from curriculum.models.content.lesson import Lesson
# from curriculum.models.learning_process.lesson_event_service import LessonEventService
from curriculum.models.student.enrollment import Enrollment
# from curriculum.config.dependency_factory import CurriculumServiceFactory

from curriculum.models.student.skill_snapshot import SkillSnapshot
from curriculum.services.learning_path_initialization import LearningPathInitializationService
from curriculum.services.lesson_event_service import LessonEventService
from curriculum.services.path_generation_service import PathGenerationService


logger = logging.getLogger(__file__)

class CourseListView(LoginRequiredMixin, ChatContextMixin, ListView):
    """
    Представление для отображения списка всех курсов с уроками.
    Для аутентифицированных пользователей показывает информацию о зачислении.
    """
    model = Course
    template_name = 'curriculum/course_list.html'
    context_object_name = 'courses'
    queryset = Course.objects.filter(is_active=True).order_by('title')
    paginate_by = 10

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(is_active=True).annotate(
                lesson_counter=Count(
                    "lessons",
                    filter=Q(lessons__is_active=True),
                    distinct=True,
                ),
                total_duration=Coalesce(
                    Sum(
                        "lessons__duration_minutes",
                        filter=Q(lessons__is_active=True),
                    ),
                    0,
                ),
            )
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

            )

        return queryset

    # def __init__(self, **kwargs):
    #     super().__init__(**kwargs)
    #     # self.learning_service = CurriculumServiceFactory().create_learning_service()
    #
    # def get_queryset(self):
    #     # Предзагружаем уроки для каждого курса, отсортированные по порядку
    #     queryset = Course.objects.filter(is_active=True).prefetch_related(
    #         Prefetch('lessons',
    #                  queryset=Lesson.objects.filter(is_active=True).order_by('order'),
    #                  to_attr='ordered_lessons')
    #     )
    #
    #     # Если пользователь аутентифицирован, предзагружаем его enrollment
    #     if self.request.user.is_authenticated and hasattr(self.request.user, 'student'):
    #         student = self.request.user.student
    #         enrollment_qs = Enrollment.objects.filter(
    #             student=student,
    #             course=OuterRef('pk'),
    #             is_active=True
    #         )
    #
    #         queryset = queryset.annotate(
    #             has_enrollment=Exists(enrollment_qs),
    #             enrollment_id=Subquery(enrollment_qs.values('id')[:1]),
    #             current_lesson_title=Subquery(
    #                 enrollment_qs.values('current_lesson__title')[:1]
    #             ),
    #         )
    #
    #     return queryset.order_by('title')
    #
    # def get_context_data(self, **kwargs):
    #     context = super().get_context_data(**kwargs)
    #     context.update(self.get_chat_context(request=self.request))
    #
    #     if hasattr(self.request.user, 'student'):
    #         student = self.request.user.student
    #         context['enrollments'] = self.learning_service.enrollment_service.get_student_enrollments(student)
    #
    #     return context


class CourseDetailView(LoginRequiredMixin, ChatContextMixin, DetailView):
    """
    Детальное представление курса с уроками и информацией о зачислении.
    """
    model = Course
    template_name = 'curriculum/course_detail.html'
    context_object_name = 'course'

    def get_queryset(self):
        return Course.objects.filter(is_active=True).prefetch_related(
            Prefetch('lessons',
                     queryset=Lesson.objects.filter(is_active=True).order_by("order"),
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
            # context['progress_details'] = self.enrollment_service.get_course_progress(enrollment)
            context['current_lesson'] = enrollment.current_lesson

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


class EnrollCourseView(LoginRequiredMixin, View):
    """
    Зачисление студента на курс.
    Поддерживает AJAX (JSON) и обычный POST (редирект + messages).
    """

    def post(self, request, course_id):
        student = request.user.student
        course = get_object_or_404(Course, id=course_id, is_active=True)

        # 1. Проверка дубликата зачисления
        if Enrollment.objects.filter(student=student, course=course, is_active=True).exists():
            msg = f"Вы уже зачислены на курс «{course.title}»"
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': msg, 'already_enrolled': True}, status=400)
            messages.warning(request, msg)
            return redirect('curriculum:course_detail', pk=course_id)
        try:
            with transaction.atomic():
                # 2. Создание Enrollment
                enrollment = Enrollment.objects.create(
                    student=student,
                    course=course,
                    is_active=True,
                )

                # 3. Baseline SkillSnapshot (PLACEMENT)
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
                    metadata={
                        "source": "enrollment_baseline",
                        "trigger": "new_course_enrollment"
                    }
                )

                # 4. Генерация персонализированного пути
                learning_path = LearningPathInitializationService.initialize_for_enrollment(
                    enrollment=enrollment
                )

                # 5. Логирование события зачисления
                LessonEventService.create_event(
                    student=student,
                    enrollment=enrollment,
                    lesson=None,
                    event_type="ENROLLMENT_START",
                    channel="WEB",
                    metadata={
                        "course_id": course.id,
                        "course_title": course.title,
                        "nodes_count": len(learning_path.nodes)
                    }
                )
        except Exception as exc:
            logger.exception(
                "Enrollment failed",
                extra={
                    "student_id": student.id,
                    "course_id": course.id
                }
            )

            msg = "Не удалось зачислиться на курс. Пожалуйста, попробуйте ещё раз."

            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"error": msg}, status=500)

            messages.error(request, msg)
            return redirect("curriculum:course_detail", pk=course_id)

        # 6. Формирование ответа
        success_msg = f"Вы успешно зачислены на курс «{course.title}»!"

        if (request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                or request.headers.get("Accept") == "application/json"):
            response_data = {
                'message': success_msg,
                'enrollment_id': enrollment.id,
                'redirect_url': reverse_lazy('curriculum:learning_session', kwargs={'pk': enrollment.id})
            }
            return JsonResponse(response_data)

        # Обычный HTML-ответ
        messages.success(request, success_msg)
        return redirect('curriculum:learning_session', pk=enrollment.id)
