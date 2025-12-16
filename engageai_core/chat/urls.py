from django.urls import path, include

from .views import AiChatView, ChatClearView, AIMessageScoreView, AIConversationHistoryView

app_name = 'chat'

urlpatterns = [
    path("chat/ai/<str:slug>", AiChatView.as_view(), name="ai-chat"),
    path("chat/ai/<str:slug>/history", AIConversationHistoryView.as_view(), name="ai-chat-conversation"),
    path("chat/<int:pk>/clear", ChatClearView.as_view(), name="web-chat-clear"),
    path('chat/ai_message/<int:message_pk>/score', AIMessageScoreView.as_view(), name='ai-message-score'),

    # DRF API приложения
    path("api/v1/chat/", include("chat.api.urls")),

]