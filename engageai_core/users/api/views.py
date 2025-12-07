from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
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

        telegram_id = request.data.get("telegram_id")
        telegram_username = request.data.get("telegram_username")
        reg_code = request.data.get("registration_code")

        if not telegram_id or not reg_code:
            core_api_logger.warning(f"{bot_tag} Отсутствуют обязательные поля: telegram_id={telegram_id},"
                                    f" reg_code={reg_code}")
            return Response(
                {
                    "success": False,
                    "message": "Необходимые поля не указаны",
                    "detail": f"telegram_id={telegram_id}, reg_code={reg_code}"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Проверяем, зарегистрирован ли уже telegram_id
        try:
            user = User.objects.get(telegram_profile__telegram_id=telegram_id)
            core_api_logger.info(f"{bot_tag} Пользователь уже зарегистрирован: user_id={user.id}")
            return Response(
                {
                    "success": True,
                    "user": user.id,
                    "message": f"{user.first_name}, ты уже зарегистрирован",
                    "detail": "telegram_id уже привязан к пользователю"
                }
            )
        except ObjectDoesNotExist:
            core_api_logger.info(f"{bot_tag} Пользователь с telegram_id={telegram_id} не найден, продолжаем регистрацию")

        # Привязываем telegram к существующему пользователю по registration_code
        try:
            user = (
                User.objects.select_related("telegram_profile")
                .filter(is_active=True)
                .get(telegram_profile__invite_code=reg_code)
            )
            t_profile = user.telegram_profile
            t_profile.telegram_id = telegram_id
            t_profile.username = telegram_username
            t_profile.save()

            core_api_logger.info(f"{bot_tag} Telegram-профиль обновлён: user_id={user.id}, telegram_id={telegram_id}")
            return Response(
                {
                    "success": True,
                    "user_id": user.id,
                    "profile": {
                        "user_first_name": user.first_name,
                        "user_last_name": user.last_name,
                    },
                    "message": "",
                    "detail": f"telegram_id={telegram_id} привязан к user_id={user.id}"
                }
            )
        except ObjectDoesNotExist:
            core_api_logger.error(f"{bot_tag} Invite code не найден: reg_code={reg_code}")
            return Response(
                {
                    "success": False,
                    "message": "Не смог найти ключ, проверь ключ еще раз в личном кабинете",
                    "detail": f"reg_code={reg_code} не найден"
                }
            )


class TelegramGetUserProfileView(BotAuthenticationMixin, APIView):
    """
    Получение профиля пользователя по Telegram ID
    """

    def post(self, request):
        telegram_id = request.data.get("telegram_id")
        bot = getattr(request, "internal_bot", None)
        bot_tag = f"[bot:{bot}]"

        core_api_logger.info(f"{bot_tag} Получен запрос на получение профиля: telegram_id={telegram_id}")

        try:
            user = (
                User.objects.select_related("profile")
                .filter(is_active=True)
                .get(telegram_profile__telegram_id=telegram_id)
            )
            user_id = user.id
            user_first_name = user.first_name
            user_last_name = user.last_name

            core_api_logger.info(
                f"{bot_tag} Профиль найден: user_id={user_id}, name={user_first_name} {user_last_name}"
            )

        except ObjectDoesNotExist:
            user_id = None
            user_first_name = None
            user_last_name = None

            core_api_logger.warning(f"{bot_tag} Профиль не найден для telegram_id={telegram_id}")

        return Response(
            {
                "success": True,
                "user_id": user_id,
                "profile": {
                    "user_first_name": user_first_name,
                    "user_last_name": user_last_name,
                }
            }
        )
