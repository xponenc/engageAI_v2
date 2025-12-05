from typing import Optional, Dict, Any, Union

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import F
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db import transaction

from engageai_core.ai_assistant.models import AIAssistant
from engageai_core.chat.models import Chat, Message, MessageSource, ChatPlatform
from engageai_core.chat.services.telegram_message_service import TelegramMessageService, TelegramUpdateService
from engageai_core.engageai_core.mixins import BotAuthenticationMixin, TelegramUserResolverMixin
from utils.setup_logger import setup_logger

User = get_user_model()


core_api_logger = setup_logger(name=__file__, log_dir="logs/core_api", log_file="core_api.log")


class TelegramUpdateSaveView(BotAuthenticationMixin, TelegramUserResolverMixin, APIView):
    """
    Сохраняет апдейты Telegram: message, edited_message, callback_query.
    Проверяет дубли по external_id и формирует корректные метаданные.
    Использует обновленный TelegramMessageService для работы с сообщениями.
    """

    def post(self, request):
        bot = getattr(request, "internal_bot", "unknown")
        bot_tag = f"[bot:{bot}]"

        # Разрешение пользователя
        user_resolve_result = self.resolve_telegram_user(request)
        if isinstance(user_resolve_result, Response):
            return user_resolve_result
        user = user_resolve_result

        update_data = request.data.get("update")
        assistant_slug = request.data.get("assistant_slug")

        if not update_data:
            core_api_logger.warning(f"{bot_tag} Отсутствует поле 'update' в запросе")
            return Response({"success": False, "detail": "Missing update data"}, status=status.HTTP_400_BAD_REQUEST)

        # Обработка через сервис
        service = TelegramUpdateService()
        success, result = service.process_update(
            update_data=update_data,
            assistant_slug=assistant_slug,
            user=user,
            bot_tag=bot_tag
        )

        if not success:
            return Response({"success": False, "detail": result}, status=status.HTTP_400_BAD_REQUEST)

        # Определение статуса ответа
        status_code = status.HTTP_200_OK if isinstance(result, dict) and "detail" in result else status.HTTP_201_CREATED
        return Response(result, status=status_code)

    @transaction.atomic
    def post(self, request):
        bot = getattr(request, "internal_bot", None)
        bot_tag = f"[bot:{bot}]"
        core_api_logger.debug(f"{bot_tag} Получен запрос на обработку апдейта")

        # Разрешение пользователя по telegram_id
        user_resolve_result = self.resolve_telegram_user(request)
        if isinstance(user_resolve_result, Response):
            core_api_logger.warning(f"{bot_tag} Не удалось разрешить пользователя: {user_resolve_result.data}")
            return user_resolve_result
        user = user_resolve_result

        update_data = request.data.get("update")
        assistant_slug = request.data.get("assistant_slug")

        if not update_data:
            core_api_logger.warning(f"{bot_tag} Отсутствует поле 'update' в запросе")
            return Response({"success": False, "detail": "Missing update data"}, status=status.HTTP_400_BAD_REQUEST)

        update_id = update_data.get("update_id")
        if not update_id:
            core_api_logger.warning(f"{bot_tag} Отсутствует update_id в апдейте")
            return Response({"success": False, "detail": "Missing update_id"}, status=status.HTTP_400_BAD_REQUEST)

        # Проверка дубликата через external_id по уникальному update_id
        if Message.objects.filter(external_id=str(update_id), source_type=MessageSource.TELEGRAM).exists():
            core_api_logger.info(f"{bot_tag} Апдейт {update_id} уже обработан, пропускаем")
            return Response({"success": True, "detail": "Update already processed"}, status=status.HTTP_200_OK)

        # Определение типа апдейта и делегирование обработки
        try:
            core_api_logger.debug(f"{bot_tag} Начало обработки апдейта {update_id}, типы: {list(update_data.keys())}")

            if "message" in update_data:
                return self._process_message(update_data["message"], update_id, bot_tag, assistant_slug, user)
            elif "edited_message" in update_data:
                return self._process_edited_message(update_data["edited_message"], bot_tag, assistant_slug, user)
            elif "callback_query" in update_data:
                return self._process_callback(update_data["callback_query"], update_id, bot_tag, assistant_slug, user)
            else:
                core_api_logger.warning(f"{bot_tag} Неизвестный тип апдейта: {list(update_data.keys())}")
                return Response({"success": False, "detail": "Unknown update type"}, status=status.HTTP_400_BAD_REQUEST)

        except ObjectDoesNotExist as e:
            core_api_logger.error(f"{bot_tag} Ошибка поиска объекта при обработке апдейта {update_id}: {str(e)}")
            return Response({"success": False, "detail": f"Required object not found: {str(e)}"},
                            status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Непредвиденная ошибка при обработке апдейта {update_id}: {str(e)}")
            return Response({"success": False, "detail": "Internal server error"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


    def _process_message(self, message_data, update_id, bot_tag, assistant_slug, user):
        """Обрабатывает обычное сообщение из Telegram"""
        message_id = message_data.get("message_id")
        text = message_data.get("text", "")

        chat = self._get_or_create_chat(user=user, assistant_slug=assistant_slug, bot_tag=bot_tag)
        if isinstance(chat, Response):
            return chat

        try:
            message = TelegramMessageService.create_message_from_update(
                chat=chat,
                sender=user,
                content=text,
                update_id=update_id,
                message_id=message_id,
                extra_metadata=message_data
            )

            core_api_logger.info(f"{bot_tag} Создано сообщение ID {message.id} из апдейта {update_id}")
            return Response({
                "success": True,
                "core_message_id": message.id,
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            core_api_logger.error(f"{bot_tag} Ошибка создания сообщения из апдейта {update_id}: {str(e)}")
            return Response({
                "success": False,
                "detail": f"Error creating message: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _process_edited_message(self, edited_data, bot_tag, assistant_slug, user):
        """Обрабатывает отредактированное сообщение"""
        message_id = str(edited_data.get("message_id", ""))
        new_text = edited_data.get("text", "")

        # Получение чата
        chat = self._get_or_create_chat(user=user, assistant_slug=assistant_slug, bot_tag=bot_tag)
        if isinstance(chat, Response):
            return chat

        try:
            # Поиск сообщения по message_id
            message = Message.objects.get(
                metadata__telegram__message_id=str(message_id),
                chat=chat,
                source_type=MessageSource.TELEGRAM
            )

            # Обновление содержимого и метаданных
            old_content = message.content
            message.content = new_text
            message.edited_at = timezone.now()

            # Обновляем метаданные с информацией о редактировании
            metadata = message.metadata or {}
            if "edit_history" not in metadata:
                metadata["edit_history"] = []

            metadata["edit_history"].append({
                "timestamp": timezone.now().isoformat(),
                "old_content": old_content,
                "new_content": new_text,
                "editor_id": user.id
            })

            # Обновляем счётчик редактирований
            message.edit_count = F("edit_count") + 1
            message.metadata = metadata
            message.save(update_fields=["content", "edited_at", "edit_count", "metadata"])

            core_api_logger.info(f"{bot_tag} Обновлено сообщение ID {message.id}, версия {message.edit_count + 1}")
            return Response({
                "success": True,
                "message_id": message.id,
                "chat_id": chat.id,
                "edit_count": message.edit_count + 1
            }, status=status.HTTP_200_OK)

        except Message.DoesNotExist:
            core_api_logger.warning(f"{bot_tag} Редактирование несуществующего сообщения {message_id}")
            return Response({
                "success": False,
                "detail": f"Message with ID {message_id} not found"
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Ошибка редактирования сообщения {message_id}: {str(e)}")
            return Response({
                "success": False,
                "detail": f"Error editing message: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _process_callback(self, callback_data, update_id, bot_tag, assistant_slug, user):
        """Обрабатывает callback query от inline-кнопок"""
        message_data = callback_data.get("message")
        callback_id = callback_data.get("id")
        callback_data_value = callback_data.get("data")

        # Получение чата
        chat = self._get_or_create_chat(user=user, assistant_slug=assistant_slug, bot_tag=bot_tag)
        if isinstance(chat, Response):
            return chat

        # Поиск исходного сообщения
        original_message = None
        if message_data:
            original_message_id = message_data.get("message_id")
            if not original_message_id:
                core_api_logger.error(f"{bot_tag} Callback query не содержит message_id: {callback_data}")
                return Response({
                    "success": False,
                    "detail": "Missing message_id in callback query"
                }, status=status.HTTP_400_BAD_REQUEST)
            try:
                original_message = Message.objects.get(
                    metadata__telegram__message_id=str(original_message_id),
                    chat=chat,
                    source_type=MessageSource.TELEGRAM
                )
            except Message.DoesNotExist:
                core_api_logger.warning(
                    f"{bot_tag} Не найдено исходное сообщение {original_message_id} для callback {callback_id}")

        # Создание сообщения для callback
        try:
            content = f"[Callback: {callback_data_value}]"

            callback_message = TelegramMessageService.create_message_from_update(
                chat=chat,
                sender=user,
                content=content,
                update_id=update_id,
                message_id=callback_id,
                extra_metadata=callback_data,
                reply_to=original_message
            )

            core_api_logger.info(
                f"{bot_tag} Создан callback-сообщение ID {callback_message.id} для update_id {update_id}")
            return Response({
                "success": True,
                "message_id": callback_message.id,
                "chat_id": chat.id,
                "callback_id": callback_id
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            core_api_logger.exception(
                f"{bot_tag} Ошибка создания callback-сообщения для update_id {update_id}: {str(e)}")
            return Response({
                "success": False,
                "detail": f"Error creating callback message: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @staticmethod
    def _get_or_create_chat(
        user:User,
        assistant_slug:str,
        bot_tag: str,
    ):
        """Получает или создает чат для пользователя с указанным ассистентом"""
        try:
            assistant = AIAssistant.objects.get(slug=assistant_slug, is_active=True)

            chat, created = Chat.get_or_create_ai_chat(
                user=user,
                ai_assistant=assistant,
                platform=ChatPlatform.TELEGRAM,
                title=f"Telegram Чат с {assistant.name}",
            )

            # Добавление пользователя в участники, если чат новый
            if created:
                chat.participants.add(user)
                core_api_logger.info(
                    f"{bot_tag} Создан новый AI-чат {chat.id} для пользователя {user.id} с ассистентом {assistant.slug}")
            else:
                core_api_logger.debug(f"{bot_tag} Найден существующий AI-чат {chat.id} для пользователя {user.id}")

            return chat

        except AIAssistant.DoesNotExist:
            core_api_logger.error(f"{bot_tag} Ассистент с slug {assistant_slug} не найден")
            return Response({
                "success": False,
                "detail": f"Assistant with slug '{assistant_slug}' not found"
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Ошибка при получении/создании чата: {str(e)}")
            return Response({
                "success": False,
                "detail": f"Error getting/creating chat: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TelegramMessageSaveView(BotAuthenticationMixin, TelegramUserResolverMixin, APIView):
    """
    API для сохранения/обновления сообщений Telegram в core.

    Обрабатывает два сценария:
    1. Создание нового сообщения (когда core_message_id отсутствует)
    2. Обновление существующего сообщения (когда core_message_id передан)

    Требует:
    - Аутентификацию бота через X-Internal-Key
    - Разрешение пользователя по telegram_id
    - assistant_slug для поиска ассистента и чата
    """

    @transaction.atomic
    def post(self, request):
        bot = getattr(request, "internal_bot", "unknown")
        bot_tag = f"[bot:{bot}]"

        # Разрешение пользователя по telegram_id
        user_resolve_result = self.resolve_telegram_user(request)
        if isinstance(user_resolve_result, Response):
            return user_resolve_result
        user = user_resolve_result

        payload = request.data
        assistant_slug = payload.get("assistant_slug")
        core_message_id = payload.get("core_message_id")
        telegram_message_id = payload.get("telegram_message_id")
        text = payload.get("text", "")
        metadata = payload.get("metadata", {})

        if core_message_id:
            # Обновление
            return self._update_existing_message(
                bot_tag=bot_tag,
                core_message_id=core_message_id,
                telegram_message_id=telegram_message_id,
                content=text,
                metadata=metadata
            )
        else:
            # Создание нового
            if not assistant_slug:
                core_api_logger.warning(f"{bot_tag} Missing assistant_slug in request")
                return Response({"success": False, "detail": "Missing assistant_slug"},
                                status=status.HTTP_400_BAD_REQUEST)

            return self._create_new_message(
                bot_tag=bot_tag,
                telegram_message_id=telegram_message_id,
                text=text,
                metadata=metadata,
                assistant_slug=assistant_slug,
                user=user
            )

    def _create_new_message(
            self,
            bot_tag:str,
            telegram_message_id: Union[str, int],
            text: str,
            metadata:Dict[str, Any],
            assistant_slug:str,
            user:User):
        """Создает новое AI-сообщение в core и связывает его с Telegram"""
        try:
            chat = self._get_or_create_chat(user=user, assistant_slug=assistant_slug, bot_tag=bot_tag)

            if telegram_message_id:
                existing_message = Message.objects.filter(
                    source_type=MessageSource.TELEGRAM,
                    metadata__telegram__message_id=str(telegram_message_id),
                    chat=chat,
                    is_ai=True
                ).first()

                if existing_message:
                    core_api_logger.info(
                        f"{bot_tag} Duplicate AI message found: telegram_id={telegram_message_id}, "
                        f"core_id={existing_message.id}"
                    )
                    return Response({
                        "success": True,
                        "core_message_id": existing_message.id,
                        "chat_id": chat.id,
                        "duplicate": True
                    }, status=status.HTTP_200_OK)

            new_message = TelegramMessageService.create_ai_message(
                chat=chat,
                content=text,
                message_id=telegram_message_id,
                extra_metadata=metadata
            )

            core_api_logger.info(
                f"{bot_tag} Created new AI message: core_id={new_message.id}, "
                f"telegram_id={telegram_message_id}, chat_id={chat.id}"
            )

            return Response({
                "success": True,
                "core_message_id": new_message.id,
                "chat_id": chat.id
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Error creating AI message: {str(e)}")
            return Response({
                "success": False,
                "detail": f"Error creating AI message: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


    @staticmethod
    def _update_existing_message(
        bot_tag:str,
        core_message_id:str,
        telegram_message_id:str,
        content:str,
        metadata: Optional[Dict[str, Any]],
    ):
        """Обновляет существующее AI-сообщение в core с привязкой к Telegram"""
        try:
            try:
                message = Message.objects.get(
                    id=core_message_id,
                    is_ai=True,
                    sender=None,
                    source_type=MessageSource.TELEGRAM
                )
            except ObjectDoesNotExist:
                core_api_logger.error(f"{bot_tag} AI message not found: core_id={core_message_id}")
                return Response({
                    "success": False,
                    "detail": f"AI message with ID {core_message_id} not found"
                }, status=status.HTTP_404_NOT_FOUND)

            # Обновление метаданных Telegram для AI-сообщения
            updated_message = TelegramMessageService.update_ai_message_metadata(
                message=message,
                message_id=telegram_message_id,
                extra_metadata=metadata
            )
            if updated_message.content != content:
                updated_message.content = content
                updated_message.save(update_fields=["content", ])

            core_api_logger.info(
                f"{bot_tag} Updated AI message: core_id={core_message_id}, telegram_id={telegram_message_id}"
            )

            return Response({
                "success": True,
                "core_message_id": updated_message.id,
            }, status=status.HTTP_200_OK)

        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Error updating AI message {core_message_id}: {str(e)}")
            return Response({
                "success": False,
                "detail": f"Error updating AI message: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


    @staticmethod
    def _get_or_create_chat(
            user: User,
            assistant_slug: str,
            bot_tag: str,
    ):
        """Получает или создает чат для пользователя с указанным ассистентом"""
        try:
            assistant = AIAssistant.objects.get(slug=assistant_slug, is_active=True)

            chat, created = Chat.get_or_create_ai_chat(
                user=user,
                ai_assistant=assistant,
                platform=ChatPlatform.TELEGRAM,
                title=f"Telegram Чат с {assistant.name}",
            )

            # Добавление пользователя в участники, если чат новый
            if created:
                chat.participants.add(user)
                core_api_logger.info(
                    f"{bot_tag} Создан новый AI-чат {chat.id} для пользователя {user.id} с ассистентом {assistant.slug}")
            else:
                core_api_logger.debug(f"{bot_tag} Найден существующий AI-чат {chat.id} для пользователя {user.id}")

            return chat

        except AIAssistant.DoesNotExist:
            core_api_logger.error(f"{bot_tag} Ассистент с slug {assistant_slug} не найден")
            return Response({
                "success": False,
                "detail": f"Assistant with slug '{assistant_slug}' not found"
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Ошибка при получении/создании чата: {str(e)}")
            return Response({
                "success": False,
                "detail": f"Error getting/creating chat: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

