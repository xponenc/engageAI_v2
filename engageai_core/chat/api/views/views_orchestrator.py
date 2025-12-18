import random
from multiprocessing import AuthenticationError
from typing import Dict, Any, Optional

from celery.backends.database import retry
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from engageai_core.mixins import BotAuthenticationMixin, TelegramUserResolverMixin
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ai_assistant.models import AIAssistant
from assessment.models import CEFRQuestion, QuestionType
from chat.models import ChatPlatform, Chat, Message, ChatScope
from chat.services.interfaces.chat_service import ChatService
from chat.services.interfaces.message_service import MessageService
from utils.setup_logger import setup_logger

User = get_user_model()

core_api_logger = setup_logger(name=__file__, log_dir="logs/core_api", log_file="core_api.log")


class OrchestratorProcessAPIView(BotAuthenticationMixin, TelegramUserResolverMixin, APIView):
    """
    Обрабатывает запросы

    Формат запроса:
    {
        "user_id": 12345,           # ID пользователя в Core
        "source": "telegram",       # Источник: telegram/web/api/system
        "content": "Текст сообщения",  # Обязательно для text
        "message_type": "text|image|audio|video|document|callback|media_group",
        "reply_to_external_id": 67890,  # Опционально: ID сообщения в Telegram, на которое отвечает пользователь
        "media_files": [            # Опционально: массив медиафайлов
            {
                "external_id": "AgACAgIAAxkBAAMjZ...",  # file_id в Telegram
                "file_type": "image",  # image/audio/video/document
                "mime_type": "image/jpeg",  # MIME type
                "caption": "Подпись к фото"  # Опционально
            }
        ],
        "metadata": {               # Опционально: дополнительные данные
            "chat_id": 123456789,   # ID чата в Telegram
            "message_id": 987654,   # ID сообщения в Telegram
            "from_user": {
                "id": 432684977,
                "username": "user_name",
                "first_name": "Имя",
                "last_name": "Фамилия"
            }
        }
    }

    Формат ответа:
    {
        "response_type": "text|photo|document|voice|video|media_group|error",
        "data": {
            "text": "Ответ от AI",  # Для text
            "parse_mode": "HTML",   # Опционально
            "media": [              # Для медиа-группы
                {
                    "type": "photo|video",
                    "url": "https://...",
                    "caption": "Подпись"
                }
            ],
            "keyboard": {           # Опционально
                "type": "inline|reply",
                "buttons": [
                    {"text": "Кнопка 1", "callback_data": "data1"},
                    {"text": "Ссылка", "url": "https://example.com"}
                ],
                "layout": [2]       # 2 кнопки в ряду
            }
        },
        "core_answer": {
            "core_message_id": 123, # ID Message сообщения в Core
        }
    }
    """
    chat_service = ChatService()
    message_service = MessageService()

    def post(self, request, *args, **kwargs):
        # Получаем информацию о боте из аутентификации
        bot = getattr(request, "internal_bot", 'unknown')
        bot_tag = f"[bot:{bot}]"

        core_api_logger.info(f"{bot_tag} Получен запрос к AI-оркестратору")
        core_api_logger.info(f"{bot_tag} Payload: {request.data}")

        user_resolve_result = self.resolve_telegram_user(request)
        if isinstance(user_resolve_result, dict):
            result = user_resolve_result
            return Response(result["payload"], status=result["response_status"])
        user = user_resolve_result

        payload = request.data
        assistant_slug = payload.get("assistant_slug")
        core_message_id = payload.get("core_message_id")
        reply_to_message_id = payload.get("reply_to_message_id")
        platform_str = payload.get("platform")

        if not assistant_slug:
            return Response(
                {"error": "Missing 'assistant_slug' in request"},
                status=status.HTTP_400_BAD_REQUEST
            )

        platform = ChatPlatform.__members__.get(platform_str.upper(), ChatPlatform.API)

        chat = self.chat_service.get_or_create_chat(
            user=user,
            platform=platform,
            scope=ChatScope.PRIVATE,
            assistant_slug=assistant_slug,
            api_tag=bot_tag,
        )
        try:

            reply_to_msg = Message.objects.filter(
                source_type=platform,
                metadata__telegram__message_id=str(reply_to_message_id),
                chat=chat
            ).first()

            """Выбор случайного вопроса из уровня"""
            qs = CEFRQuestion.objects.values_list("id", flat=True)
            if not qs:
                return None
            qid = random.choice(list(qs))
            task = CEFRQuestion.objects.get(id=qid)

            keyboard_config = None
            if task.options:
                keyboard_config = {
                    "type": "inline",
                    "buttons": [{"text": opt} for opt in task.options],
                    "layout": [1] * len(task.options)  # одна кнопка в строке
                    # "layout": [2] * ((len(task.options) + 1) // 2) #  две кнопки в строке
                }

            text = ""
            if task.type == QuestionType.MCQ:
                text = "Выберите правильный вариант ответа\n\n"
            text += task.question_text

            ai_message = Message.objects.create(
                chat=chat,
                content=text,  # TODO добавить сохранение клавиатур
                is_ai=True,
                source_type=platform,
                sender=None,
                reply_to=reply_to_msg,
                external_id=None,
                metadata={
                    "task_id": str(task.pk),
                }
            )

            response_data = {
                "response_type": "text",
                "core_answer": {
                    "text": text,
                    "parse_mode": "HTML",  # Опционально
                    # "media": [              # Для медиа-группы
                    #     {
                    #         "type": "photo|video",
                    #         "url": "https://...",
                    #         "caption": "Подпись"
                    #     }
                    # ],
                    "keyboard": keyboard_config,
                    # Пример
                    # keyboard_config = {
                    #     "type": "inline", # inline | reply
                    #     "buttons": [{"text": opt} for opt in task.options],
                    #     "layout": [1]
                    # }
                    "message_effect_id": "",  # Telegram message_effect_id - эффект телеграм в сообщении
                    "audio_answer": False,  # Ожидаем аудио ответ
                },
                "core_answer_meta": {
                    "task_id": task.pk,
                    "core_message_id": ai_message.pk,
                    "reply_to_message_id": reply_to_message_id,
                    "last_message_update_config": {
                        "change_last_message": True,  # Флаг изменять/не изменять last_message
                        "text": {
                            "method": "append",  # append добавить текст к сообщению, rewrite - изменить полностью
                            "last_message_update_text": "\U00002705 Ответ принят",
                            "fix_user_answer": True,
                            # Зафиксировать в изменяемом сообщении цитатой ответ пользователя - протоколирование
                        },
                        "keyboard": {
                            "reset": True,  # Удалить клавиатуру у редактируемого сообщения
                        }
                    },
                }
            }

            # 8. Логируем результат
            core_api_logger.info(f"{bot_tag} Успешно обработан запрос для пользователя {user}")
            core_api_logger.info(f"{bot_tag} Ответ AI: {response_data}")

            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Ошибка при обработке запроса к AI-оркестратору: {str(e)}")
            return Response({
                "error": "Internal server error while processing AI request",
                "details": str(e) if settings.DEBUG else None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
