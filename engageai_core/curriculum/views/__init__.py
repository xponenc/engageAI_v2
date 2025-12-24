from rest_framework import serializers
from curriculum.models.content.course import Course
from curriculum.models.content.lesson import Lesson
from curriculum.models.student.enrollment import Enrollment


class LessonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = ['id', 'title', 'description', 'order', 'duration_minutes', 'required_cefr']


class CourseSerializer(serializers.ModelSerializer):
    lessons = LessonSerializer(many=True, read_only=True)
    progress_percent = serializers.SerializerMethodField()
    is_enrolled = serializers.SerializerMethodField()
    enrollment_id = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = [
            'id', 'title', 'description', 'target_cefr_from', 'target_cefr_to',
            'estimated_duration', 'created_at', 'updated_at', 'is_active',
            'lessons', 'progress_percent', 'is_enrolled', 'enrollment_id'
        ]

    def get_progress_percent(self, obj):
        request = self.context.get('request')
        if request and hasattr(request.user, 'student'):
            student = request.user.student
            try:
                enrollment = Enrollment.objects.get(
                    student=student,
                    course=obj,
                    is_active=True
                )
                if enrollment.current_lesson:
                    total_lessons = obj.lessons.filter(is_active=True).count()
                    if total_lessons > 0:
                        return round((enrollment.current_lesson.order / total_lessons) * 100, 1)
            except Enrollment.DoesNotExist:
                pass
        return 0

    def get_is_enrolled(self, obj):
        request = self.context.get('request')
        if request and hasattr(request.user, 'student'):
            student = request.user.student
            return Enrollment.objects.filter(
                student=student,
                course=obj,
                is_active=True
            ).exists()
        return False

    def get_enrollment_id(self, obj):
        request = self.context.get('request')
        if request and hasattr(request.user, 'student'):
            student = request.user.student
            try:
                enrollment = Enrollment.objects.get(
                    student=student,
                    course=obj,
                    is_active=True
                )
                return enrollment.id
            except Enrollment.DoesNotExist:
                pass
        return None
    