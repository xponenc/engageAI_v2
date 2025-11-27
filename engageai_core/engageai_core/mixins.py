from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.response import Response
from django.conf import settings

from utils.setup_logger import setup_logger

core_api_logger = setup_logger(name=__file__, log_dir="logs/core_api", log_file="core_api.log")


class InternalBotAuthMixin:
    """Mixin для проверки доступа внутренних ботов через X-Internal-Key."""

    def dispatch(self, request, *args, **kwargs):
        key = request.headers.get("X-Internal-Key")
        ip = request.META.get("REMOTE_ADDR")

        if not key:
            core_api_logger.warning(
                f"[BOT AUTH] Missing X-Internal-Key | IP={ip} | PATH={request.path}"
            )
            return Response({"detail": "Missing bot key"}, status=401)

        bot_id = None

        if key not in set(settings.INTERNAL_BOTS.values()):
            core_api_logger.error(
                f"[BOT AUTH] Invalid X-Internal-Key attempt | KEY={key} | IP={ip} | PATH={request.path}"
            )
            return Response({"detail": "Invalid bot key"}, status=403)

        for name, data in settings.INTERNAL_BOTS.items():
            if isinstance(data, dict) and data.get("key") == key:
                bot_id = name
                break
            elif data == key:
                bot_id = name
                break
        if not bot_id:
            core_api_logger.error(
                f"[BOT AUTH] Key exists in config but bot_id unresolved | KEY={key} | IP={ip}"
            )
            return Response({"detail": "Invalid bot configuration"}, status=403)

        request.internal_bot = bot_id

        return super().dispatch(request, *args, **kwargs)


class TelegramUserMixin:
    """
    Mixin для извлечения пользователя по telegram_id.
    Требует, чтобы InternalBotAuthMixin уже выполнился и добавил request.internal_bot.
    """

    def get_telegram_user(self, request):
        telegram_id = request.data.get("telegram_id") or request.query_params.get("telegram_id")
        bot = getattr(request, "internal_bot", None)
        bot_tag = f"[bot:{bot}]"

        if not telegram_id:
            core_api_logger.warning(f"{bot_tag} Missing telegram_id в запросе {request.path}")
            return Response({"detail": "telegram_id is required"}, status=400)

        try:
            user = (
                User.objects.select_related("profile")
                .get(telegram_profile__telegram_id=telegram_id, is_active=True)
            )

            core_api_logger.info(
                f"{bot_tag} Профиль найден: user_id={user.id}, "
                f"name={user.first_name} {user.last_name} | telegram_id={telegram_id}"
            )

            request.tg_user = user
            return user

        except ObjectDoesNotExist:
            core_api_logger.warning(
                f"{bot_tag} Профиль НЕ найден для telegram_id={telegram_id}"
            )
            return Response(
                {"detail": "User with given telegram_id not found"},
                status=404
            )
