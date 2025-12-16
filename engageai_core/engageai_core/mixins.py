from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from rest_framework import status
from rest_framework.response import Response
from django.conf import settings

from chat.services.interfaces.exceptions import AuthenticationError, UserNotFoundError
from utils.setup_logger import setup_logger

core_api_logger = setup_logger(name=__file__, log_dir="logs/core_api", log_file="core_api.log")

#
# class BotAuthenticationMixin:
#     """
#     Миксин для аутентификации внутренних ботов через X-Internal-Key.
#
#     Добавляет в request:
#     - internal_bot: имя бота (строка)
#     - bot_config: конфигурация бота из settings.INTERNAL_BOTS
#
#     Возвращает dict 401/403 при неудачной аутентификации.
#     """
#
#     def dispatch(self, request, *args, **kwargs):
#         key = request.headers.get("X-Internal-Key")
#         ip = request.META.get("REMOTE_ADDR")
#         path = request.path
#
#         # Проверка наличия ключа
#         if not key:
#             core_api_logger.warning(
#                 f"[AUTH FAIL] Missing X-Internal-Key | IP={ip} | PATH={path}"
#             )
#             raise AuthenticationError("Missing bot authentication key", status_code=status.HTTP_401_UNAUTHORIZED)
#
#         # Поиск бота по ключу
#         bot_id = None
#         bot_config = None
#
#         for name, config in settings.INTERNAL_BOTS.items():
#             config_key = config.get("key") if isinstance(config, dict) else config
#             if config_key == key:
#                 bot_id = name
#                 bot_config = config if isinstance(config, dict) else {"key": config}
#                 break
#
#         # Обработка ошибок аутентификации
#         if not bot_id:
#             core_api_logger.error(
#                 f"[AUTH FAIL] Invalid key | KEY={key[:4]}... | IP={ip} | PATH={path}"
#             )
#             raise AuthenticationError("Invalid bot authentication key", status_code=status.HTTP_403_FORBIDDEN)
#
#         # Успешная аутентификация
#         request.internal_bot = bot_id
#         request.bot_config = bot_config
#
#         core_api_logger.info(
#             f"[AUTH SUCCESS] Bot {bot_id} authenticated | IP={ip} | PATH={path}"
#         )
#
#         return super().dispatch(request, *args, **kwargs)


class BotAuthenticationMixin:
    """
    Миксин для аутентификации внутренних ботов.
    Поддерживает два метода:
    1. Старый: X-Internal-Key (для совместимости)
    2. Новый: Bearer Token (стандарт)

    Добавляет в request:
    - internal_bot: имя бота (строка)
    - bot_config: конфигурация бота из settings.INTERNAL_BOTS
    - auth_method: "x-internal" или "bearer"

    Возвращает 401/403 при неудачной аутентификации.
    """

    def dispatch(self, request, *args, **kwargs):
        ip = request.META.get("REMOTE_ADDR")
        path = request.path

        # 1. Попытка аутентификации через Bearer Token (приоритет)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split("Bearer ")[1].strip()
            return self._authenticate_bearer(request, token, ip, path, *args, **kwargs)

        # 2. Попытка аутентификации через X-Internal-Key (совместимость)
        key = request.headers.get("X-Internal-Key")
        if key:
            return self._authenticate_x_internal(request, key, ip, path, *args, **kwargs)

        # 3. Оба метода отсутствуют
        core_api_logger.warning(
            f"[AUTH FAIL] Missing authentication headers | IP={ip} | PATH={path}"
        )
        return self._handle_authentication_error(
            "Missing bot authentication headers. Use 'Authorization: Bearer <token>' or 'X-Internal-Key: <key>'",
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    def _authenticate_bearer(self, request, token, ip, path, *args, **kwargs):
        """Аутентификация через Bearer Token"""
        bot_id = None
        bot_config = None

        for name, config in settings.INTERNAL_BOTS.items():
            if isinstance(config, dict):
                bot_token = config.get("token")
                if bot_token == token:
                    bot_id = name
                    bot_config = config
                    break
            elif config == token:  # обратная совместимость
                bot_id = name
                bot_config = {"key": config, "token": config}
                break

        if not bot_id:
            core_api_logger.error(
                f"[AUTH FAIL] Invalid Bearer token | TOKEN={token[:4]}... | IP={ip} | PATH={path}"
            )
            return self._handle_authentication_error(
                "Invalid bot authentication token",
                status_code=status.HTTP_403_FORBIDDEN
            )

        # Успешная аутентификация
        request.internal_bot = bot_id
        request.bot_config = bot_config
        request.auth_method = "bearer"

        core_api_logger.info(
            f"[AUTH SUCCESS] Bot {bot_id} authenticated via Bearer Token | IP={ip} | PATH={path}"
        )
        return super().dispatch(request, *args, **kwargs)

    def _authenticate_x_internal(self, request, key, ip, path, *args, **kwargs):
        """Аутентификация через X-Internal-Key (старый метод)"""
        bot_id = None
        bot_config = None

        for name, config in settings.INTERNAL_BOTS.items():
            config_key = config.get("key") if isinstance(config, dict) else config
            if config_key == key:
                bot_id = name
                bot_config = config if isinstance(config, dict) else {"key": config}
                break

        if not bot_id:
            core_api_logger.error(
                f"[AUTH FAIL] Invalid X-Internal-Key | KEY={key[:4]}... | IP={ip} | PATH={path}"
            )
            return self._handle_authentication_error(
                "Invalid bot authentication key",
                status_code=status.HTTP_403_FORBIDDEN
            )

        # Успешная аутентификация
        request.internal_bot = bot_id
        request.bot_config = bot_config
        request.auth_method = "x-internal"

        core_api_logger.info(
            f"[AUTH SUCCESS] Bot {bot_id} authenticated via X-Internal-Key | IP={ip} | PATH={path}"
        )
        return super().dispatch(request, *args, **kwargs)

    def _handle_authentication_error(self, message, status_code):
        """Унифицированная обработка ошибок аутентификации"""
        return Response(
            {"error": message},
            status=status_code
        )


class TelegramUserResolverMixin:
    """
    Миксин для разрешения пользователя по telegram_id.

    Предварительное условие: BotAuthenticationMixin должен быть применен ранее.

    Добавляет в request:
    - tg_user: объект пользователя, привязанного к telegram_id

    Возвращает 400/404 при отсутствии telegram_id или пользователя соответственно.
    """

    @staticmethod
    def resolve_telegram_user(request):
        """
        Разрешает пользователя по telegram_id из запроса.

        Args:
            request: HTTP-запрос с telegram_id в data или query_params

        Returns:
            User: объект пользователя или Response при ошибке
        """
        bot = getattr(request, "internal_bot", "unknown")
        bot_tag = f"[bot:{bot}]"

        # Извлечение telegram_id из разных частей запроса
        telegram_id = (
                request.data.get("telegram_id") or
                request.query_params.get("telegram_id") or
                request.data.get("user_telegram_id")
        )

        if not telegram_id:
            core_api_logger.warning(f"{bot_tag} Missing telegram_id in request | PATH={request.path}")
            raise UserNotFoundError("Missing 'user_telegram_id' in request", status_code=status.HTTP_400_BAD_REQUEST)

        try:
            # Поиск активного пользователя по telegram_id
            User = get_user_model()
            user = User.objects.select_related("profile", "telegram_profile").get(
                telegram_profile__telegram_id=str(telegram_id),
                is_active=True
            )

            core_api_logger.info(
                f"{bot_tag} User resolved: ID={user.id}, "
                f"name={user.get_full_name()}, telegram_id={telegram_id}"
            )

            request.tg_user = user
            return user

        except ObjectDoesNotExist:
            core_api_logger.warning(
                f"{bot_tag} User NOT found for telegram_id={telegram_id} | PATH={request.path}"
            )
            raise UserNotFoundError(f"No active user found for telegram_id={telegram_id}",
                                    status_code=status.HTTP_404_NOT_FOUND)
