from django.urls import path

from .views import OrchestratorProcessAPIView

urlpatterns = [
    path('orchestrator/process/', OrchestratorProcessAPIView.as_view(), name='orchestrator-process'),

]
