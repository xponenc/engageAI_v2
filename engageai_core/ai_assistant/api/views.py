from typing import Dict, Any, Optional

from celery.backends.database import retry
from django.conf import settings
from django.contrib.auth import get_user_model
from engageai_core.mixins import BotAuthenticationMixin, TelegramUserResolverMixin
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ai_assistant.models import AIAssistant
from chat.models import ChatPlatform, Chat
from chat.services.interfaces.chat_service import ChatService
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
        "success": true,
        "response_type": "text|photo|document|voice|video|media_group|error",
        "data": {
            "text": "Ответ от AI",  # Для text
            "parse_mode": "HTML",   # Опционально
            "url": "https://...",   # Для одиночного медиа
            "caption": "Подпись",   # Для одиночного медиа
            "filename": "file.pdf", # Для документа
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
        "metadata": {
            "core_message_id": 123, # ID сообщения в Core
            "processing_time": 0.245 # время обработки в секундах
        }
    }
    """
    chat_service = ChatService()

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

        try:

            # 2. Получаем данные из запроса
            message_text = request.data.get("message_text", "")
            message_type = request.data.get("message_type", "text")
            user_context = request.data.get("user_context", {})
            callback_data = request.data.get("callback_data")
            platform = request.data.get("platform", "telegram")
            assistant_slug = request.data.get("assistant_slug", "default")

            # 3. Получаем дополнительные данные в зависимости от типа сообщения
            file_id = None
            caption = None
            media_data = {}

            if message_type == "photo":
                file_id = request.data.get("photo_file_id")
                caption = request.data.get("message_text", "")
                media_data = {
                    "width": request.data.get("photo_width"),
                    "height": request.data.get("photo_height"),
                    "file_size": request.data.get("photo_file_size")
                }
            elif message_type == "document":
                file_id = request.data.get("document_file_id")
                caption = request.data.get("message_text", "")
                media_data = {
                    "file_name": request.data.get("document_file_name"),
                    "mime_type": request.data.get("document_mime_type"),
                    "file_size": request.data.get("document_file_size")
                }
            elif message_type in ["audio", "voice", "video"]:
                file_id = request.data.get(f"{message_type}_file_id")
                caption = request.data.get("message_text", "")
                media_data = {k: v for k, v in request.data.items() if k.startswith(f"{message_type}_")}

            # 4. Обрабатываем запрос в зависимости от типа
            response_data = {}

            if callback_data:
                # Обработка callback от inline-кнопок
                response_data = self._process_callback(
                    callback_data=callback_data,
                    user_id=user.id,
                    platform=platform,
                    assistant_slug=assistant_slug,
                    request_data=request.data
                )
            elif message_type == "text":
                # Обработка текстового сообщения
                response_data = self._process_text_message(
                    text=message_text,
                    user_id=user.id,
                    user_context=user_context,
                    platform=platform,
                    assistant_slug=assistant_slug,
                    request_data=request.data
                )
            else:
                # Обработка медиа-сообщений и других типов
                response_data = self._process_media_message(
                    media_type=message_type,
                    file_id=file_id,
                    caption=caption,
                    media_data=media_data,
                    user_id=user.id,
                    user_context=user_context,
                    platform=platform,
                    assistant_slug=assistant_slug,
                    request_data=request.data
                )

            # 5. Если нужно, добавляем информацию о клавиатуре
            if "keyboard_config" in response_data:
                response_data["keyboard"] = self._generate_inline_keyboard(
                    response_data.pop("keyboard_config")
                )


            # 7. Добавляем общие метаданные
            response_data["metadata"] = {
                "bot_name": bot,
                "processing_time": "TODO",  # Можно добавить замер времени
                "platform": platform
            }

            # 8. Логируем результат
            core_api_logger.info(f"{bot_tag} Успешно обработан запрос для пользователя {user}")
            core_api_logger.debug(f"{bot_tag} Ответ AI: {response_data}")

            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Ошибка при обработке запроса к AI-оркестратору: {str(e)}")
            return Response({
                "error": "Internal server error while processing AI request",
                "details": str(e) if settings.DEBUG else None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _process_callback(self, callback_data: str, user_id: int, platform: str,
                          assistant_slug: str, request_data: Dict) -> Dict[str, Any]:
        """Обрабатывает callback от inline-кнопок"""
        core_api_logger.info(f"Обработка callback от пользователя {user_id}: {callback_data}")

        # TODO тестовые заглушки
        if callback_data.startswith("action:"):
            action = callback_data.split(":")[1]
            return self._handle_action(action, user_id, platform, assistant_slug, request_data)
        elif callback_data.startswith("menu:"):
            menu_item = callback_data.split(":")[1]
            return self._handle_menu(menu_item, user_id, platform, assistant_slug, request_data)
        elif callback_data.startswith("paginate:"):
            page = callback_data.split(":")[1]
            return self._handle_pagination(page, user_id, platform, assistant_slug, request_data)
        else:
            return {
                "response_message": "Неизвестное действие. Попробуйте еще раз.",
                "response_type": "text"
            }

    def _process_text_message(self, text: str, user_id: int, user_context: Dict[str, Any],
                              platform: str, assistant_slug: str, request_data: Dict) -> Dict[str, Any]:
        """Обрабатывает текстовое сообщение от пользователя"""
        core_api_logger.info(f"Обработка текстового сообщения от пользователя {user_id}")

        # Здесь должна быть интеграция с AI-моделью
        # Пока что имитируем ответ
        return {
            "response_message": f"Вы написали: {text}\n\nЭто тестовый ответ от AI-ассистента.",
            "response_type": "text",
            "keyboard_config": {
                "type": "inline",
                "buttons": [
                    {"text": "🔄 Повторить", "callback_data": "action:repeat"},
                    {"text": "❓ Помощь", "callback_data": "menu:help"}
                ],
                "layout": [2]  # 2 кнопки в ряду
            }
        }

    def _process_media_message(self, media_type: str, file_id: Optional[str], caption: Optional[str],
                               media_data: Dict[str, Any], user_id: int, user_context: Dict[str, Any],
                               platform: str, assistant_slug: str, request_data: Dict) -> Dict[str, Any]:
        """Обрабатывает медиа-сообщения"""
        core_api_logger.info(f"Обработка {media_type} сообщения от пользователя {user_id}")

        # Здесь должна быть интеграция с AI-моделью для анализа медиа
        # Пока что имитируем ответ
        return {
            "response_message": f"Я получил ваше {media_type}. "
                                f"К сожалению, в текущей версии я пока не могу анализировать медиафайлы. "
                                f"Пожалуйста, опишите словами, что вы хотели бы узнать.",
            "response_type": "text"
        }

    def _generate_inline_keyboard(self, keyboard_config: Dict) -> Dict:
        """
        Генерирует inline-клавиатуру для Telegram
        keyboard_config формат:
        {
            "type": "inline",
            "buttons": [
                {"text": "Кнопка 1", "callback_data": "btn1"},
                {"text": "Кнопка 2", "url": "https://example.com"}
            ],
            "layout": [2]  // 2 кнопки в ряду
        }
        """
        if not keyboard_config:
            return None

        buttons = []
        current_row = []
        layout = keyboard_config.get("layout", [1])
        button_index = 0

        for button in keyboard_config.get("buttons", []):
            button_data = {
                "text": button["text"]
            }

            if "callback_data" in button:
                button_data["callback_data"] = button["callback_data"]
            elif "url" in button:
                button_data["url"] = button["url"]

            current_row.append(button_data)
            button_index += 1

            # Проверяем, нужно ли перейти на следующую строку
            if button_index >= layout[0]:
                buttons.append(current_row)
                current_row = []
                button_index = 0

        # Добавляем последнюю строку, если она не пустая
        if current_row:
            buttons.append(current_row)

        return {
            "inline_keyboard": buttons
        }


    # Примеры обработчиков для разных типов действий
    def _handle_action(self, action: str, user_id: int, platform: str,
                       assistant_slug: str, request_data: Dict) -> Dict[str, Any]:
        """Обрабатывает действия пользователя"""
        if action == "repeat":
            return {
                "response_message": "Пожалуйста, повторите ваш вопрос или запрос.",
                "response_type": "text"
            }
        elif action == "cancel":
            return {
                "response_message": "Действие отменено. Чем я могу вам помочь?",
                "response_type": "text"
            }
        else:
            return {
                "response_message": f"Действие '{action}' не поддерживается.",
                "response_type": "text"
            }

    def _handle_menu(self, menu_item: str, user_id: int, platform: str,
                     assistant_slug: str, request_data: Dict) -> Dict[str, Any]:
        """Обрабатывает выбор пункта меню"""
        menus = {
            "help": {
                "response_message": "Я могу помочь вам с:\n\n"
                                    "• Ответами на вопросы\n"
                                    "• Анализом материалов\n"
                                    "• Практикой диалогов\n"
                                    "• Объяснением сложных тем\n\n"
                                    "Просто задайте ваш вопрос!",
                "response_type": "text"
            },
            "settings": {
                "response_message": "Настройки:\n\n"
                                    "• Язык общения: Русский\n"
                                    "• Сложность ответов: Средняя\n"
                                    "• Уведомления: Включены\n\n"
                                    "Что вы хотите изменить?",
                "response_type": "text",
                "keyboard_config": {
                    "type": "inline",
                    "buttons": [
                        {"text": "🔤 Язык", "callback_data": "settings:language"},
                        {"text": "📊 Сложность", "callback_data": "settings:difficulty"},
                        {"text": "🔔 Уведомления", "callback_data": "settings:notifications"}
                    ],
                    "layout": [1, 1, 1]
                }
            }
        }

        return menus.get(menu_item, {
            "response_message": f"Меню '{menu_item}' не найдено.",
            "response_type": "text"
        })

    def _handle_pagination(self, page: str, user_id: int, platform: str,
                           assistant_slug: str, request_data: Dict) -> Dict[str, Any]:
        """Обрабатывает пагинацию"""
        try:
            page_num = int(page)
            return {
                "response_message": f"Страница {page_num}\n\nЭто тестовый контент для страницы {page_num}.",
                "response_type": "text",
                "keyboard_config": {
                    "type": "inline",
                    "buttons": [
                        {"text": "⬅️ Назад",
                         "callback_data": f"paginate:{page_num - 1}" if page_num > 1 else "paginate:1"},
                        {"text": f"Стр. {page_num}", "callback_data": f"current_page:{page_num}"},
                        {"text": "Вперед ➡️", "callback_data": f"paginate:{page_num + 1}"}
                    ],
                    "layout": [3]
                }
            }
        except ValueError:
            return {
                "response_message": "Неверный номер страницы.",
                "response_type": "text"
            }