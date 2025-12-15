# from typing import Optional
#
# from django.contrib.auth import get_user_model
# from rest_framework import status
#
# from ai_assistant.models import AIAssistant
# from chat.models import Chat, ChatPlatform
# from utils.setup_logger import setup_logger
#
# User = get_user_model()
#
# core_api_logger = setup_logger(name=__file__, log_dir="logs/core_api", log_file="core_api.log")
#
# class ChatService:
#     """Вспомогательные методы по работе с Chat"""
#
#     @staticmethod
#     def get_or_create_assistant_chat(
#             user: User,
#             assistant_slug: str,
#             chat_platform: ChatPlatform,
#             api_tag: str,
#     ):
#         """Получает или создает чат для пользователя с указанным ассистентом"""
#         try:
#             assistant = AIAssistant.objects.get(slug=assistant_slug, is_active=True)
#
#             chat, created = Chat.get_or_create_ai_chat(
#                 user=user,
#                 ai_assistant=assistant,
#                 platform=chat_platform,
#                 title=f"Telegram Чат с {assistant.name}",
#             )
#
#             # Добавление пользователя в участники, если чат новый
#             if created:
#                 chat.participants.add(user)
#                 core_api_logger.info(
#                     f"{api_tag} Создан новый AI-чат {chat.id} для пользователя {user.pk}"
#                     f" с ассистентом {assistant}(slug={assistant.slug})")
#             else:
#                 core_api_logger.debug(f"{api_tag} Найден существующий AI-чат {chat.id} для пользователя {user.id}")
#
#             return chat
#
#         except AIAssistant.DoesNotExist:
#             core_api_logger.error(f"{api_tag} Ассистент с slug {assistant_slug} не найден")
#             return {
#                 "payload": {
#                     "detail": f"Assistant with slug '{assistant_slug}' not found"
#                 },
#                 "response_status": status.HTTP_404_NOT_FOUND,
#             }
#         except Exception as e:
#             core_api_logger.exception(f"{api_tag} Ошибка при получении/создании чата: {str(e)}")
#             return {
#                 "payload": {
#                     "detail": f"Error getting/creating chat: {str(e)}"
#                 },
#                 "response_status": status.HTTP_500_INTERNAL_SERVER_ERROR,
#             }
#
#     @staticmethod
#     def get_chat_platform(value: Optional[str] = 'api') -> ChatPlatform:
#         """
#         Возвращает элемент перечисления ChatPlatform по его строковому значению.
#
#         Поведение:
#         - Если значение совпадает с одним из вариантов TextChoices — возвращается соответствующий ChatPlatform.
#         - Если значение None, пустое или не найдено в перечислении — возвращается ChatPlatform.API.
#
#         Параметры:
#             value (Optional[str]): Строковое значение платформы (например, "telegram", "web").
#
#         Возвращает:
#             ChatPlatform: Найденная платформа или ChatPlatform.API по умолчанию.
#         """
#         if not value:
#             return ChatPlatform.API
#
#         try:
#             return ChatPlatform(value)
#         except ValueError:
#             return ChatPlatform.API