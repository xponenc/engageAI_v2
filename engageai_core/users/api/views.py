from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse_lazy
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from engageai_core.mixins import BotAuthenticationMixin
from utils.setup_logger import setup_logger

core_api_logger = setup_logger(name=__file__, log_dir="logs/core_api", log_file="core_api.log")


class TelegramRegistrationView(BotAuthenticationMixin, APIView):
    """
    Регистрирует пользователя через Telegram и привязывает его к личному кабинету.
    Формат ответа совместим с core_post:
    {
        "success": True|False,
        "user": user_id,
        "message": "текст для пользователя",
        "detail": "технические детали для логов/debug"
    }
    """

    def post(self, request):
        bot = request.internal_bot
        bot_tag = f"[bot:{bot}]"

        core_api_logger.info(f"{bot_tag} Получен запрос на регистрацию: {request.data}")

        telegram_id = request.data.get("user_telegram_id")
        telegram_username = request.data.get("telegram_username")
        telegram_username_first_name = request.data.get("telegram_username_first_name")
        telegram_username_last_name = request.data.get("telegram_username_last_name")
        registration_code = request.data.get("registration_code")

        if not telegram_id or not registration_code:
            core_api_logger.warning(f"{bot_tag} Отсутствуют обязательные поля в запросе: 'telegram_id={telegram_id}' "
                                    f"или 'registration_code={registration_code}'")
            return Response(
                {
                    "detail": f"Необходимые поля 'telegram_id={telegram_id}' или "
                              f"'registration_code={registration_code}' не переданы в запросе",
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        personal_account_url = f"{settings.SITE_URL}"

        # Проверяем, зарегистрирован ли уже telegram_id
        try:
            user = User.objects.get(telegram_profile__telegram_id=telegram_id)
            core_api_logger.info(f"{bot_tag} Пользователь уже зарегистрирован: user_id={user.id}")
            return Response(
                data={
                    "profile": {
                        "core_user_id": user.id,
                        "user_first_name": user.first_name,
                        "user_last_name": user.last_name,
                        "personal_account_url": personal_account_url,
                    },
                },
                status=status.HTTP_200_OK
            )
        except ObjectDoesNotExist:
            core_api_logger.debug(f"{bot_tag} Пользователь с telegram_id={telegram_id} не найден,"
                                  f" продолжаем регистрацию")

        # Привязываем telegram к существующему пользователю по registration_code
        try:
            user = (
                User.objects.select_related("telegram_profile")
                .filter(is_active=True)
                .get(telegram_profile__invite_code=registration_code)
            )
            t_profile = user.telegram_profile
            t_profile.telegram_id = telegram_id
            t_profile.username = telegram_username
            t_profile.save()

            core_api_logger.info(f"{bot_tag} Зарегистрирован telegram аккаунт пользователя {user}(id={user.id}):"
                                 f"\n\ttelegram_id={telegram_id}"
                                 f"\n\ttelegram_username_first_name={telegram_username_first_name}"
                                 f"\n\ttelegram_username_last_name={telegram_username_last_name}"
                                 )

            return Response(
                data={
                    "profile": {
                        "core_user_id": user.id,
                        "user_first_name": user.first_name,
                        "user_last_name": user.last_name,
                        "personal_account_url": personal_account_url,
                    },
                },
                status=status.HTTP_202_ACCEPTED
            )
        except ObjectDoesNotExist:
            core_api_logger.error(f"{bot_tag} При регистрации telegram_id={telegram_id}"
                                  f" Invite code не найден: registration_code={registration_code}")
            return Response(
                data={
                    "detail": "Не найден ключ регистрации registration_code={registration_code}",
                    "personal_account_url": personal_account_url,
                },
                status=status.HTTP_301_MOVED_PERMANENTLY
            )


class TelegramGetUserProfileView(BotAuthenticationMixin, APIView):
    """
    Получение профиля пользователя по Telegram ID
    """

    def post(self, request):
        bot = getattr(request, "internal_bot", None)
        bot_tag = f"[bot:{bot}]"

        user_telegram_id = request.data.get("user_telegram_id")
        telegram_username = request.data.get("telegram_username")
        telegram_username_first_name = request.data.get("telegram_username_first_name")
        telegram_username_last_name = request.data.get("user_telegram_id")

        if not user_telegram_id:
            core_api_logger.warning(f"{bot_tag} Отсутствуют обязательное поле в запросе:"
                                    f" 'telegram_id={user_telegram_id}'")
            return Response(
                {
                    "detail": f"Необходимое поле 'telegram_id={user_telegram_id}' не передано в запросе",
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        core_api_logger.info(f"{bot_tag} Получен запрос на получение профиля: "
                             f"\t\n telegram_username={telegram_username}"
                             f"\t\n telegram_id={user_telegram_id}"
                             f"\t\n telegram_username_first_name={telegram_username_first_name}"
                             f"\t\n telegram_username_last_name={telegram_username_last_name}"
                             )

        try:
            user = (
                User.objects.select_related("profile")
                .filter(is_active=True)
                .get(telegram_profile__telegram_id=user_telegram_id)
            )

            core_api_logger.info(
                f"{bot_tag} Для telegram_id={user_telegram_id} найден: {user}(id {user.id},"
                f" name={user.first_name} {user.last_name}"
            )

            personal_account_url = f"{settings.SITE_URL}{reverse_lazy('users:profile', kwargs={'pk': user.id})}"

            return Response(
                data={
                    "profile": {
                        "core_user_id": user.id,
                        "user_first_name": user.first_name,
                        "user_last_name": user.last_name,
                        "personal_account_url": personal_account_url,
                    },
                },
                status=status.HTTP_202_ACCEPTED
            )

        except ObjectDoesNotExist:
            core_api_logger.warning(f"{bot_tag} Профиль не найден для telegram_id={user_telegram_id}")
            return Response(
                data={
                    "detail": f"{bot_tag} Профиль не найден для telegram_id={user_telegram_id}",
                },
                status=status.HTTP_401_UNAUTHORIZED
            )
