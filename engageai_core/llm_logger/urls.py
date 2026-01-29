from django.urls import path

from llm_logger.views import LLMAnalyticsView, LLMUserDetailView, LLMCostAnalysisView, LLMLogListView, LLMLogDetailView

app_name = "llm_logger"

urlpatterns = [
    path('logs/', LLMLogListView.as_view(), name='log_list'),
    path('logs/<int:pk>/', LLMLogDetailView.as_view(), name='log_detail'),

    path("analytics/", LLMAnalyticsView.as_view(), name="analytics"),
    path("analytics/user", LLMUserDetailView.as_view(), name="analytics-user"),
    path("analytics/cost", LLMCostAnalysisView.as_view(), name="analytics-cost"),
]