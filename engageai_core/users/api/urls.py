from django.urls import path
from .views import TelegramRegistrationView, TelegramGetUserProfileView

urlpatterns = [
    path("register_tg/", TelegramRegistrationView.as_view(), name="api_register_tg"),
    path("profile/", TelegramGetUserProfileView.as_view(), name="api_get_profile"),
]
