from django.urls import path

from engageai_core.chat.api.views import TelegramUpdateView

urlpatterns = [
    path("telegram/updates/", TelegramUpdateView.as_view(), name="api_save_tg_update"),
]
