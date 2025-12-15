from datetime import datetime
from typing import Optional, List
from django.contrib.auth import get_user_model
from ai_assistant.models import AIAssistant
from chat.services.interfaces.base_service import BaseService
from chat.services.interfaces.exceptions import AssistantNotFoundError, ChatCreationError
from chat.models import Chat, ChatPlatform, ChatScope, Message

User = get_user_model()


class ChatService(BaseService):
    """
    Единый сервис для управления чатами разных платформ
    """
    #
    # def get_or_create_platform_chat(
    #         self,
    #         user: User,
    #         assistant_slug: str,
    #         platform: ChatPlatform,
    #         scope: ChatScope = ChatScope.PRIVATE,
    #         title: Optional[str] = None,
    #         external_chat_id: Optional[str] = None
    # ) -> Chat:
    #     """
    #     Получает или создает чат для пользователя с AI-ассистентом
    #     """
    #     try:
    #         assistant = AIAssistant.objects.get(slug=assistant_slug, is_active=True)
    #     except AIAssistant.DoesNotExist:
    #         self.logger.error(f"AI-ассистент с slug {assistant_slug} не найден")
    #         raise AssistantNotFoundError(assistant_slug)
    #
    #     # Поиск существующего чата
    #     chat = Chat.objects.filter(
    #         owner=user,
    #         ai_assistant=assistant,
    #         platform=platform,
    #         scope=scope,
    #         is_active=True
    #     ).first()
    #
    #     if chat:
    #         self.logger.debug(f"Найден существующий чат {chat.id} для пользователя {user.id}")
    #         return chat
    #
    #     # Создание нового чата
    #     default_title = title or f"{'Telegram' if platform == ChatPlatform.TELEGRAM else 'Веб'} чат с {assistant.name}"
    #
    #     chat = Chat.objects.create(
    #         owner=user,
    #         ai_assistant=assistant,
    #         platform=platform,
    #         scope=scope,
    #         title=default_title,
    #         is_ai_enabled=True,
    #         external_chat_id=external_chat_id
    #     )
    #
    #     chat.participants.add(user)
    #     self.logger.info(
    #         f"Создан {'Telegram' if platform == ChatPlatform.TELEGRAM else 'веб'} чат {chat.id} "
    #         f"для пользователя {user.id} с ассистентом {assistant.slug}"
    #     )
    #
    #     return chat
    #
    # def get_or_create_assistant_chat(
    #         self,
    #         user: User,
    #         assistant_slug: str,
    #         chat_platform: ChatPlatform,
    #         api_tag: str,
    # ):
    #     try:
    #         assistant = AIAssistant.objects.get(slug=assistant_slug, is_active=True)
    #         chat, created = Chat.get_or_create_ai_chat(
    #             user=user,
    #             ai_assistant=assistant,
    #             platform=chat_platform,
    #             title=f"Telegram Чат с {assistant.name}",
    #         )
    #         if created:
    #             chat.participants.add(user)
    #             self.logger.info(
    #                 f"{api_tag} Создан новый AI-чат {chat.id} для пользователя {user.pk}"
    #                 f" с ассистентом {assistant}(slug={assistant.slug})")
    #         else:
    #             self.logger.debug(f"{api_tag} Найден существующий AI-чат {chat.id} для пользователя {user.id}")
    #         return chat
    #     except AIAssistant.DoesNotExist:
    #         self.logger.error(f"{api_tag} Ассистент с slug {assistant_slug} не найден")
    #         raise AssistantNotFoundError(assistant_slug)
    #     except Exception as e:
    #         self.logger.exception(f"{api_tag} Ошибка при получении/создании чата: {str(e)}")
    #         raise ChatCreationError(str(e))

    def get_or_create_chat(
            self,
            user: User,
            platform: ChatPlatform,
            scope: ChatScope = ChatScope.PRIVATE,
            assistant_slug: Optional[str] = None,
            # title: Optional[str] = None,
            external_chat_id: Optional[str] = None,
            api_tag: Optional[str] = None
    ) -> Chat:
        """
        Получает или создает чат для пользователя
        """
        context = f"{api_tag} " if api_tag else ""
        context += f"user={user.id}, platform={platform.value}"

        try:
            assistant = None
            if assistant_slug:
                try:
                    assistant = AIAssistant.objects.get(slug=assistant_slug, is_active=True)
                except AIAssistant.DoesNotExist:
                    self.logger.error(f"{context} Ассистент с slug {assistant_slug} не найден")
                    raise AssistantNotFoundError(assistant_slug)

            # Поиск существующего чата
            chat_query = Chat.objects.filter(
                owner=user,
                platform=platform,
                scope=scope,
                is_active=True
            )

            if assistant:
                chat_query = chat_query.filter(ai_assistant=assistant)

            chat = chat_query.first()
            if chat:
                self.logger.debug(f"{context} Найден существующий чат {chat.id}")
                return chat

            chat_params = {
                "owner": user,
                "platform": platform,
                "scope": scope,
                # "title": title,
                "is_ai_enabled": bool(assistant),
                "external_chat_id": external_chat_id
            }

            if assistant:
                chat_params["ai_assistant"] = assistant

            chat = Chat.objects.create(**chat_params)
            chat.participants.add(user)

            action = "Создан" if not assistant else f"Создан AI-чат с {assistant.name}"
            self.logger.info(
                f"{context} {action} {chat.id} для пользователя {user.id}"
            )

            return chat

        except Exception as e:
            self.logger.exception(f"{context} Ошибка при получении/создании чата: {str(e)}")
            chat_data = {
                "user_id": user.id,
                "platform": platform.value,
                "assistant_slug": assistant_slug
            }
            raise ChatCreationError(str(e), chat_data) from e


    def get_chat_history(
            self,
            chat: Chat,
            limit: int = 50,
            include_deleted: bool = False,
            exclude_ai_messages: bool = False,
            since: Optional[datetime] = None
    ) -> List[Message]:
        """
        Получает историю сообщений с гибкими параметрами фильтрации
        """
        messages = chat.messages.select_related('sender').prefetch_related('media_files').order_by("created_at")

        if not include_deleted:
            messages = messages.filter(is_user_deleted=False)

        if exclude_ai_messages:
            messages = messages.filter(is_ai=False)

        if since:
            messages = messages.filter(created_at__gte=since)

        return list(messages[:limit])