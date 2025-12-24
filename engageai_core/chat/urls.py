from django.urls import path, include

from .views import AiChatView, ChatClearView, AIMessageScoreView, AIConversationHistoryView

app_name = 'chat'

urlpatterns = [
    path("ai/<str:slug>", AiChatView.as_view(), name="ai-chat"),
    path("ai/<str:slug>/history", AIConversationHistoryView.as_view(), name="ai-chat-conversation"),
    path("<int:pk>/clear", ChatClearView.as_view(), name="web-chat-clear"),
    path('ai_message/<int:message_pk>/score', AIMessageScoreView.as_view(), name='ai-message-score'),
]
