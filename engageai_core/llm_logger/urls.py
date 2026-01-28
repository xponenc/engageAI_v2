from django.urls import path

from llm_logger.views import LLMAnalyticsView

app_name = "llm_logger"

urlpatterns = [
    path("analytics/", LLMAnalyticsView.as_view(), name="analytics"),
]