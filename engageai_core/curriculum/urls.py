from django.urls import path
from curriculum.views.course_views import (
    CourseListView, CourseDetailView, enroll_in_course
)
from curriculum.views.learning_session_views import (
    LearningSessionView, submit_task_response, LearningSessionTaskView,
    LessonHistoryView, CourseHistoryView
)


app_name = "curriculum"


urlpatterns = [
    path('', CourseListView.as_view(), name='course_list'),
    path('course/<int:pk>/', CourseDetailView.as_view(), name='course_detail'),
    path('enroll/<int:course_id>/', enroll_in_course, name='enroll_course'),

    # Learning Session views
    path('session/<int:pk>/', LearningSessionView.as_view(), name='learning_session'),
    path('session/<int:enrollment_id>/task/<int:task_id>/', LearningSessionTaskView.as_view(),
         name='learning_session_task'),
    path('session/<int:enrollment_id>/submit/', submit_task_response, name='submit_task_response'),

    # История обучения
    path('session/<int:enrollment_id>/lesson/<int:lesson_id>/history/',
         LessonHistoryView.as_view(), name='lesson_history'),
    path('session/<int:enrollment_id>/history/',
         CourseHistoryView.as_view(), name='course_history'),
]
