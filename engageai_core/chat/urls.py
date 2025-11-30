from django.urls import path, include
from django.views.generic import TemplateView

app_name = 'chat'

urlpatterns = [

    # DRF API приложения
    path("api/v1/chat/", include("chat.api.urls")),

]