import io
import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.mixins import PermissionRequiredMixin, UserPassesTestMixin, LoginRequiredMixin
from django.contrib.auth.models import Group, User
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.base import ContentFile, File
from django.core.files.images import get_image_dimensions
from django.core.mail import send_mail
from django.db.models import Count
from django.http import HttpResponseRedirect, JsonResponse, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render, redirect
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.views import View, generic
from PIL import Image
from django.views.generic import FormView, DetailView

from chat.views import ChatContextMixin
from .forms import UserRegistrationForm, UserProfileForm, UserProfileUpdateForm, FeedbackForm
from .models import Profile
from .services.emails import send_activation_email
from .services.telegram import generate_invite


class UserLogin(LoginView):
    """Авторизация пользователя"""
    template_name = "users/login.html"


class UserLogout(LogoutView):
    """Выход пользователя из системы"""
    template_name = "users/logout.html"
    success_url = reverse_lazy("index")


class UserRegistration(FormView):
    """Регистрация пользователя"""

    template_name = "users/registration.html"
    form_class = UserRegistrationForm
    success_url = reverse_lazy("users:check_email")

    def form_valid(self, form):
        user = form.save()
        user.is_active = False
        user.save()

        # 1) uid
        uid = urlsafe_base64_encode(force_bytes(user.pk))

        # 2) token
        token = default_token_generator.make_token(user)

        # 3) генерируем ссылку подтверждения
        activation_link = self.request.build_absolute_uri(
            reverse_lazy("users:activate", kwargs={"uidb64": uid, "token": token})
        )

        # 4) отправляем письмо
        send_mail(
            subject="EngageAI Подтвердите ваш email",
            message=f"Для активации аккаунта перейдите по ссылке:\n{activation_link}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )

        return super().form_valid(form)


class ActivateUserView(View):
    """Активация через ссылку в письме"""

    def get(self, request, uidb64, token):
        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            user = User.objects.get(pk=uid)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            user = None

        if user and default_token_generator.check_token(user, token):
            user.is_active = True
            user.save()
            login(request, user)
            return redirect("users:profile-update", pk=user.pk)
        else:
            return redirect("users:activation_invalid")


class ResendActivationEmailView(View):
    """Повторная отправка письма активации"""

    def post(self, request):
        email = request.POST.get("email")

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return redirect("users:check_email")  # чтобы не палить существование email

        if user.is_active:
            return redirect("users:profile-update", pk=user.pk)

        # отправляем новое письмо
        send_activation_email(self, user)

        return redirect("users:check_email")

    #
    # @classmethod
    # def get(cls, request):
    #     user_form = UserRegistrationForm()
    #     profile_form = UserProfileForm()
    #     context = {
    #         'forms': [user_form, profile_form]
    #     }
    #     return render(request, 'users/registration.html', context=context)

    # @classmethod
    # def post(cls, request):
    #     user_form = UserRegistrationForm(request.POST)
    #     profile_form = UserProfileForm(request.POST, request.FILES)
    #     if user_form.is_valid() and profile_form.is_valid():
    #         user = user_form.save()
    #         try:
    #             default_group = Group.objects.get(name='Обычный пользователь')
    #         except Group.DoesNotExist:
    #             user_form.add_error('username', 'Ошибка базы -  группы Обычный пользователь не существует')
    #             forms = [user_form, profile_form]
    #             return render(request, 'users/registration.html', {'forms': forms})
    #         if default_group:
    #             user.groups.add(default_group)
    #         profile = profile_form.save(commit=False)
    #         profile.user = user
    #         image = profile_form.cleaned_data.get('avatar')
    #         if image:
    #             file = avatar_resize(image)
    #             profile.avatar.save(file.name, file)
    #         profile.save()
    #
    #         username = user_form.cleaned_data.get('username')
    #         password = user_form.cleaned_data.get('password1')
    #         user = authenticate(username=username, password=password)
    #         login(request, user)
    #         messages.success(request, 'Ваш аккаунт успешно создан. Добро пожаловать.')
    #         return redirect(reverse_lazy('users:profile', kwargs={'pk': user.id}))
    #     forms = [user_form, profile_form]
    #     return render(request, 'users/registration.html', {'forms': forms})


def avatar_resize(image):
    """Изменение размеров файла аватара"""
    img_width, img_height = get_image_dimensions(image)
    image_data = Image.open(image)

    if img_height > 100:  # Уменьшаем размер, если высота больше 100px
        new_img_height = 100
        new_img_width = int(new_img_height * img_width / img_height)
        image_data = image_data.resize((new_img_width, new_img_height), Image.LANCZOS)

    output = io.BytesIO()
    image_data.save(output, format="JPEG", optimize=True, quality=75)
    output.seek(0)

    content_file = ContentFile(output.read())  # Создаём файл в памяти
    output.close()

    return File(content_file)


class UserProfileView(LoginRequiredMixin, ChatContextMixin, DetailView):
    """Просмотр профиля пользователя"""
    model = User
    template_name = "users/profile.html"
    queryset = User.objects.select_related("profile", "student")

    def dispatch(self, request, *args, **kwargs):
        user = self.get_object()
        if not hasattr(user, 'profile') or user.profile is None:
            return redirect(reverse_lazy("users:profile-create", kwargs={"pk": request.user.id}))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.get_chat_context(request=self.request))
        user = self.object
        profile = getattr(user, "telegram_profile", None)

        if not profile or not profile.telegram_id:
            if not profile:
                # Создаем профиль и генерируем invite
                invite_link, qr_path = generate_invite(user)
            elif not profile.invite_code:
                invite_link, qr_path = generate_invite(user)
            else:
                bot_username = "DPO_Assistant+bot"
                invite_link = f"https://t.me/{bot_username}?start={profile.invite_code}"
                qr_path = os.path.join(settings.MEDIA_ROOT, "users", f"user-id-{user.id}",
                                       f"telegram-invite-{user.pk}.png")

                # Генерируем URL для шаблона
            invite_qr_url = qr_path.replace(settings.MEDIA_ROOT, settings.MEDIA_URL)

            context.update({
                "invite_link": invite_link,
                "invite_qr": invite_qr_url,
            })
        return context


class UserProfileCreateView(LoginRequiredMixin, View):
    """Создание профиля пользователя"""

    def get(self, request, *args, **kwargs):
        user = request.user
        form = UserProfileForm(initial={
            'first_name': user.first_name,
            'last_name': user.last_name,
        })
        return render(request, 'users/profile_update.html', {'form': form})

    def post(self, request, *args, **kwargs):
        form = UserProfileForm(request.POST, request.FILES)
        if form.is_valid():
            # Передаем пользователя в форму при сохранении
            profile = form.save(commit=False)
            profile.user = request.user
            profile.save()

            request.user.first_name = form.cleaned_data.get("first_name")
            request.user.last_name = form.cleaned_data.get("last_name")
            request.user.save(update_fields=["first_name", "last_name"])

            return redirect(profile.get_absolute_url())
        return render(request, 'users/profile_update.html', {'form': form})


class UserProfileUpdateView(LoginRequiredMixin, View):
    """Редактирование профиля пользователя"""

    def get(self, request, *args, **kwargs):
        try:
            profile = request.user.profile
        except ObjectDoesNotExist:
            # перенаправляем на создание профиля
            return redirect(reverse_lazy("users:profile-create", kwargs={"pk": request.user.id}))

        form = UserProfileUpdateForm(instance=profile)
        # print(profile.avatar, profile.avatar.url).
        context = {
            'form': form,
            'profile': profile}
        return render(request, 'users/profile_update.html', context)

    def post(self, request, *args, **kwargs):
        profile_id = kwargs.get('pk')
        profile = Profile.objects.get(id=profile_id)
        if request.user.profile.pk != profile_id:
            return redirect("users:profile-update", pk=request.user.profile.pk)
        form = UserProfileUpdateForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            profile = form.save()
            profile.user.first_name = form.cleaned_data.get('first_name')
            profile.user.last_name = form.cleaned_data.get('last_name')
            profile.user.save(update_fields=['first_name', 'last_name'])
            return redirect(profile.get_absolute_url())
        return render(request, 'users/profile_update.html', {'form': form})


class UserListView(LoginRequiredMixin, generic.ListView):
    """Списковый просмотр пользователей"""
    model = User
    template_name = "users/user_list.html"
    queryset = User.objects.select_related("profile").all()


class UserVerifyView(PermissionRequiredMixin, View):
    """Представление перевода пользователя в группу Верифицированные пользователи"""
    # @permission_required('users.verify')
    permission_required = 'users.verify'

    @classmethod
    def get(cls, request, pk, *args, **kwargs):
        user = User.objects.get(id=pk)
        user_group = Group.objects.get(name='Верифицированный пользователь')
        # user.groups.add(user_group)
        user.groups.set([user_group])

        profile = Profile.objects.get(user=user)
        profile.is_verified = True
        profile.save(update_fields=['is_verified'])

        messages.success(request, f'Пользователь {user.get_full_name()} успешно верифицирован')

        return HttpResponseRedirect(reverse('users:user_list'))


class UserFeedbackView(View):
    """Отправка сообщения обратной связи"""

    def get(self, *args, **kwargs):
        if self.request.user.is_anonymous:
            feedback_form = FeedbackForm()
        else:
            feedback_form = FeedbackForm(initial={
                "name": f"{self.request.user.first_name} {self.request.user.last_name}",
                "email": self.request.user.email
            })
        return render(request=self.request, template_name="users/feedback.html", context={"form": feedback_form})

    def post(self, *args, **kwargs):
        is_ajax = self.request.headers.get('x-requested-with') == 'XMLHttpRequest'
        feedback_form = FeedbackForm(self.request.POST)
        if feedback_form.is_valid():
            print(feedback_form.cleaned_data)
            # Обработка формы
            if is_ajax:
                return JsonResponse(
                    {
                        "message": "Сообщение успешно отправлено",
                        "redirect_url": reverse_lazy("index"),
                    }, status=200)
            return redirect("index")
        if is_ajax:
            csrf_token = get_token(self.request)
            return JsonResponse(
                {
                    "form_html": render_to_string(
                        template_name="widgets/_custom-form.html",
                        context={"form": feedback_form}),
                    "csrf_token": csrf_token,
                },
                status=400)
        return render(request=self.request, template_name="users/feedback.html", context={"form": feedback_form})


class CheckEmailExistView(View):
    """Представление проверки e-mail для регистрации"""

    def get(self, *args, **kwargs):
        is_ajax = self.request.headers.get('x-requested-with') == 'XMLHttpRequest'
        email = self.request.GET.get("email")
        if is_ajax and email:
            # try:
            email_exist = User.objects.filter(email=email).exists()
            if email_exist:
                return JsonResponse({"available": False}, status=200)
            return JsonResponse({"available": True}, status=200)
            # except Exception:
            #     return JsonResponse({}, status=500)
        return HttpResponse(status=404)
