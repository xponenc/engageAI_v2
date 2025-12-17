import yaml
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from chat.services.interfaces.exceptions import ServiceError, AuthenticationError, UserNotFoundError
# from chat.services.telegram_message_service import TelegramMessageService, TelegramUpdateService
from engageai_core.mixins import BotAuthenticationMixin, TelegramUserResolverMixin

from chat.services.interfaces.telegram_message_service import TelegramMessageService
from chat.services.interfaces.telegram_update_service import TelegramUpdateService
from utils.setup_logger import setup_logger

User = get_user_model()

core_api_logger = setup_logger(name=__file__, log_dir="logs/core_api", log_file="core_api.log")

#
# class TelegramUpdateSaveView(BotAuthenticationMixin, TelegramUserResolverMixin, APIView):
#     """
#     Сохраняет апдейты Telegram: message, edited_message, callback_query.
#     Проверяет дубли по external_id и формирует корректные метаданные.
#     Использует обновленный TelegramMessageService для работы с сообщениями.
#     """
#
#     def post(self, request):
#         bot = getattr(request, "internal_bot", "unknown")
#         bot_tag = f"[bot:{bot}]"
#
#         # Разрешение пользователя
#         user_resolve_result = self.resolve_telegram_user(request)
#         if isinstance(user_resolve_result, Response):
#             response = user_resolve_result
#             return response
#
#         user = user_resolve_result
#
#         # core_api_logger.warning(f"TelegramUpdateSaveView\n\nDEBUG UPDATE\\n{request.data.get("update")}")
#
#         update_data = request.data.get("update")
#         assistant_slug = request.data.get("assistant_slug")
#
#         if not update_data:
#             core_api_logger.warning(f"{bot_tag} Отсутствует поле 'update' в запросе")
#             return Response(
#                 {"success": False, "detail": "Missing update data"},
#                 status=status.HTTP_400_BAD_REQUEST
#             )
#
#         service = TelegramUpdateService()
#         result = service.process_update(
#             update_data=update_data,
#             assistant_slug=assistant_slug,
#             user=user,
#             bot_tag=bot_tag
#         )
#         return Response(result["payload"], status=result["response_status"])


class TelegramUpdateSaveView(BotAuthenticationMixin, TelegramUserResolverMixin, APIView):
    """
    Сохраняет апдейты Telegram: message, edited_message, callback_query.
    Проверяет дубли по external_id и формирует корректные метаданные.
    Использует сервисный подход с кастомными исключениями.
    """

    def post(self, request):
        bot = getattr(request, "internal_bot", "unknown")
        bot_tag = f"[bot:{bot}]"

        # Разрешение пользователя
        user_resolve_result = self.resolve_telegram_user(request)
        if isinstance(user_resolve_result, Response):
            return user_resolve_result

        user = user_resolve_result
        assistant_slug = request.data.get("assistant_slug")
        update_data = request.data.get("update")

        if not update_data:
            core_api_logger.warning(f"{bot_tag} Отсутствует поле 'update' в запросе")
            return Response(
                {"detail": "Missing update data"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not assistant_slug:
            core_api_logger.warning(f"{bot_tag} Отсутствует поле 'assistant_slug' в запросе")
            return Response(
                {"detail": "Missing assistant_slug"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            service = TelegramUpdateService()
            result = service.process_update(
                update_data=update_data,
                assistant_slug=assistant_slug,
                user=user,
                bot_tag=bot_tag
            )

            # Если это дубликат, возвращаем соответствующий статус
            if result.get("duplicate"):
                return Response(
                    {"detail": "Update already processed"},
                    status=status.HTTP_200_OK
                )

            return Response(
                data=result,
                status=status.HTTP_201_CREATED
            )

        except ServiceError as e:
            core_api_logger.error(f"{bot_tag} Ошибка обработки апдейта: {str(e)}")
            return Response(
                {"detail": str(e)},
                status=e.status_code
            )
        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Необработанная ошибка: {str(e)}")
            return Response(
                {"detail": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# class TelegramMessageSaveView(BotAuthenticationMixin, TelegramUserResolverMixin, APIView):
#     """
#     API для сохранения/обновления сообщений Telegram в core.
#
#     Обрабатывает два сценария:
#     1. Создание нового сообщения (когда core_message_id отсутствует)
#     2. Обновление существующего сообщения (когда core_message_id передан)
#
#     Требует:
#     - Аутентификацию бота через X-Internal-Key
#     - Разрешение пользователя по telegram_id
#     - assistant_slug для поиска ассистента и чата
#     """
#
#     def post(self, request):
#         bot = getattr(request, "internal_bot", "unknown")
#         bot_tag = f"[bot:{bot}]"
#
#         # Разрешение пользователя
#         user_resolve_result = self.resolve_telegram_user(request)
#         if isinstance(user_resolve_result, Response):
#             response = user_resolve_result
#             return response
#
#         user = user_resolve_result
#
#         payload = request.data
#
#         # core_api_logger.warning(f"TelegramMessageSaveView \n payload:\n"
#         #                         f"{yaml.dump(payload, allow_unicode=True, default_flow_style=False)}")
#
#         # Обработка через сервис
#         service = TelegramMessageService()
#         result = service.process_message(
#             payload=payload,
#             user=user,
#             bot_tag=bot_tag
#         )
#
#         return Response(result["payload"], status=result["response_status"])


class TelegramMessageSaveView(BotAuthenticationMixin, TelegramUserResolverMixin, APIView):
    """
    API для сохранения/обновления сообщений Telegram в core.
    Использует кастомные исключения для обработки ошибок.
    """

    def post(self, request):
        bot = getattr(request, "internal_bot", "unknown")
        bot_tag = f"[bot:{bot}]"

        try:
            # Разрешение пользователя через миксин
            user = self.resolve_telegram_user(request)

            # Обработка сообщения через сервис
            service = TelegramMessageService()
            result = service.process_message(
                payload=request.data,
                user=user,
                bot_tag=bot_tag
            )

            return Response(result["payload"], status=result["response_status"])

        except AuthenticationError as e:
            core_api_logger.warning(f"{bot_tag} Authentication error: {str(e)}")
            return Response(
                {"detail": str(e)},
                status=e.status_code
            )
        except UserNotFoundError as e:
            core_api_logger.warning(f"{bot_tag} User not found: {str(e)}")
            return Response(
                {"detail": str(e)},
                status=e.status_code
            )
        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Unexpected error: {str(e)}")
            return Response(
                {"detail": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
