from django.urls import path, include

app_name = 'assistant'

urlpatterns = [

    # DRF API приложения
    path("api/v1/ai/", include("ai_assistant.api.urls")),

]