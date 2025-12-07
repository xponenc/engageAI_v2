from django.urls import path
from .views import StartAssessmentTestAPIView, AnswerAPIView

urlpatterns = [
    path("start/", StartAssessmentTestAPIView.as_view(), name="api-start-assessment-test"),
    path("session/<uuid:session_id>/<uuid:question_id>/answer/", AnswerAPIView.as_view(), name="api-assessment-answer"),
]
