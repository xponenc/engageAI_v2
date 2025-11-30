from django.urls import path, include
from django.views.generic import TemplateView

from .views import UserLogin, UserLogout, UserRegistration, UserProfileView, UserListView, \
    UserProfileUpdateView, CheckEmailExistView, UserFeedbackView, UserVerifyView, ActivateUserView, \
    ResendActivationEmailView, UserProfileCreateView

app_name = 'users'

urlpatterns = [
    path('login/', UserLogin.as_view(), name='login'),
    path('logout/', UserLogout.as_view(), name='logout'),
    path('sign-up/', UserRegistration.as_view(), name='sign-up'),
    path("activate/<uidb64>/<token>/", ActivateUserView.as_view(), name="activate"),
    path("check-email/", TemplateView.as_view(template_name="users/check_email.html"), name="check_email"),
    path("activation-invalid/", TemplateView.as_view(template_name="users/activation_invalid.html"),
         name="activation_invalid"),
    path("resend-activation/", ResendActivationEmailView.as_view(), name="resend_activation"),


    path('<int:pk>/profile/', UserProfileView.as_view(), name='profile'),
    path('<int:pk>/profile/create/', UserProfileCreateView.as_view(), name='profile-create'),
    path('<int:pk>/profile/update/', UserProfileUpdateView.as_view(), name='profile-update'),
    path('list/', UserListView.as_view(), name='users'),
    path('<int:pk>/verify/', UserVerifyView.as_view(), name='verify'),
    path('feedback/', UserFeedbackView.as_view(), name='feedback'),
    path('check_email/', CheckEmailExistView.as_view(), name='check-email'),

    # DRF API приложения
    path("api/v1/users/", include("users.api.urls")),

]
