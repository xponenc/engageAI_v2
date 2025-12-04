from django.db.models import F
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db import transaction

from engageai_core.ai_assistant.models import AIAssistant
from engageai_core.chat.models import Chat, User, Message, MessageSource, ChatPlatform
from engageai_core.chat.services.telegram_message_service import TelegramMessageService
from engageai_core.engageai_core.mixins import InternalBotAuthMixin, TelegramUserMixin
from engageai_core.users.models import TelegramProfile
from utils.setup_logger import setup_logger

core_api_logger = setup_logger(name=__file__, log_dir="logs/core_api", log_file="core_api.log")


class TGUpdateSaveView(InternalBotAuthMixin, TelegramUserMixin, APIView):
    """
    Сохраняет апдейты Telegram: message, edited_message, callback_query.
    Проверяет дубли по external_id и формирует правильный metadata.
    """

    def post(self, request):
        bot = getattr(request, "internal_bot", None)
        bot_tag = f"[bot:{bot}]"

        user = self.get_telegram_user(request)
        if isinstance(user, Response):
            return user

        update_data = request.data.get("update")
        assistant_slug = request.data.get("assistant_slug")

        if not update_data:
            return Response({"success": False, "detail": "Missing update data"}, status=400)

        update_id = update_data.get("update_id")
        if not update_id:
            core_api_logger.warning(f"{bot_tag} Отсутствует update_id")
            return Response({"success": False, "detail": "Missing update_id"}, status=400)

        # Проверка дубля
        if Message.objects.filter(external_id=str(update_id), source_type=MessageSource.TELEGRAM).exists():
            core_api_logger.info(f"{bot_tag} Апдейт {update_id} уже обработан")
            return Response({"success": True, "detail": "Update already processed"}, status=200)

        try:
            if "message" in update_data:
                return self._process_message(update_data["message"], update_id, bot_tag, assistant_slug)
            elif "edited_message" in update_data:
                return self._process_edited_message(update_data["edited_message"], bot_tag, assistant_slug)
            elif "callback_query" in update_data:
                return self._process_callback(update_data["callback_query"], update_id, bot_tag, assistant_slug)
            else:
                core_api_logger.warning(f"{bot_tag} Неизвестный тип апдейта: {list(update_data.keys())}")
                return Response({"success": False, "detail": "Unknown update type"}, status=400)
        except Exception as e:
            core_api_logger.exception(f"{bot_tag} Ошибка обработки апдейта {update_id}: {e}")
            return Response({"success": False, "detail": str(e)}, status=500)

    # ------------------ Вспомогательные методы ------------------

    def _process_message(self, message_data, update_id, bot_tag, assistant_slug):
        from_user = message_data["from"]
        chat_data = message_data["chat"]
        message_id = message_data["message_id"]
        text = message_data.get("text", "")
        entities = message_data.get("entities", [])

        user, _ = self._get_or_create_user(from_user)
        chat = self._get_or_create_chat(chat_data, user, assistant_slug)

        message = TelegramMessageService.create_ai_message(
            chat=chat,
            content=text,
            reply_to=None,
            sender=user
        )
        TelegramMessageService.update_ai_message_metadata(
            message=message,
            update_id=update_id,
            message_id=message_id,
            extra_metadata={
                "entities": entities,
                "chat": chat_data,
                "user": from_user,
                "raw": message_data
            }
        )

        core_api_logger.info(f"{bot_tag} Создано сообщение ID {message.id} ({message_id})")
        return Response({"success": True, "message_id": message.id, "chat_id": chat.id}, status=201)

    def _process_edited_message(self, edited_data, bot_tag, assistant_slug):
        from_user = edited_data["from"]
        chat_data = edited_data["chat"]
        message_id = str(edited_data["message_id"])
        new_text = edited_data.get("text", "")
        edit_time = timezone.datetime.fromtimestamp(edited_data["edit_date"], tz=timezone.utc)

        user, _ = self._get_or_create_user(from_user)
        chat = self._get_or_create_chat(chat_data, user, assistant_slug)

        try:
            message = Message.objects.get(
                metadata__telegram__message_id=message_id,
                chat=chat,
                source_type=MessageSource.TELEGRAM
            )
        except Message.DoesNotExist:
            core_api_logger.warning(f"{bot_tag} Редактирование несуществующего сообщения {message_id}")
            return Response({"success": False, "detail": "Message not found"}, status=404)

        # Сохраняем историю редактирования
        message.add_edit_history(message.content, user.id, edit_time)
        message.content = new_text
        message.edited_at = edit_time
        message.edit_count = F("edit_count") + 1
        message.save(update_fields=["content", "edited_at", "edit_count"])

        core_api_logger.info(f"{bot_tag} Обновлено сообщение ID {message.id}, версия {message.edit_count + 1}")
        return Response({"success": True, "message_id": message.id, "chat_id": chat.id}, status=200)

    def _process_callback(self, callback_data, update_id, bot_tag, assistant_slug):
        from_user = callback_data["from"]
        message_data = callback_data.get("message")
        callback_id = callback_data["id"]
        data = callback_data.get("data")

        user, _ = self._get_or_create_user(from_user)
        chat = self._get_or_create_chat(message_data["chat"], user, assistant_slug)

        original_message = None
        if message_data:
            original_message_id = str(message_data["message_id"])
            try:
                original_message = Message.objects.get(
                    metadata__telegram__message_id=original_message_id,
                    chat=chat,
                    source_type=MessageSource.TELEGRAM
                )
            except Message.DoesNotExist:
                core_api_logger.warning(f"{bot_tag} Не найдено исходное сообщение {original_message_id} для callback {callback_id}")

        callback_message = TelegramMessageService.create_ai_message(
            chat=chat,
            content=f"[Нажата кнопка: {data}]",
            reply_to=original_message,
            sender=user
        )
        TelegramMessageService.update_ai_message_metadata(
            message=callback_message,
            update_id=update_id,
            extra_metadata={
                "callback_query_id": callback_id,
                "callback_data": data,
                "user": from_user,
                "raw": callback_data
            }
        )

        core_api_logger.info(f"{bot_tag} Создан callback-сообщение ID {callback_message.id}")
        return Response({"success": True, "message_id": callback_message.id, "chat_id": chat.id}, status=200)

    # ------------------ Вспомогательные методы ------------------

    @staticmethod
    def _get_or_create_user(user_data):
        telegram_id = str(user_data["id"])
        try:
            user = User.objects.get(telegram_profile__telegram_id=telegram_id)
            return user, False
        except User.DoesNotExist:
            username = f"tg_{telegram_id}"
            user = User.objects.create(
                username=username,
                first_name=user_data.get("first_name", ""),
                last_name=user_data.get("last_name", ""),
                is_active=True
            )
            TelegramProfile.objects.create(user=user, telegram_id=telegram_id, username=user_data.get("username"))
            return user, True

    @staticmethod
    def _get_or_create_chat(chat_data, user, assistant_slug):
        assistant = AIAssistant.objects.get(slug=assistant_slug, is_active=True)
        return Chat.get_or_create_ai_chat(user=user, ai_assistant=assistant, platform=ChatPlatform.TELEGRAM)


class TGMessageSaveView(InternalBotAuthMixin, TelegramUserMixin, APIView):
    """
    Обновляет metadata AI-сообщений, созданных ядром, после их отправки в Telegram.
    Ищет чат пользователя по assistant_slug и telegram_id, обновляет связь между core и Telegram.
    """
    @transaction.atomic
    def post(self, request):
        bot = getattr(request, "internal_bot", None)
        bot_tag = f"[bot:{bot}]"

        user = self.get_telegram_user(request)
        if isinstance(user, Response):
            return user

        payload = request.data

        # Получаем ID сообщения в core, которое нужно обновить
        core_message_id = payload.get("core_message_id")
        if not core_message_id:
            # Создание нового сообщения
            assistant_slug = payload.get("assistant_slug")
            if not assistant_slug:
                core_api_logger.warning(f"{bot_tag} Отсутствуют u assistant_slug")
                return Response({"success": False, "detail": "Missing assistant_slug"},
                                status=status.HTTP_400_BAD_REQUEST)

            try:
                assistant = AIAssistant.objects.get(slug=assistant_slug, is_active=True)
            except AIAssistant.DoesNotExist:
                core_api_logger.error(f"{bot_tag} Ассистент с slug {assistant_slug} не найден")
                return Response({"success": False, "detail": f"Assistant {assistant_slug} not found"},
                                status=status.HTTP_404_NOT_FOUND)

            try:
                # TODO взять meesage_id из raw и проверить
                exist_message = Message.objects.filter(
                    source_type=MessageSource.TELEGRAM,
                    metadata__telegram__message_id=message_id,
                    chat=chat
                ).first()
            except Message.DoesNotExist:
                # TODO создаем новое сообщение
                core_api_logger.error(f"{bot_tag} Сообщение core ID {core_message_id} не найдено")
                return Response({"success": False, "detail": "Core message not found"}, status=status.HTTP_404_NOT_FOUND)

        else:
            exist_message = Message.objects.get(
                id=core_message_id,
            )
            # проверить user - а как? отправлял ведь AI

            # Обновляем сообщение
            telegram_message_id = payload.get("telegram_message_id")
            extra_metadata = payload.get("metadata", {})

            updated_message = TelegramMessageService.update_ai_message_metadata(
                message=ai_message,
                telegram_user_id=user_telegram_id,
                assistant_slug=assistant_slug,
                message_id=telegram_message_id,
                extra_metadata={
                    "chat_id": payload.get("chat_id"),
                    "text": payload.get("text"),
                    **extra_metadata
                }
            )

            core_api_logger.info(f"{bot_tag} Обновлено сообщение core ID {core_message_id} -> Telegram message ID {telegram_message_id}")

            return Response({
                "success": True,
                "ai_message_id": updated_message.id,
                "chat_id": updated_message.chat.id
            }, status=status.HTTP_200_OK)

