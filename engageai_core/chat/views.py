import json
import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone

from django.views import View
from django.views.generic import ListView

from ai.orchestrator import Orchestrator
from ai_assistant.models import AIAssistant
from .models import Chat, Message, MessageSource, ChatPlatform, MessageType
from chat.services.interfaces.ai_message_service import AiMediaService
from .services.interfaces.chat_service import ChatService
from .services.interfaces.exceptions import AssistantNotFoundError, ChatCreationError, MediaProcessingError
from .services.interfaces.message_service import MessageService
from .services.user_media_service import UserMediaService

logger = logging.getLogger(__name__)


# class AiChatView(LoginRequiredMixin, View):
#     """Базовый чат с AI"""
#     template_name = "chat/ai_chat.html"
#
#     def _get_assistant_and_chat(self, request, slug):
#         """Получает AI-ассистента и чат с обработкой ошибок"""
#         try:
#             assistant = AIAssistant.objects.get(slug=slug, is_active=True)
#         except AIAssistant.DoesNotExist:
#             raise Http404("AI-ассистент не найден или неактивен")
#
#         try:
#             chat = Chat.get_or_create_ai_chat(
#                 user=request.user,
#                 ai_assistant=assistant,
#                 platform=ChatPlatform.WEB,
#             )
#             return assistant, chat
#         except Exception as e:
#             # logger.error(f"Ошибка при создании чата: {str(e)}")
#             raise Http404("Не удалось создать чат с AI-ассистентом")
#
#     def _get_ajax_response(self, user_message_text, ai_message, request):
#         """Формирует AJAX-ответ для чата с поддержкой медиа"""
#         response_data = {
#             'user_message': user_message_text,
#             'ai_response': {
#                 "id": ai_message.pk,
#                 "score": None,
#                 "request_url": reverse_lazy("chat:ai-message-score", kwargs={"message_pk": ai_message.pk}),
#                 "text": ai_message.content,
#                 "message_type": ai_message.message_type,
#                 "media_files": [
#                     {
#                         "url": media.get_absolute_url(),
#                         "type": media.file_type,
#                         "mime_type": media.mime_type
#                     } for media in ai_message.media_files.all()
#                 ]
#             },
#         }
#         return JsonResponse(response_data)
#
#     def _process_ai_response(self, chat, user_message_text, media_files=None):
#         """Обрабатывает запрос к AI и возвращает ответ"""
#
#         try:
#             orchestrator = Orchestrator(chat=chat)
#
#             # Подготавливаем расширенный контекст с медиа
#             user_context = {
#                 'text': user_message_text,
#                 'media': [
#                     {
#                         'url': media.get_absolute_url(),
#                         'type': media.file_type,
#                         'mime_type': media.mime_type,
#                         'path': media.file.path if hasattr(media.file, 'path') else None
#                     } for media in media_files
#                 ] if media_files else []
#             }
#
#             # Получаем ответ от AI с возможными медиа
#             ai_response = orchestrator.process_message(user_context)
#
#             if not ai_response.get('success', False):
#                 return "Извините, произошла ошибка при генерации ответа.", []
#
#             return ai_response.get('response_message',
#                                    "Извините, я пока не могу ответить на ваш вопрос."), ai_response.get('media_files',
#                                                                                                         [])
#
#         except Exception as e:
#             # logger.exception(f"Ошибка при работе с AI: {str(e)}")
#             return "Извините, сейчас не могу обработать ваш запрос.", []
#
#     def _handle_media_files(self, request, message):
#         """Обрабатывает загрузку медиафайлов"""
#         media_objects = []
#         media_files = request.FILES.getlist('media_files')  # Получаем загруженные файлы
#
#         for media_file in media_files:
#             # Валидация файла
#             if media_file.size > 10 * 1024 * 1024:  # 10MB limit
#                 continue
#
#             # Определяем тип файла
#             file_type = self._determine_file_type(media_file)
#             if file_type not in ['image', 'audio', 'video', 'document']:
#                 continue
#
#             # Сохраняем файл
#             media_obj = MediaFile.objects.create(
#                 file=media_file,
#                 file_type=file_type,
#                 mime_type=media_file.content_type,
#                 size=media_file.size,
#                 created_by=request.user
#             )
#             media_objects.append(media_obj)
#
#         # Связываем медиа с сообщением
#         if media_objects:
#             message.media_files.add(*media_objects)
#             # Обновляем тип сообщения
#             if any(m.file_type == 'image' for m in media_objects):
#                 message.message_type = MessageType.IMAGE
#             elif any(m.file_type == 'audio' for m in media_objects):
#                 message.message_type = MessageType.AUDIO
#             elif any(m.file_type == 'video' for m in media_objects):
#                 message.message_type = MessageType.VIDEO
#             elif any(m.file_type == 'document' for m in media_objects):
#                 message.message_type = MessageType.DOCUMENT
#
#         message.save()
#         return media_objects
#
#     def _determine_file_type(self, file):
#         """Определяет тип файла по расширению"""
#         extension = file.name.split('.')[-1].lower()
#         if extension in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp']:
#             return 'image'
#         elif extension in ['mp3', 'wav', 'ogg', 'm4a']:
#             return 'audio'
#         elif extension in ['mp4', 'avi', 'mov', 'wmv']:
#             return 'video'
#         else:
#             return 'document'
#
#     def get(self, request, slug, *args, **kwargs):
#         """Отображает интерфейс чата с историей сообщений"""
#         try:
#             assistant, (chat, created) = self._get_assistant_and_chat(request, slug)
#         except Http404 as e:
#             return render(request, "chat/assistant_not_found.html", {"error": str(e)}, status=404)
#         print(chat)
#
#         # Получаем историю сообщений с пагинацией для производительности
#         chat_history = chat.messages.filter(
#             is_user_deleted=False
#         ).order_by("created_at").select_related('sender')
#
#         context = {
#             'chat': chat,
#             'chat_history': chat_history,
#             'assistant': assistant,
#         }
#         return render(request, self.template_name, context)
#
#     def post(self, request, slug, *args, **kwargs):
#         """Обрабатывает отправку сообщения в чат"""
#         user_message_text = request.POST.get('message', '').strip()
#         has_media = bool(request.FILES.getlist('media_files'))
#
#         # Валидация сообщения
#         if not user_message_text and not has_media:
#             if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
#                 return JsonResponse({"error": "Сообщение или файлы отсутствуют"}, status=400)
#             return redirect('chat:ai-chat', slug=slug)
#
#         # if len(user_message_text) > 2000:
#         #     if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
#         #         return JsonResponse({"error": "Сообщение слишком длинное"}, status=400)
#         #     return redirect('chat:ai-chat', slug=slug)
#
#         # Получаем ассистента и чат
#         try:
#             assistant, (chat, created) = self._get_assistant_and_chat(request, slug)
#         except Http404 as e:
#             if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
#                 return JsonResponse({"error": str(e)}, status=404)
#             return render(request, "chat/assistant_not_found.html", {"error": str(e)}, status=404)
#
#         user_message = Message.objects.create(
#             chat=chat,
#             content=user_message_text,
#             source_type=MessageSource.WEB,
#             sender=self.request.user,
#             message_type=MessageType.TEXT
#         )
#
#         # Обрабатываем медиафайлы, если есть
#         media_objects = []
#         if has_media:
#             media_objects = self._handle_media_files(request, user_message)
#
#         # Генерируем ответ от AI
#         ai_message_text, ai_media_files = self._process_ai_response(chat, user_message_text, media_objects)
#
#         ai_message = Message.objects.create(
#             chat=chat,
#             reply_to=user_message,
#             content=ai_message_text,
#             is_ai=True,
#             source_type=MessageSource.WEB,
#             sender=None,
#             message_type=MessageType.TEXT  # По умолчанию текст
#         )
#
#         # Обрабатываем медиафайлы от AI
#         if ai_media_files:
#             ai_media_objects = []
#             for media_data in ai_media_files:
#                 # Создаем объекты MediaFile для сгенерированных AI файлов
#                 # Здесь предполагается, что ai_media_files содержит URL или пути к файлам
#                 media_obj = MediaFile.objects.create(
#                     file=media_data['path'],
#                     file_type=media_data['type'],
#                     mime_type=media_data['mime_type'],
#                     size=media_data['size'],
#                     ai_generated=True
#                 )
#                 ai_media_objects.append(media_obj)
#
#             ai_message.media_files.add(*ai_media_objects)
#             # Обновляем тип сообщения AI
#             if ai_media_objects:
#                 ai_message.message_type = self._determine_message_type(ai_media_objects)
#             ai_message.save()
#
#         # Обрабатываем AJAX-запрос
#         if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
#             return self._get_ajax_response(user_message_text, ai_message, request)
#
#         return redirect('chat:ai-chat', slug=slug)

# class AiChatView(LoginRequiredMixin, View):
#     """Чат с AI с полной поддержкой медиафайлов"""
#     template_name = "chat/ai_chat.html"
#
#     def _get_assistant_and_chat(self, request, slug):
#         """Получает AI-ассистента и чат с обработкой ошибок"""
#         try:
#             assistant = AIAssistant.objects.get(slug=slug, is_active=True)
#         except AIAssistant.DoesNotExist:
#             raise Http404("AI-ассистент не найден или неактивен")
#
#         try:
#             chat, created = Chat.get_or_create_ai_chat(
#                 user=request.user,
#                 ai_assistant=assistant,
#                 platform=ChatPlatform.WEB,
#             )
#             return assistant, (chat, created)
#         except Exception as e:
#             # logger.error(f"Ошибка при создании чата: {str(e)}")
#             raise Http404("Не удалось создать чат с AI-ассистентом")
#
#     def _get_ajax_response(self, user_message, ai_message):
#         """Формирует AJAX-ответ для чата с поддержкой медиа"""
#         # Получаем медиафайлы пользователя
#         user_media = [{
#             "url": media.get_absolute_url(),
#             "type": media.file_type,
#             "mime_type": media.mime_type,
#             "name": os.path.basename(media.file.name)
#         } for media in user_message.media_files.all()]
#
#         # Получаем медиафайлы AI
#         ai_media = [{
#             "url": media.get_absolute_url(),
#             "type": media.file_type,
#             "mime_type": media.mime_type,
#             "name": os.path.basename(media.file.name),
#             "thumbnail": media.thumbnail.url if media.thumbnail else None
#         } for media in ai_message.media_files.all()]
#
#         response_data = {
#             'user_message': {
#                 "id": user_message.pk,
#                 "text": user_message.content,
#                 "media_files": user_media
#             },
#             'ai_response': {
#                 "id": ai_message.pk,
#                 "score": ai_message.score,
#                 "request_url": reverse_lazy("chat:ai-message-score", kwargs={"message_pk": ai_message.pk}),
#                 "text": ai_message.content,
#                 "message_type": ai_message.message_type,
#                 "media_files": ai_media
#             },
#         }
#         return JsonResponse(response_data)
#
#     def _determine_message_type(self, media_files):
#         """Определяет тип сообщения на основе прикрепленных медиафайлов"""
#         if not media_files:
#             return MessageType.TEXT
#
#         for media in media_files:
#             if media.file_type == 'image':
#                 return MessageType.IMAGE
#             elif media.file_type == 'audio':
#                 return MessageType.AUDIO
#             elif media.file_type == 'video':
#                 return MessageType.VIDEO
#             elif media.file_type == 'document':
#                 continue
#
#         return MessageType.DOCUMENT
#
#     def _save_ai_generated_media(self, media_data, ai_message):
#         """Сохраняет медиафайлы, сгенерированные AI"""
#         media_objects = []
#
#         for item in media_data:
#             try:
#                 # Скачиваем файл по URL
#                 response = requests.get(item['url'], timeout=30)
#                 response.raise_for_status()
#
#                 # Генерируем уникальное имя файла
#                 ext = os.path.splitext(urlparse(item['url']).path)[1] or '.bin'
#                 filename = f"ai_generated/{uuid.uuid4()}{ext}"
#
#                 # Сохраняем файл
#                 file_content = ContentFile(response.content)
#                 file_path = default_storage.save(filename, file_content)
#
#                 # Определяем тип файла
#                 file_type = get_file_type_from_mime(item.get('mime_type', ''))
#                 if not file_type:
#                     file_type = self._determine_file_type_by_extension(ext)
#
#                 # Создаем объект MediaFile
#                 media_obj = MediaFile.objects.create(
#                     file=file_path,
#                     file_type=file_type,
#                     mime_type=item.get('mime_type', 'application/octet-stream'),
#                     size=len(response.content),
#                     ai_generated=True,
#                     created_by=ai_message.chat.user
#                 )
#
#                 # Генерируем миниатюру для изображений
#                 if file_type == 'image':
#                     generate_thumbnail(media_obj)
#
#                 media_objects.append(media_obj)
#
#             except Exception as e:
#                 # logger.error(f"Ошибка при сохранении медиа от AI: {str(e)}")
#                 continue
#
#         if media_objects:
#             ai_message.media_files.add(*media_objects)
#             return media_objects
#         return []
#
#     def _determine_file_type_by_extension(self, ext):
#         """Определяет тип файла по расширению"""
#         ext = ext.lower().strip('.')
#         if ext in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg']:
#             return 'image'
#         elif ext in ['mp3', 'wav', 'ogg', 'm4a', 'aac', 'flac']:
#             return 'audio'
#         elif ext in ['mp4', 'avi', 'mov', 'wmv', 'mkv', 'webm']:
#             return 'video'
#         return 'document'
#
#     def _handle_uploaded_file(self, request, message):
#         """Обрабатывает загруженный файл из запроса"""
#         uploaded_file = request.FILES.get('file')  # Имя поля из формы
#         if not uploaded_file:
#             return []
#
#         # Валидация размера файла
#         max_size = 25 * 1024 * 1024  # 25MB
#         if uploaded_file.size > max_size:
#             raise ValueError(f"Размер файла превышает максимально допустимый ({max_size // 1024 // 1024}MB)")
#
#         # Валидация типа файла
#         if not validate_file_type(uploaded_file):
#             raise ValueError("Недопустимый тип файла")
#
#         # Определяем тип файла
#         file_type = get_file_type_from_mime(uploaded_file.content_type)
#         if not file_type:
#             file_type = self._determine_file_type_by_extension(uploaded_file.name)
#         print(f'{file_type=}')
#         try:
#             with transaction.atomic():
#                 # Создаем объект MediaFile
#                 media_obj = MediaFile.objects.create(
#                     message=message,
#                     file=uploaded_file,
#                     file_type=file_type,
#                     mime_type=uploaded_file.content_type,
#                     size=uploaded_file.size,
#                     created_by=request.user
#                 )
#
#                 # Генерируем миниатюру для изображений
#                 if file_type == 'image':
#                     two_generate_thumbnail(media_obj, uploaded_file)
#
#                 # Связываем с сообщением
#                 message.media_files.add(media_obj)
#
#                 # Обновляем тип сообщения
#                 if file_type == 'image':
#                     message.message_type = MessageType.IMAGE
#                 elif file_type == 'audio':
#                     message.message_type = MessageType.AUDIO
#                 elif file_type == 'video':
#                     message.message_type = MessageType.VIDEO
#                 else:
#                     message.message_type = MessageType.DOCUMENT
#
#                 message.save()
#                 return [media_obj]
#
#         except Exception as e:
#             # logger.error(f"Ошибка при сохранении файла: {str(e)}")
#             print(f"Ошибка при сохранении файла: {str(e)}")
#             raise
#
#     def _process_ai_response(self, chat, user_context):
#         """Обрабатывает запрос к AI и возвращает ответ с медиа"""
#         try:
#             orchestrator = Orchestrator(chat=chat)
#             ai_response = orchestrator.process_message(user_context)
#
#             if not ai_response.get('success', False):
#                 return {
#                     'text': "Извините, произошла ошибка при генерации ответа.",
#                     'media': []
#                 }
#
#             return {
#                 'text': ai_response.get('response_message', "Извините, я пока не могу ответить на ваш вопрос."),
#                 'media': ai_response.get('media_files', [])
#             }
#
#         except Exception as e:
#             # logger.exception(f"Ошибка при работе с AI: {str(e)}")
#             return {
#                 'text': "Извините, сейчас не могу обработать ваш запрос.",
#                 'media': []
#             }
#
#     def get(self, request, slug, *args, **kwargs):
#         """Отображает интерфейс чата с историей сообщений"""
#         try:
#             assistant, (chat, created) = self._get_assistant_and_chat(request, slug)
#         except Http404 as e:
#             return render(request, "chat/assistant_not_found.html", {"error": str(e)}, status=404)
#
#         # Получаем историю сообщений с предзагрузкой медиа
#         chat_history = chat.messages.filter(
#             is_user_deleted=False
#         ).order_by("created_at").select_related('sender').prefetch_related('media_files')
#
#         context = {
#             'chat': chat,
#             'chat_history': chat_history,
#             'assistant': assistant,
#         }
#         return render(request, self.template_name, context)
#
#     def post(self, request, slug, *args, **kwargs):
#         """Обрабатывает отправку сообщения в чат с поддержкой медиа"""
#         user_message_text = request.POST.get('message', '').strip()
#         has_file = 'file' in request.FILES
#
#         print(request.POST)
#         print(request.FILES)
#
#         # Валидация: должно быть либо текст, либо файл
#         if not user_message_text and not has_file:
#             if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
#                 return JsonResponse({"error": "Сообщение или файл отсутствуют"}, status=400)
#             return redirect('chat:ai-chat', slug=slug)
#
#         # Получаем ассистента и чат
#         try:
#             assistant, (chat, created) = self._get_assistant_and_chat(request, slug)
#         except Http404 as e:
#             if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
#                 return JsonResponse({"error": str(e)}, status=404)
#             return render(request, "chat/assistant_not_found.html", {"error": str(e)}, status=404)
#
#         try:
#
#             # Создаем сообщение пользователя
#             user_message = Message.objects.create(
#                 chat=chat,
#                 content=user_message_text,
#                 source_type=MessageSource.WEB,
#                 sender=request.user,
#                 message_type=MessageType.TEXT
#             )
#
#             # Обрабатываем загруженный файл
#             media_objects = []
#             if has_file:
#                 media_objects = self._handle_uploaded_file(request, user_message)
#
#             # Подготавливаем контекст для AI
#             user_context = {
#                 'text': user_message_text,
#                 'media': [{
#                     'url': media.get_absolute_url(),
#                     'type': media.file_type,
#                     'mime_type': media.mime_type,
#                     'path': media.file.path if hasattr(media.file, 'path') else None
#                 } for media in media_objects]
#             }
#
#             # Получаем ответ от AI
#             ai_response = self._process_ai_response(chat, user_context)
#             ai_message_text = ai_response['text']
#             ai_media_data = ai_response['media']
#
#             # Создаем сообщение AI
#             ai_message = Message.objects.create(
#                 chat=chat,
#                 reply_to=user_message,
#                 content=ai_message_text,
#                 is_ai=True,
#                 source_type=MessageSource.WEB,
#                 sender=None,
#                 message_type=MessageType.TEXT
#             )
#
#             # Сохраняем медиафайлы, сгенерированные AI
#             if ai_media_data:
#                 ai_media_objects = self._save_ai_generated_media(ai_media_data, ai_message)
#                 if ai_media_objects:
#                     ai_message.message_type = self._determine_message_type(ai_media_objects)
#                     ai_message.save()
#
#         except ValueError as e:
#             if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
#                 return JsonResponse({"error": str(e)}, status=400)
#             # logger.warning(f"Ошибка валидации: {str(e)}")
#             return redirect('chat:ai-chat', slug=slug)
#         except Exception as e:
#             # logger.exception(f"Критическая ошибка при обработке сообщения: {str(e)}")
#             if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
#                 return JsonResponse({
#                     "error": "Произошла внутренняя ошибка сервера. Попробуйте позже."
#                 }, status=500)
#             return redirect('chat:ai-chat', slug=slug)
#
#         # Обрабатываем AJAX-запрос
#         if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
#             return self._get_ajax_response(user_message, ai_message)
#
#         return redirect('chat:ai-chat', slug=slug)

#
# class AiChatView(LoginRequiredMixin, View):
#     """Чат с AI с полной поддержкой медиафайлов"""
#     template_name = "chat/ai_chat.html"
#
#     def setup(self, request, *args, **kwargs):
#         """Инициализация сервисов перед обработкой запроса"""
#         super().setup(request, *args, **kwargs)
#         self.user_media_service = UserMediaService(request.user)
#
#     @staticmethod
#     def _get_assistant_and_chat(request, slug):
#         """Получает AI-ассистента и чат с обработкой ошибок"""
#         try:
#             assistant = AIAssistant.objects.get(slug=slug, is_active=True)
#         except AIAssistant.DoesNotExist:
#             raise Http404("AI-ассистент не найден или неактивен")
#
#         try:
#             chat, created = Chat.get_or_create_ai_chat(
#                 user=request.user,
#                 ai_assistant=assistant,
#                 platform=ChatPlatform.WEB,
#                 title=f"Чат с {assistant.name}"
#             )
#             if created:
#                 logger.info(
#                     f"Создан новый чат {chat.pk} для пользователя {request.user.pk} и ассистента {assistant.slug}")
#
#             return assistant, chat
#         except Exception as e:
#             logger.error(f"Ошибка при создании чата: {str(e)}")
#             raise Http404("Не удалось создать чат с AI-ассистентом")
#
#     @staticmethod
#     def _get_chat_history(chat):
#         """Получает историю сообщений с предзагрузкой медиа"""
#         return chat.messages.filter(
#             is_user_deleted=False
#         ).select_related('sender').prefetch_related(
#             'media_files'
#         ).order_by("created_at")
#
#     @staticmethod
#     def _get_ajax_response(user_message, ai_message):
#         """Формирует AJAX-ответ для чата с поддержкой медиа"""
#
#         def serialize_media(media_files):
#             return [{
#                 "id": media.pk,
#                 "url": media.get_absolute_url(),
#                 "type": media.file_type,
#                 "mime_type": media.mime_type,
#                 "name": os.path.basename(media.file.name),
#                 "thumbnail": media.thumbnail.url if media.thumbnail else None,
#                 "size": media.size
#             } for media in media_files.all()]
#
#         response_data = {
#             'user_message': {
#                 "id": user_message.pk,
#                 "text": user_message.content,
#                 "message_type": user_message.message_type,
#                 "media_files": serialize_media(user_message.media_files)
#             },
#             'ai_response': {
#                 "id": ai_message.pk,
#                 "score": ai_message.score,
#                 "request_url": reverse_lazy("chat:ai-message-score", kwargs={"message_pk": ai_message.pk}),
#                 "text": ai_message.content,
#                 "message_type": ai_message.message_type,
#                 "media_files": serialize_media(ai_message.media_files)
#             },
#         }
#         return JsonResponse(response_data)
#
#     @staticmethod
#     def _process_ai_response(user_id, user_context):
#         """Обрабатывает запрос к AI и возвращает ответ"""
#         try:
#             orchestrator = Orchestrator(user_id=user_id, user_context=user_context)
#             ai_response = orchestrator.process_message(user_context)
#
#             if not ai_response.get('success', False):
#                 logger.warning(f"AI вернул неуспешный ответ: {ai_response}")
#                 return {
#                     'text': "Извините, произошла ошибка при генерации ответа.",
#                     'media': []
#                 }
#
#             return {
#                 'text': ai_response.get('response_message', "Извините, я пока не могу ответить на ваш вопрос."),
#                 'media': ai_response.get('media_files', [])
#             }
#
#         except Exception as e:
#             logger.exception(f"Ошибка при работе с AI: {str(e)}")
#             return {
#                 'text': "Извините, сейчас не могу обработать ваш запрос.",
#                 'media': []
#             }
#
#     def get(self, request, slug, *args, **kwargs):
#         """Отображает интерфейс чата с историей сообщений"""
#         try:
#             assistant, chat = self._get_assistant_and_chat(request, slug)
#             chat_history = self._get_chat_history(chat)
#         except Http404 as e:
#             return render(request, "chat/assistant_not_found.html", {"error": str(e)}, status=404)
#
#         context = {
#             'chat': chat,
#             'chat_history': chat_history,
#             'assistant': assistant,
#             # Передаем настройки для фронтенда
#             'max_file_size_mb': UserMediaService.MAX_FILE_SIZE // 1024 // 1024,
#             'allowed_file_types': list(UserMediaService.ALLOWED_MIME_TYPES.keys()),
#         }
#         return render(request, self.template_name, context)
#
#     def post(self, request, slug, *args, **kwargs):
#         """Обрабатывает отправку сообщения в чат с поддержкой медиа"""
#         user_message_text = request.POST.get('message', '').strip()
#         has_file = 'file' in request.FILES
#
#         print(request.POST)
#         print(request.FILES)
#
#         # Валидация: должно быть либо текст, либо файл
#         if not user_message_text and not has_file:
#             error_msg = "Сообщение или файл отсутствуют"
#             if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
#                 return JsonResponse({"error": error_msg}, status=400)
#             messages.error(request, error_msg)
#             return redirect('chat:ai-chat', slug=slug)
#
#         # Получаем ассистента и чат
#         try:
#             assistant, chat = self._get_assistant_and_chat(request, slug)
#         except Http404 as e:
#             if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
#                 return JsonResponse({"error": str(e)}, status=404)
#             return render(request, "chat/assistant_not_found.html", {"error": str(e)}, status=404)
#
#         try:
#             with transaction.atomic():
#                 # Создаем сообщение пользователя
#                 user_message = Message.objects.create(
#                     chat=chat,
#                     content=user_message_text,
#                     source_type=MessageSource.WEB,
#                     sender=request.user,
#                     message_type=MessageType.TEXT if not has_file else MessageType.DOCUMENT
#                 )
#
#                 # Обрабатываем загруженный файл
#                 if has_file:
#                     try:
#                         self.user_media_service.handle_uploaded_file(
#                             request.FILES['file'],
#                             user_message
#                         )
#                         # Если файл успешно загружен, обновляем тип сообщения
#                         if user_message.media_files.exists():
#                             file_type = user_message.media_files.first().file_type
#                             type_mapping = {
#                                 'image': MessageType.IMAGE,
#                                 'audio': MessageType.AUDIO,
#                                 'video': MessageType.VIDEO,
#                                 'document': MessageType.DOCUMENT
#                             }
#                             user_message.message_type = type_mapping.get(file_type, MessageType.TEXT)
#                             user_message.save(update_fields=['message_type'])
#                     except ValueError as e:
#                         raise
#                     except Exception as e:
#                         logger.error(f"Ошибка при обработке файла: {str(e)}")
#                         raise ValueError("Ошибка при загрузке файла. Попробуйте еще раз.")
#
#                 # Подготавливаем контекст для AI
#                 user_context = {
#                     'text': user_message_text,
#                     'media': [{
#                         'url': media.get_absolute_url(),
#                         'type': media.file_type,
#                         'mime_type': media.mime_type,
#                         'path': media.file.path if hasattr(media.file, 'path') else None
#                     } for media in user_message.media_files.all()]
#                 }
#
#                 # Получаем ответ от AI
#                 ai_response = self._process_ai_response(request.user.id, user_context)
#                 ai_message_text = ai_response['text']
#                 ai_media_data = ai_response['media']
#
#                 # Создаем сообщение AI
#                 ai_message = Message.objects.create(
#                     chat=chat,
#                     reply_to=user_message,
#                     content=ai_message_text,
#                     is_ai=True,
#                     source_type=MessageSource.WEB,
#                     sender=None,
#                     message_type=MessageType.TEXT
#                 )
#
#                 # Асинхронно обрабатываем AI-сгенерированные медиа
#                 if ai_media_data:
#                     ai_media_service = AiMediaService(chat)
#                     ai_media_service.process_ai_media(ai_media_data, ai_message)
#
#         except ValueError as e:
#             if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
#                 return JsonResponse({"error": str(e)}, status=400)
#             messages.error(request, str(e))
#             return redirect('chat:ai-chat', slug=slug)
#         except Exception as e:
#             logger.exception(f"Критическая ошибка при обработке сообщения: {str(e)}")
#             if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
#                 return JsonResponse({
#                     "error": "Произошла внутренняя ошибка сервера. Попробуйте позже."
#                 }, status=500)
#             messages.error(request, "Произошла ошибка при обработке вашего сообщения. Попробуйте позже.")
#             return redirect('chat:ai-chat', slug=slug)
#
#         # Обрабатываем AJAX-запрос
#         if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
#             return self._get_ajax_response(user_message, ai_message)
#
#         return redirect('chat:ai-chat', slug=slug)

class AiChatView(LoginRequiredMixin, View):
    """Чат с AI с полной поддержкой медиафайлов"""
    template_name = "chat/ai_chat.html"

    def setup(self, request, *args, **kwargs):
        """Инициализация сервисов перед обработкой запроса"""
        super().setup(request, *args, **kwargs)
        # Инициализация сервисов
        self.chat_service = ChatService()
        self.message_service = MessageService()
        self.user_media_service = UserMediaService(request.user)

    def _get_assistant_and_chat(self, request, slug):
        """
        Получает AI-ассистента и чат с обработкой ошибок через исключения
        Возвращает кортеж (assistant, chat)
        """
        try:
            # Получаем ассистента
            assistant = AIAssistant.objects.get(slug=slug, is_active=True)
        except AIAssistant.DoesNotExist:
            logger.error(f"AI-ассистент с slug {slug} не найден")
            raise Http404("AI-ассистент не найден или неактивен")

        try:
            # Создаем или получаем чат
            chat = self.chat_service.get_or_create_chat(
                user=request.user,
                platform=ChatPlatform.WEB,
                assistant_slug=slug,
                title=f"Чат с {assistant.name}",
                scope="private"
            )
            return assistant, chat
        except AssistantNotFoundError as e:
            logger.error(f"Ошибка при получении чата: {str(e)}")
            raise Http404(str(e))
        except ChatCreationError as e:
            logger.error(f"Ошибка создания чата: {str(e)}")
            raise Http404("Не удалось создать чат с AI-ассистентом")

    def _get_chat_history(self, chat):
        """Получает историю сообщений с предзагрузкой медиа"""
        return self.chat_service.get_chat_history(chat)

    def _get_ajax_response(self, user_message, ai_message):
        """Формирует AJAX-ответ для чата с поддержкой медиа"""
        return self.message_service.get_ajax_response(user_message, ai_message)

    def _process_ai_response(self, user_id, user_context):
        """Обрабатывает запрос к AI и возвращает ответ"""
        try:
            orchestrator = Orchestrator(user_id=user_id, user_context=user_context)
            ai_response = orchestrator.process_message(user_context)

            if not ai_response.get('success', False):
                logger.warning(f"AI вернул неуспешный ответ: {ai_response}")
                return {
                    'text': "Извините, произошла ошибка при генерации ответа.",
                    'media': []
                }

            return {
                'text': ai_response.get('response_message', "Извините, я пока не могу ответить на ваш вопрос."),
                'media': ai_response.get('media_files', [])
            }

        except Exception as e:
            logger.exception(f"Ошибка при работе с AI: {str(e)}")
            return {
                'text': "Извините, сейчас не могу обработать ваш запрос.",
                'media': []
            }

    def get(self, request, slug, *args, **kwargs):
        """Отображает интерфейс чата с историей сообщений"""
        try:
            assistant, chat = self._get_assistant_and_chat(request, slug)
            chat_history = self._get_chat_history(chat)
        except Http404 as e:
            return render(request, "chat/assistant_not_found.html", {"error": str(e)}, status=404)

        context = {
            'chat': chat,
            'chat_history': chat_history,
            'assistant': assistant,
            # Передаем настройки для фронтенда
            'max_file_size_mb': UserMediaService.MAX_FILE_SIZE // 1024 // 1024,
            'allowed_file_types': list(UserMediaService.ALLOWED_MIME_TYPES.keys()),
        }
        return render(request, self.template_name, context)

    def post(self, request, slug, *args, **kwargs):
        """Обрабатывает отправку сообщения в чат с поддержкой медиа"""
        user_message_text = request.POST.get('message', '').strip()
        has_file = 'file' in request.FILES

        # Валидация: должно быть либо текст, либо файл
        if not user_message_text and not has_file:
            error_msg = "Сообщение или файл отсутствуют"
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({"error": error_msg}, status=400)
            messages.error(request, error_msg)
            return redirect('chat:ai-chat', slug=slug)

        # Получаем ассистента и чат
        try:
            assistant, chat = self._get_assistant_and_chat(request, slug)
        except Http404 as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({"error": str(e)}, status=404)
            return render(request, "chat/assistant_not_found.html", {"error": str(e)}, status=404)

        try:
            with transaction.atomic():
                # Создаем сообщение пользователя
                user_message = self.message_service.create_user_message(
                    chat=chat,
                    sender=request.user,
                    content=user_message_text,
                    message_type=MessageType.TEXT if not has_file else MessageType.DOCUMENT
                )

                # Обрабатываем загруженный файл
                if has_file:
                    try:
                        # Обработка файла через сервис
                        media_obj = self.user_media_service.handle_uploaded_file(
                            request.FILES['file'],
                            user_message
                        )

                        # Обновляем тип сообщения на основе медиа
                        self.message_service.update_message_type_from_media(user_message)

                    except ValueError as e:
                        # Обработка ошибок валидации файла
                        logger.warning(f"Ошибка валидации файла: {str(e)}")
                        raise
                    except Exception as e:
                        logger.error(f"Ошибка при обработке файла: {str(e)}")
                        raise MediaProcessingError(f"Ошибка при загрузке файла: {str(e)}")

                # Подготавливаем контекст для AI
                user_context = {
                    'text': user_message_text,
                    'media': [{
                        'url': media.get_absolute_url(),
                        'type': media.file_type,
                        'mime_type': media.mime_type,
                        'path': media.file.path if hasattr(media.file, 'path') else None
                    } for media in user_message.media_files.all()]
                }

                # Получаем ответ от AI
                ai_response = self._process_ai_response(request.user.id, user_context)
                ai_message_text = ai_response['text']
                ai_media_data = ai_response['media']

                # Создаем сообщение AI
                ai_message = self.message_service.create_ai_message(
                    chat=chat,
                    content=ai_message_text,
                    reply_to=user_message,
                    source_type=MessageSource.WEB
                )

                # Асинхронно обрабатываем AI-сгенерированные медиа
                if ai_media_data:
                    ai_media_service = AiMediaService(chat)
                    ai_media_service.process_ai_media(ai_media_data, ai_message)

        except ValueError as e:
            # Обработка ошибок валидации
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({"error": str(e)}, status=400)
            messages.error(request, str(e))
            return redirect('chat:ai-chat', slug=slug)
        except MediaProcessingError as e:
            # Специфическая обработка ошибок медиа
            logger.error(f"Ошибка обработки медиа: {str(e)}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({"error": str(e)}, status=500)
            messages.error(request, "Ошибка при обработке медиафайла. Пожалуйста, попробуйте еще раз.")
            return redirect('chat:ai-chat', slug=slug)
        except Exception as e:
            # Обработка всех остальных ошибок
            logger.exception(f"Критическая ошибка при обработке сообщения: {str(e)}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    "error": "Произошла внутренняя ошибка сервера. Попробуйте позже."
                }, status=500)
            messages.error(request, "Произошла ошибка при обработке вашего сообщения. Попробуйте позже.")
            return redirect('chat:ai-chat', slug=slug)

        # Обрабатываем AJAX-запрос
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return self._get_ajax_response(user_message, ai_message)

        return redirect('chat:ai-chat', slug=slug)


class ChatClearView(LoginRequiredMixin, View):
    """Очистить историю чата"""
    pass


class AIMessageScoreView(LoginRequiredMixin, View):
    """Установка оценки ответа AI"""

    def post(self, request, message_pk):
        try:
            data = json.loads(request.body)
            score = int(data.get("score"))
            if score not in range(-2, 3):  # -2, -1, 0, 1, 2
                return JsonResponse({"error": "Invalid score value"}, status=400)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Score must be an integer"}, status=400)

        updated_count = Message.objects.filter(pk=message_pk, is_ai=True).update(score=score)
        if not updated_count:
            return JsonResponse({"error": "Message not found or is a user message"}, status=404)

        return JsonResponse({"success": True,
                             "score": score,
                             })


class AIConversationHistoryView(LoginRequiredMixin, ListView):
    """Просмотр всей истории переписки пользователя с заданным AI-ассистентом
    JSON при ?export=json
    """
    model = Message
    template_name = "chat/ai_conversation_history.html"
    context_object_name = 'messages'
    paginate_by = 10

    def get_ai_assistant(self):
        if not hasattr(self, "_ai_assistant"):
            self._ai_assistant = get_object_or_404(
                AIAssistant,
                slug=self.kwargs.get("slug"),
                is_active=True,
            )
        return self._ai_assistant

    def get_queryset(self):
        """Возвращает queryset сообщений, уже с select_related для sender"""
        user = self.request.user
        ai_assistant = self.get_ai_assistant()

        # Кэшируем chat_ids один раз
        if not hasattr(self, "_chat_ids"):
            self._chat_ids = list(
                Chat.objects.filter(owner=user, ai_assistant=ai_assistant)
                .values_list("id", flat=True)
            )

        qs = (
            Message.objects.filter(chat_id__in=self._chat_ids)
            .select_related("sender", "chat", "reply_to", )
            .prefetch_related("answers", "media_files")
            .order_by("timestamp")
        )
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = self.object_list  # queryset, который использует пагинатор

        # Статистика
        total_messages = qs.count()
        ai_messages = qs.filter(is_ai=True).count()
        user_messages = total_messages - ai_messages

        try:
            first_msg = qs.earliest("timestamp")
        except qs.model.DoesNotExist:
            first_msg = None

        try:
            last_msg = qs.latest("timestamp")
        except qs.model.DoesNotExist:
            last_msg = None

        context.update({
            "ai_assistant": self.get_ai_assistant(),
            "total_messages": total_messages,
            "ai_messages": ai_messages,
            "user_messages": user_messages,
            "first_interaction": first_msg.timestamp if first_msg else None,
            "last_interaction": last_msg.timestamp if last_msg else None,
        })
        return context

    def render_to_response(self, context, **response_kwargs):
        """Возвращаем JSON при ?export=json, иначе стандартный HTML"""
        if self.request.GET.get("export") == "json":
            messages = self.get_queryset().order_by("timestamp")  # по возрастанию для JSON
            export_data = {
                "assistant_name": self.get_ai_assistant().name,
                "assistant_type": self.get_ai_assistant().get_assistant_type_display(),
                "user": self.request.user.username,
                "total_messages": messages.count(),
                "export_date": timezone.now().isoformat(),
                "conversation": [
                    {
                        "timestamp": msg.timestamp.isoformat(),
                        "sender": "AI" if msg.is_ai else self.request.user.username,
                        "content": msg.content,
                        "platform": msg.get_source_type_display(),
                        "metadata": msg.metadata,
                    }
                    for msg in messages.iterator()
                ]
            }
            response = JsonResponse(export_data, json_dumps_params={'ensure_ascii': False, 'indent': 2})
            response[
                'Content-Disposition'] = (f'attachment; filename="ai_conversation_{self.get_ai_assistant().slug}'
                                          f'_{timezone.now().strftime("%Y%m%d_%H%M")}.json"')
            return response
        else:
            return super().render_to_response(context, **response_kwargs)
