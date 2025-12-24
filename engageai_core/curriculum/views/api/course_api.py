from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from curriculum.models.content.course import Course
from curriculum.models.student.enrollment import Enrollment
from curriculum.permissions import IsStudentOrTeacher

from curriculum.views import CourseSerializer


class CourseViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint для работы с курсами.
    """
    queryset = Course.objects.filter(is_active=True)
    serializer_class = CourseSerializer
    permission_classes = [permissions.IsAuthenticated, IsStudentOrTeacher]

    def get_queryset(self):
        queryset = super().get_queryset()
        # Предзагружаем уроки для каждого курса
        return queryset.prefetch_related(
            'lessons'
        ).order_by('title')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    @action(detail=True, methods=['post'])
    def enroll(self, request, pk=None):
        """
        Зачисление студента на курс
        """
        course = self.get_object()
        student = request.user.student

        # Проверяем, не зачислен ли уже студент на этот курс
        existing_enrollment = Enrollment.objects.filter(
            student=student,
            course=course,
            is_active=True
        ).first()

        if existing_enrollment:
            return Response({
                'message': 'You are already enrolled in this course',
                'enrollment_id': existing_enrollment.id
            }, status=status.HTTP_200_OK)

        # Создаем новое зачисление
        enrollment = Enrollment.objects.create(
            student=student,
            course=course,
            current_lesson=course.lessons.filter(is_active=True).order_by('order').first()
        )

        return Response({
            'message': 'Successfully enrolled in course',
            'enrollment_id': enrollment.id
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def progress(self, request, pk=None):
        """
        Получение информации о прогрессе студента в курсе
        """
        course = self.get_object()
        student = request.user.student

        try:
            enrollment = Enrollment.objects.get(
                student=student,
                course=course,
                is_active=True
            )

            total_lessons = course.lessons.filter(is_active=True).count()
            completed_lessons = 0

            if enrollment.current_lesson:
                completed_lessons = enrollment.current_lesson.order - 1

            progress_percent = round((completed_lessons / total_lessons) * 100, 1) if total_lessons > 0 else 0

            return Response({
                'enrollment_id': enrollment.id,
                'current_lesson': {
                    'id': enrollment.current_lesson.id if enrollment.current_lesson else None,
                    'title': enrollment.current_lesson.title if enrollment.current_lesson else None,
                    'order': enrollment.current_lesson.order if enrollment.current_lesson else None
                },
                'progress_percent': progress_percent,
                'completed_lessons': completed_lessons,
                'total_lessons': total_lessons
            })
        except Enrollment.DoesNotExist:
            return Response({
                'message': 'Not enrolled in this course'
            }, status=status.HTTP_404_NOT_FOUND)