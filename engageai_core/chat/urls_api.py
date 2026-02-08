from django.urls import path, include


app_name = 'chat-api'

urlpatterns = [
    path("", include("chat.api.urls")),
]
