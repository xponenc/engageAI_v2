from django.urls import path

from .views.views_telegram import TelegramMessageSaveView, TelegramUpdateSaveView

urlpatterns = [
    path("telegram/update/", TelegramUpdateSaveView.as_view(), name="api_save_tg_update"),
    path("telegram/message/", TelegramMessageSaveView.as_view(), name="api_save_tg-message"),
]
