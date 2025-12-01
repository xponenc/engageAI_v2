from django.urls import path

from .views import TelegramUpdateSaveView

urlpatterns = [
    path("telegram/updates/", TelegramUpdateSaveView.as_view(), name="api_save_tg_update"),
]
