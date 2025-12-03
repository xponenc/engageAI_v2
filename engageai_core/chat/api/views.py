from django.contrib.auth import get_user_model
from django.db import transaction, IntegrityError
from django.db.models import F
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ai_assistant.models import AIAssistant
from ..models import Message, MessageSource, Chat, ChatScope, ChatPlatform
from engageai_core.mixins import InternalBotAuthMixin
from users.models import TelegramProfile
from utils.setup_logger import setup_logger

core_api_logger = setup_logger(name=__file__, log_dir="logs/core_api", log_file="core_api.log")

User = get_user_model()


# class TelegramUpdateSaveView(InternalBotAuthMixin, APIView):
#     """
#     Сохраняет входящие апдейты от Telegram.
#
#     Формат ответа совместим с core_post:
#     {
#         "success": True|False,
#         "message_id": id созданного сообщения,
#         "chat_id": id чата,
#         "detail": "технические детали"
#     }
#     """
#
#     @transaction.atomic
#     def post(self, request):
#         bot = request.internal_bot
#         bot_tag = f"[bot:{bot}]"
#         data = request.data
#
#         update_data = data.get("update")
#         assistant_slug = data.get('assistant_slug')
#
#         # Проверка на дубликаты =====
#         update_id = update_data.get('update_id')
#         if not update_id:
#             core_api_logger.warning(f"{bot_tag} Отсутствует update_id в запросе")
#             return Response({
#                 "success": False,
#                 "detail": "Missing update_id"
#             }, status=status.HTTP_400_BAD_REQUEST)
#
#         # Проверяем, не обрабатывали ли уже этот update_id
#         if Message.objects.filter(
#                 external_id=str(update_id),
#                 source_type=MessageSource.TELEGRAM
#         ).exists():
#             core_api_logger.info(f"{bot_tag} Апдейт {update_id} уже обработан")
#             return Response({
#                 "success": True,
#                 "detail": "Update already processed"
#             }, status=status.HTTP_200_OK)
#
#         core_api_logger.info(f"{bot_tag} Начало обработки апдейта {update_id}")
#
#         try:
#             if 'message' in update_data:
#                 return self._process_message_update(update_data, bot_tag, assistant_slug)
#             elif 'edited_message' in update_data:
#                 return self._process_edited_message_update(update_data, bot_tag, assistant_slug)
#             elif 'callback_query' in update_data:
#                 return self._process_callback_update(update_data, bot_tag, assistant_slug)
#             else:
#                 core_api_logger.warning(f"{bot_tag} Неизвестный тип апдейта: {list(update_data.keys())}")
#                 return Response({
#                     "success": False,
#                     "detail": f"Unknown update type: {list(update_data.keys())}"
#                 }, status=status.HTTP_400_BAD_REQUEST)
#
#         except Exception as e:
#             core_api_logger.exception(f"{bot_tag} Критическая ошибка при обработке апдейта {update_id}: {str(e)}")
#             return Response({
#                 "success": False,
#                 "detail": f"Internal server error: {str(e)}"
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#     def _process_message_update(self, update_data, bot_tag, assistant_slug):
#         """Обработка обычного сообщения"""
#         update_id = update_data['update_id']
#         message_data = update_data['message']
#         chat_data = message_data['chat']
#         from_user = message_data['from']
#         message_id = str(message_data['message_id'])
#
#         # Поиск или создание пользователя
#         user, user_created = self._get_or_create_user(from_user, bot_tag)
#         if not user:
#             return Response({
#                 "success": False,
#                 "detail": "Failed to create or find user"
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#         # Поиск или создание чата
#         chat = self._get_or_create_chat(chat_data, user, bot_tag, assistant_slug)
#         if not chat:
#             return Response({
#                 "success": False,
#                 "detail": "Failed to create or find chat"
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#         # Создание сообщения =====
#         text = message_data.get('text', '')
#         entities = message_data.get('entities', [])
#
#         message = Message.objects.create(
#             chat=chat,
#             sender=user,
#             content=text,
#             source_type=MessageSource.TELEGRAM,
#             external_id=update_id,
#             metadata={
#                 'telegram': {
#                     'update_id': update_data['update_id'],
#                     'entities': entities,
#                     'chat': chat_data,
#                     'user': from_user,
#                     'raw': message_data
#                 }
#             }
#         )
#
#         core_api_logger.info(f"{bot_tag} Создано сообщение ID {message.id} в чате {chat} от пользователя {user}")
#
#         return Response({
#             "success": True,
#             "message_id": message.id,
#             "chat_id": chat.id,
#             "detail": "Message processed successfully"
#         }, status=status.HTTP_201_CREATED)
#
#     def _process_edited_message_update(self, update_data, bot_tag, assistant_slug):
#         """Обработка отредактированного сообщения"""
#         edited_data = update_data['edited_message']
#         chat_data = edited_data['chat']
#         from_user = edited_data['from']
#         message_id = str(edited_data['message_id'])
#
#         # Поиск пользователя и чата
#         user, _ = self._get_or_create_user(from_user, bot_tag)
#         if not user:
#             return Response({
#                 "success": False,
#                 "detail": "Failed to create or find user"
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#         chat = self._get_or_create_chat(chat_data, user, bot_tag, assistant_slug)
#         if not chat:
#             return Response({
#                 "success": False,
#                 "detail": "Failed to create or find chat"
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#         # Поиск существующего сообщения
#         try:
#             message = Message.objects.get(
#                 external_id=message_id,
#                 chat=chat,
#                 source_type=MessageSource.TELEGRAM
#             )
#         except Message.DoesNotExist:
#             core_api_logger.warning(f"{bot_tag} Редактирование несуществующего сообщения {message_id}")
#             return Response({
#                 "success": False,
#                 "detail": f"Message {message_id} not found for editing"
#             }, status=status.HTTP_404_NOT_FOUND)
#
#         # Обновление сообщения
#         old_content = message.content
#         new_content = edited_data.get('text', '')
#         edit_time = timezone.datetime.fromtimestamp(
#             edited_data['edit_date'],
#             tz=timezone.utc
#         )
#
#         # Добавляем в историю редактирований
#         message.add_edit_history(old_content, user.id, edit_time)
#
#         # Обновляем основное сообщение
#         message.content = new_content
#         message.edited_at = edit_time
#         message.edit_count = F('edit_count') + 1
#         message.save(update_fields=['content', 'edited_at', 'edit_count'])
#
#         core_api_logger.info(f"{bot_tag} Обновлено сообщение ID {message.id}, версия {message.edit_count + 1}")
#
#         return Response({
#             "success": True,
#             "message_id": message.id,
#             "chat_id": chat.id,
#             "detail": "Message edited successfully"
#         }, status=status.HTTP_200_OK)
#
#     def _process_callback_update(self, update_data, bot_tag, assistant_slug):
#         """Обработка callback-запроса (нажатие на кнопку)"""
#         update_id = update_data['update_id']
#
#         callback_data = update_data['callback_query']
#         message_data = callback_data['message']
#         chat_data = message_data['chat']
#         from_user = callback_data['from']
#         callback_id = callback_data['id']
#         data = callback_data['data']
#
#         # Поиск пользователя и чата
#         user, _ = self._get_or_create_user(from_user, bot_tag)
#         if not user:
#             return Response({
#                 "success": False,
#                 "detail": "Failed to create or find user"
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#         chat = self._get_or_create_chat(chat_data, user, bot_tag, assistant_slug)
#         if not chat:
#             return Response({
#                 "success": False,
#                 "detail": "Failed to create or find chat"
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#         # Создание сообщения-действия
#         # Ищем исходное сообщение с кнопками
#         try:
#             original_message = Message.objects.get(
#                 external_id=str(message_data['message_id']),
#                 chat=chat,
#                 source_type=MessageSource.TELEGRAM
#             )
#         except Message.DoesNotExist:
#             core_api_logger.warning(f"{bot_tag} Не найдено исходное сообщение для callback {callback_id}")
#             original_message = None
#
#         # Создаем новое сообщение для действия пользователя
#         callback_message = Message.objects.create(
#             chat=chat,
#             sender=user,
#             content=f"[Нажата кнопка: {data}]",
#             source_type=MessageSource.TELEGRAM,
#             external_id=update_id,
#             metadata={
#                 'telegram': {
#                     'callback_query_id': callback_id,
#                     'callback_data': data,
#                     'original_message_id': message_data['message_id'] if original_message else None,
#                     'user': from_user,
#                     'raw': callback_data
#                 }
#             }
#         )
#
#         core_api_logger.info(f"{bot_tag} Создано callback-сообщение ID {callback_message.id} для действия {data}")
#
#         return Response({
#             "success": True,
#             "message_id": callback_message.id,
#             "chat_id": chat.id,
#             "detail": f"Callback processed: {data}"
#         }, status=status.HTTP_200_OK)
#
#     @staticmethod
#     def _get_or_create_user(telegram_user_data, bot_tag):
#         """Получение или создание пользователя по данным из Telegram"""
#         telegram_id = str(telegram_user_data['id'])
#
#         try:
#             # Ищем через Telegram профиль
#             user = User.objects.get(telegram_profile__telegram_id=telegram_id)
#             core_api_logger.debug(f"{bot_tag} Найден существующий пользователь ID {user.id} для telegram_id {telegram_id}")
#             return user, False
#         except User.DoesNotExist:
#             # Создаем нового пользователя
#             username = f"tg_{telegram_id}"
#             first_name = telegram_user_data.get('first_name', '')
#             last_name = telegram_user_data.get('last_name', '')
#
#             try:
#                 user = User.objects.create(
#                     username=username,
#                     first_name=first_name,
#                     last_name=last_name,
#                     is_active=True
#                 )
#
#                 # Создаем Telegram профиль
#                 TelegramProfile.objects.create(
#                     user=user,
#                     telegram_id=telegram_id,
#                     username=telegram_user_data.get('username')
#                 )
#
#                 core_api_logger.info(f"{bot_tag} Создан новый пользователь ID {user.id} для telegram_id {telegram_id}")
#                 return user, True
#             except IntegrityError:
#                 # Возможна гонка при создании пользователя
#                 user = User.objects.get(username=username)
#                 core_api_logger.warning(f"{bot_tag} Пользователь {username} был создан конкурентно")
#                 return user, False
#             except Exception as e:
#                 core_api_logger.error(f"{bot_tag} Ошибка создания пользователя для telegram_id {telegram_id}: {str(e)}")
#                 return None, False
#
#     @staticmethod
#     def _get_or_create_chat(chat_data, user, bot_tag, assistant_slug:str):
#         """Получение или создание чата по данным из Telegram"""
#         telegram_chat_id = str(chat_data['id'])
#         chat_type = chat_data['type']
#
#         # Определяем тип чата для нашей системы на TODO
#         if chat_type in ['private', 'sender']:
#             chat_type_internal = ChatScope.PRIVATE
#         elif chat_type in ['group', 'supergroup', 'channel']:
#             chat_type_internal = ChatScope.GROUP
#         else:
#             chat_type_internal = ChatScope.PRIVATE
#
#         try:
#             assistant = AIAssistant.objects.get(slug=assistant_slug, is_active=True)
#             chat = Chat.get_or_create_ai_chat(
#                 user=user,
#                 ai_assistant=assistant,
#                 platform=ChatPlatform.TELEGRAM
#             )
#             core_api_logger.debug(
#                 f"{bot_tag} Найден существующий {chat} c {assistant} для {user}")
#             return chat
#
#         except AIAssistant.DoesNotExist:
#             return None


from django.db import transaction, IntegrityError
from django.db.models import F
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ai_assistant.models import AIAssistant
from ..models import Message, MessageSource, Chat, ChatScope, ChatPlatform
from users.models import TelegramProfile
from utils.setup_logger import setup_logger

core_api_logger = setup_logger(name=__file__, log_dir="logs/core_api", log_file="core_api.log")


class TelegramUpdateSaveView(APIView):
    """
    Сохраняет апдейты Telegram: message, edited_message, callback_query.
    """

    @transaction.atomic
    def post(self, request):
        bot_tag = "[TelegramBot]"
        data = request.data
        update_data = data.get("update")
        assistant_slug = data.get("assistant_slug")

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

    def _process_message(self, message_data, update_id, bot_tag, assistant_slug):
        """Обычное сообщение"""
        chat_data = message_data["chat"]
        from_user = message_data["from"]
        message_id = str(message_data["message_id"])
        text = message_data.get("text", "")
        entities = message_data.get("entities", [])

        user, _ = self._get_or_create_user(from_user, bot_tag)
        chat = self._get_or_create_chat(chat_data, user, bot_tag, assistant_slug)

        message = Message.objects.create(
            chat=chat,
            sender=user,
            content=text,
            source_type=MessageSource.TELEGRAM,
            external_id=str(update_id),
            metadata={
                "telegram": {
                    "update_id": update_id,
                    "message_id": message_id,
                    "entities": entities,
                    "chat": chat_data,
                    "user": from_user,
                    "raw": message_data
                }
            }
        )

        core_api_logger.info(f"{bot_tag} Создано сообщение ID {message.id} ({message_id})")
        return Response({"success": True, "message_id": message.id, "chat_id": chat.id}, status=201)

    def _process_edited_message(self, edited_data, bot_tag, assistant_slug):
        """Редактирование обычного сообщения"""
        chat_data = edited_data["chat"]
        from_user = edited_data["from"]
        message_id = str(edited_data["message_id"])
        new_text = edited_data.get("text", "")
        edit_time = timezone.datetime.fromtimestamp(edited_data["edit_date"], tz=timezone.utc)

        user, _ = self._get_or_create_user(from_user, bot_tag)
        chat = self._get_or_create_chat(chat_data, user, bot_tag, assistant_slug)

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
        """Callback-запрос (нажатие кнопки)"""
        from_user = callback_data["from"]
        message_data = callback_data.get("message")
        callback_id = callback_data["id"]
        data = callback_data.get("data")

        user, _ = self._get_or_create_user(from_user, bot_tag)
        chat = self._get_or_create_chat(message_data["chat"], user, bot_tag, assistant_slug)

        original_message = None
        original_message_id = None
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

        callback_message = Message.objects.create(
            chat=chat,
            sender=user,
            content=f"[Нажата кнопка: {data}]",
            source_type=MessageSource.TELEGRAM,
            external_id=str(update_id),
            metadata={
                "telegram": {
                    "update_id": update_id,
                    "callback_query_id": callback_id,
                    "callback_data": data,
                    "original_message_id": original_message_id if original_message else None,
                    "user": from_user,
                    "raw": callback_data
                }
            }
        )

        core_api_logger.info(f"{bot_tag} Создан callback-сообщение ID {callback_message.id}")
        return Response({"success": True, "message_id": callback_message.id, "chat_id": chat.id}, status=200)

    @staticmethod
    def _get_or_create_user(user_data, bot_tag):
        telegram_id = str(user_data["id"])
        try:
            user = User.objects.get(telegram_profile__telegram_id=telegram_id)
            return user, False
        except User.DoesNotExist:
            username = f"tg_{telegram_id}"
            user = User.objects.create(username=username, first_name=user_data.get("first_name", ""),
                                       last_name=user_data.get("last_name", ""), is_active=True)
            TelegramProfile.objects.create(user=user, telegram_id=telegram_id, username=user_data.get("username"))
            return user, True

    @staticmethod
    def _get_or_create_chat(chat_data, user, bot_tag, assistant_slug):
        telegram_chat_id = str(chat_data["id"])
        chat_type = chat_data.get("type", "private")
        chat_scope = ChatScope.PRIVATE if chat_type in ["private", "sender"] else ChatScope.GROUP
        assistant = AIAssistant.objects.get(slug=assistant_slug, is_active=True)
        return Chat.get_or_create_ai_chat(user=user, ai_assistant=assistant, platform=ChatPlatform.TELEGRAM)

