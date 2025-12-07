from rest_framework import status
from rest_framework.response import Response
from django.conf import settings
from ai_assistant.models import AIAssistant
from chat.models import Chat, ChatPlatform, Message, MessageSource
from utils.setup_logger import setup_logger

core_api_logger = setup_logger(name=__name__, log_dir="logs/core_api", log_file="telegram_service.log")


class TelegramAssessmentService:
    """Сервис для интеграции оценки уровня с Telegram-ботом"""

    def __init__(self, assistant_slug="main_orchestrator"):
        self.assistant_slug = assistant_slug

    def _get_assistant(self):
        """Получает AIAssistant по slug"""
        try:
            return AIAssistant.objects.get(slug=self.assistant_slug, is_active=True)
        except AIAssistant.DoesNotExist:
            core_api_logger.error(f"AIAssistant not found: slug={self.assistant_slug}")
            return None

    def _get_or_create_chat(self, user, assistant):
        """Получает или создает чат для пользователя и ассистента"""
        return Chat.get_or_create_ai_chat(
            user=user,
            ai_assistant=assistant,
            platform=ChatPlatform.TELEGRAM,
        )

    def _get_reply_message(self, chat, incoming_message_id):
        """Получает сообщение для ответа по ID"""
        if not incoming_message_id:
            return None

        return Message.objects.filter(
            source_type=MessageSource.TELEGRAM,
            metadata__telegram__message_id=incoming_message_id,
            chat=chat
        ).first()

    def create_question_message(self, user, session, question, incoming_message_id=None, bot=None):
        """Создает сообщение с вопросом в чате"""
        bot_tag = f"[bot:{bot}]" if bot else ""

        assistant = self._get_assistant()
        if not assistant:
            core_api_logger.error(f"{bot_tag} Failed to find AIAssistant with slug={self.assistant_slug}")
            return Response(
                {"detail": f"Failed to find AIAssistant with slug={self.assistant_slug}"},
                status=status.HTTP_404_NOT_FOUND
            )

        chat, created = self._get_or_create_chat(user, assistant)
        reply_to_msg = self._get_reply_message(chat, incoming_message_id)

        ai_message = Message.objects.create(
            chat=chat,
            content=question.question_json["question_text"],  # TODO добавить сохранение клавиатур
            is_ai=True,
            source_type=MessageSource.TELEGRAM,
            sender=None,
            reply_to=reply_to_msg,
            external_id=None,
        )

        return ai_message

    def create_finish_message(self, user, session, level, view_url, incoming_message_id=None, bot=None):
        """Создает завершающее сообщение после теста"""
        bot_tag = f"[bot:{bot}]" if bot else ""

        assistant = self._get_assistant()
        if not assistant:
            core_api_logger.error(f"{bot_tag} Failed to find AIAssistant with slug={self.assistant_slug}")
            return Response(
                {"success": False, "detail": f"Failed to find AIAssistant with slug={self.assistant_slug}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        chat, created = self._get_or_create_chat(user, assistant)
        reply_to_msg = self._get_reply_message(chat, incoming_message_id)

        msg = (
            f"🎉 <b>Тест завершён!</b>\n"
            f"Ваш уровень английского: <b>{level}</b> 🎯\n\n"
            f"Сейчас AI выполнит анализ и даст полный разбор, рекомендации и ошибки доступны в личном кабинете.\n"
            f"Загляните — это реально полезно 👇\n"
            f"{view_url}"
        )

        ai_message = Message.objects.create(
            chat=chat,
            content=msg,
            is_ai=True,
            source_type=MessageSource.TELEGRAM,
            sender=None,
            reply_to=reply_to_msg,
            external_id=None,
        )

        return ai_message
