# import json
# from django.utils import timezone
#
# from engageai_core.chat.models import MessageSource, Message, ChatType, Chat
# from engageai_core.users.models import TelegramProfile
#
#
# def process_telegram_update(update):
#     """
#     Универсальный обработчик Telegram-апдейтов
#
#     Args:
#         update (dict): Полный объект обновления от Telegram API
#
#     Returns:
#         Message: Созданное/обновленное сообщение или None
#     """
#     # 1. Определяем тип обновления
#     if 'message' in update:
#         return _process_message_update(update['message'], update_id=update['update_id'])
#
#     elif 'callback_query' in update:
#         return _process_callback_update(update['callback_query'])
#
#     elif 'edited_message' in update:
#         return _process_edited_message(update['edited_message'])
#
#     return None
#
#
# def _process_message_update(telegram_message, update_id=None):
#     """Обработка обычного сообщения"""
#     try:
#         # 2. Извлекаем ключевые данные
#         chat_id = str(telegram_message['chat']['id'])
#         message_id = str(telegram_message['message_id'])
#         text = telegram_message.get('text', '')
#         from_user = telegram_message['from']
#         entities = telegram_message.get('entities', [])
#
#         # 3. Находим или создаем чат
#         chat, created = Chat.objects.get_or_create(
#             telegram_chat_id=chat_id,
#             defaults={
#                 'type': ChatType.TELEGRAM,
#                 'title': telegram_message['chat'].get('title', 'Личный чат'),
#                 'created_at': timezone.now()
#             }
#         )
#
#         # 4. Находим или создаем пользователя (упрощенный пример)
#         user = get_or_create_telegram_user(from_user)
#         chat.participants.add(user)
#
#         # 5. Проверяем, не существует ли уже такое сообщение
#         message, created = Message.objects.get_or_create(
#             external_id=message_id,
#             defaults={
#                 'chat': chat,
#                 'sender': user,
#                 'content': text,
#                 'source_type': MessageSource.TELEGRAM,
#                 'timestamp': timezone.datetime.fromtimestamp(telegram_message['date'], tz=timezone.utc),
#                 'metadata': {
#                     'telegram': {
#                         'update_id': update_id,
#                         'entities': entities,
#                         'chat': {
#                             'id': chat_id,
#                             'type': telegram_message['chat']['type'],
#                             'title': telegram_message['chat'].get('title')
#                         },
#                         'user': {
#                             'id': from_user['id'],
#                             'username': from_user.get('username'),
#                             'first_name': from_user['first_name'],
#                             'last_name': from_user.get('last_name')
#                         },
#                         'raw': telegram_message  # ← Сохраняем полные сырые данные для отладки
#                     }
#                 }
#             }
#         )
#
#         # 6. Если сообщение уже существовало (при повторной отправке)
#         if not created:
#             # Обновляем только если изменилось содержимое
#             if message.content != text:
#                 message.content = text
#                 message.metadata['telegram']['entities'] = entities
#                 message.save(update_fields=['content', 'metadata'])
#
#         # 7. Запускаем асинхронную обработку для AI
#         if text.strip():
#             process_with_ai.delay(message.id)  # Celery задача
#
#         return message
#
#     except Exception as e:
#         logger.error(f"Ошибка обработки сообщения {update_id}: {str(e)}")
#         logger.error(f"Полные данные: {json.dumps(telegram_message, indent=2)}")
#         raise
#
#
# def _process_callback_update(callback):
#     """Обработка callback-запроса от inline-кнопок"""
#     try:
#         # 1. Извлекаем данные
#         message_data = callback['message']
#         callback_data = callback['data']
#         chat_id = str(message_data['chat']['id'])
#         message_id = str(message_data['message_id'])
#
#         # 2. Находим чат
#         chat = Chat.objects.get(telegram_chat_id=chat_id)
#
#         # 3. Находим исходное сообщение с кнопками
#         original_message = Message.objects.get(
#             external_id=message_id,
#             chat=chat
#         )
#
#         # 4. Создаем новое сообщение для действия пользователя
#         user = get_or_create_telegram_user(callback['from'])
#         callback_message = Message.objects.create(
#             chat=chat,
#             sender=user,
#             content=f"[Нажата кнопка: {callback_data}]",
#             source_type=MessageSource.TELEGRAM,
#             external_id=f"callback_{callback['id']}",
#             metadata={
#                 'telegram': {
#                     'callback_query_id': callback['id'],
#                     'callback_data': callback_data,
#                     'original_message_id': message_id,
#                     'user': {
#                         'id': callback['from']['id'],
#                         'username': callback['from'].get('username')
#                     }
#                 }
#             }
#         )
#
#         # 5. Обрабатываем действие кнопки
#         handle_callback_action(callback_data, chat, user, original_message)
#
#         return callback_message
#
#     except Chat.DoesNotExist:
#         logger.warning(f"Чат не найден для callback: {chat_id}")
#         return None
#     except Message.DoesNotExist:
#         logger.warning(f"Исходное сообщение не найдено для callback: {message_id}")
#         return None
#
#
# def handle_callback_action(action, chat, user, original_message):
#     """Логика обработки разных действий кнопок"""
#     if action.startswith('ai_'):
#         # Запрос к AI с контекстом
#         context = original_message.content
#         ai_response = call_ai_api(f"{context}\n\nПользователь выбрал: {action[3:]}")
#
#         # Отправляем ответ в Telegram
#         send_telegram_message(
#             chat_id=chat.telegram_chat_id,
#             text=ai_response,
#             reply_to_message_id=original_message.external_id
#         )
#
#         # Сохраняем ответ AI
#         Message.objects.create(
#             chat=chat,
#             content=ai_response,
#             is_ai=True,
#             source_type=MessageSource.SYSTEM
#         )
#
#     elif action == 'confirm_action':
#         # Подтверждение какого-то действия
#         send_telegram_message(
#             chat_id=chat.telegram_chat_id,
#             text="✅ Действие подтверждено!",
#             reply_to_message_id=original_message.external_id
#         )
#
#
# # Вспомогательные функции
# def get_or_create_telegram_user(telegram_user_data):
#     """Создание/получение пользователя по данным из Telegram"""
#     from django.contrib.auth import get_user_model
#     User = get_user_model()
#
#     telegram_id = str(telegram_user_data['id'])
#
#     # Ищем через профиль или создаем нового пользователя
#     try:
#         return User.objects.get(telegramprofile__telegram_id=telegram_id)
#     except User.DoesNotExist:
#         # Создаем нового пользователя
#         username = f"tg_{telegram_id}"
#         user, created = User.objects.get_or_create(
#             username=username,
#             defaults={
#                 'first_name': telegram_user_data.get('first_name', ''),
#                 'last_name': telegram_user_data.get('last_name', '')
#             }
#         )
#
#         # Создаем Telegram-профиль
#         TelegramProfile.objects.get_or_create(
#             user=user,
#             defaults={'telegram_id': telegram_id}
#         )
#
#         return user
#
#
# def _process_edited_message(telegram_message):
#     """
#     Обработка отредактированного сообщения из Telegram
#
#     Args:
#         telegram_message (dict): Данные отредактированного сообщения из Telegram API
#
#     Returns:
#         Message: Обновленное сообщение или None
#     """
#     try:
#         # 1. Извлекаем ключевые данные
#         chat_id = str(telegram_message['chat']['id'])
#         message_id = str(telegram_message['message_id'])
#         new_text = telegram_message.get('text', '')
#         edit_date = timezone.datetime.fromtimestamp(
#             telegram_message['edit_date'],
#             tz=timezone.utc
#         )
#         from_user_id = telegram_message['from']['id']
#
#         # 2. Находим чат
#         try:
#             chat = Chat.objects.get(telegram_chat_id=chat_id)
#         except Chat.DoesNotExist:
#             logger.warning(f"Чат не найден для редактирования: {chat_id}")
#             return None
#
#         # 3. Находим исходное сообщение
#         try:
#             message = Message.objects.get(
#                 external_id=message_id,
#                 chat=chat,
#                 source_type=MessageSource.TELEGRAM
#             )
#         except Message.DoesNotExist:
#             logger.warning(f"Сообщение для редактирования не найдено: {message_id}")
#             # Если сообщение не найдено, создаем как новое
#             return _process_message_update(telegram_message)
#
#         # 4. Проверяем, действительно ли изменился текст
#         if message.content == new_text:
#             logger.info(f"Сообщение {message_id} отредактировано без изменений")
#             return message
#
#         # 5. Добавляем текущую версию в историю
#         old_content = message.content
#         message.add_edit_history(
#             old_content=old_content,
#             editor_id=from_user_id,
#             edit_time=edit_date
#         )
#
#         # 6. Обновляем основное сообщение
#         message.content = new_text
#         message.edited_at = edit_date
#         message.edit_count = models.F('edit_count') + 1
#
#         # 7. Обновляем метаданные с entities
#         telegram_data = message.get_telegram_data()
#         telegram_data['entities'] = telegram_message.get('entities', [])
#         telegram_data['last_edit'] = {
#             'timestamp': edit_date.isoformat(),
#             'editor_id': from_user_id
#         }
#         message.metadata['telegram'] = telegram_data
#
#         # 8. Сохраняем изменения
#         message.save(update_fields=[
#             'content', 'edited_at', 'edit_count', 'metadata'
#         ])
#
#         logger.info(f"Сообщение {message_id} отредактировано. Версия: {message.edit_count + 1}")
#
#         # 9. Запускаем повторную обработку для AI (если нужно)
#         if should_reprocess_with_ai(message, old_content, new_text):
#             process_with_ai.delay(message.id, force_update=True)
#
#         return message
#
#     except Exception as e:
#         logger.error(f"Ошибка обработки отредактированного сообщения: {str(e)}")
#         logger.error(f"Данные: {json.dumps(telegram_message, indent=2)}")
#         raise
#
# # def process_ai_command(message, entity):
# #     """Обработка команды для AI из Telegram"""
# #     command = message.content[entity['offset']:entity['offset'] + entity['length']]
# #
# #     if command == '/start':
# #         ai_response = "Привет! Я AI-помощник. Чем я могу вам помочь сегодня?"
# #     elif command == '/help':
# #         ai_response = "Доступные команды:\n/start - начать диалог\n/help - показать помощь"
# #     else:
# #         # Обращение к AI API
# #         ai_response = call_ai_api(message.content)
# #
# #     # 5. Отправляем ответ обратно в Telegram
# #     chat_data = message.get_telegram_data()['chat']
# #     send_telegram_message(
# #         chat_id=chat_data['id'],
# #         text=ai_response,
# #         reply_to_message_id=message.external_id
# #     )
# #
# #     # 6. Сохраняем ответ AI в чат
# #     Message.objects.create(
# #         chat=message.chat,
# #         content=ai_response,
# #         is_ai=True,
# #         source_type=MessageSource.SYSTEM  # Ответ от системы
# #     )