from django.urls import path, include

app_name = "assessment-api"

# API-версия
urlpatterns = [
    path("", include("assessment.api.urls")),
]