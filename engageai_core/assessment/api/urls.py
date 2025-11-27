from django.urls import path
from .views import StartAssessmentAPI, AnswerAPI

urlpatterns = [
    path("start/", StartAssessmentAPI.as_view(), name="api_start_test"),
    # path("session/<uuid:session_id>/question/", QuestionAPI.as_view(), name="api_question"),
    path("session/<uuid:session_id>/<uuid:question_id>/answer/", AnswerAPI.as_view(), name="api_answer"),
    # path("session/<uuid:session_id>/finish/", FinishAssessmentAPI.as_view(), name="api_finish"),
]
