from django.urls import path, include
from rest_framework.routers import DefaultRouter
from curriculum.views.course_views import enroll_in_course, course_list_api
from curriculum.views.api.course_api import CourseViewSet

app_name = "curriculum-api"

# API Router
router = DefaultRouter()
router.register(r'api/courses', CourseViewSet, basename='api-courses')

urlpatterns = [
    path('enroll/<int:course_id>/', enroll_in_course, name='api_enroll_course'),
    path('courses/', course_list_api, name='api_course_list'),

    # Include API router URLs
    path('', include(router.urls)),
]
