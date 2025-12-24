from django.urls import path, include


app_name = 'chat-api'

urlpatterns = [
    path("chat/", include("chat.api.urls")),
]
