from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from engageai_core.ai.orchestrator import Orchestrator
from engageai_core.engageai_core.mixins import InternalBotAuthMixin
from utils.setup_logger import setup_logger

logger = setup_logger(__name__, log_dir="logs/ai_api", log_file="orchestrator.log")


class OrchestratorProcessView(InternalBotAuthMixin, APIView):
    """
    API для обработки сообщений через AI-оркестратор
    """

    def post(self, request):
        bot = request.internal_bot
        bot_tag = f"[bot:{bot}]"

        user_id = request.data.get("user_id")
        message_text = request.data.get("message_text")
        user_context = request.data.get("user_context", {})
        platform = request.data.get("platform", "web")

        if not user_id or not message_text:
            logger.warning(f"{bot_tag} Не хватает данных для оркестратора: user_id={user_id}")
            return Response({
                "success": False,
                "detail": "Missing required parameters"
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Инициализация оркестратора с user_id
            orchestrator = Orchestrator(user_id, user_context, platform)

            # Обработка сообщения
            result = orchestrator.process_message(message_text)

            logger.info(f"{bot_tag} Успешная обработка сообщения от пользователя {user_id}")

            return Response({
                "success": True,
                "response_message": result["message"],
                "metadata": result.get("metadata", {})
            })

        except Exception as e:
            logger.exception(f"{bot_tag} Ошибка в оркестраторе: {str(e)}")
            return Response({
                "success": False,
                "detail": "Internal processing error"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)