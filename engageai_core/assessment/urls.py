from django.urls import path, include

from .views import StartAssessmentView, QuestionView, FinishView

app_name = "assessment"

urlpatterns = [
    path("start/", StartAssessmentView.as_view(), name="start_test"),
    path("session/<uuid:session_id>/question/", QuestionView.as_view(), name="question_view"),
    path("session/<uuid:session_id>/finish/", FinishView.as_view(), name="finish_view"),
]
