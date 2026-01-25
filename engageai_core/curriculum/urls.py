from django.urls import path
from .views.course_views import (
    CourseListView, CourseDetailView, EnrollCourseView
)
from .views.learning_session_views import (
    LearningSessionView,
    LessonHistoryView, CourseHistoryView, CheckLessonAssessmentView
)


app_name = "curriculum"


urlpatterns = [
    path('', CourseListView.as_view(), name='course_list'),
    path('course/<int:pk>/', CourseDetailView.as_view(), name='course_detail'),
    path('enroll/<int:course_id>/', EnrollCourseView.as_view(), name='enroll_course'),
    #
    # # Learning Session views
    path('session/<int:pk>/', LearningSessionView.as_view(), name='learning_session'),
    path('session/<int:enrollment_id>/check-assessment/', CheckLessonAssessmentView.as_view(),
         name='check_lesson_assessment'),
    #
    # # История обучения
    path('session/<int:enrollment_id>/history/', CourseHistoryView.as_view(), name='course_history'),
    # path('session/<int:enrollment_id>/lesson/<int:lesson_id>/history/', LessonHistoryView.as_view(),
    #      name='lesson_history'),

]
