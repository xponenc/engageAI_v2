from django.urls import path, include

from .views import ChatView, ChatClearView, MessageScoreView

app_name = 'chat'

urlpatterns = [
    path("main/", ChatView.as_view(), name="web-chat"),
    path("<int:pk>/clear", ChatClearView.as_view(), name="web-chat-clear"),
    path('message/<int:message_pk>/score', MessageScoreView.as_view(), name='message_score'),



    # DRF API приложения
    path("api/v1/chat/", include("chat.api.urls")),

]