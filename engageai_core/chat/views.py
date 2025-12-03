import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q, Min, Max
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse_lazy
from django.utils import timezone

from django.views import View
from django.views.generic import ListView

from ai_assistant.models import AIAssistant
from .models import Chat, Message, MessageSource, ChatPlatform


class AiChatView(LoginRequiredMixin, View):
    """Базовый чат с AI"""
    template_name = "chat/ai_chat.html"

    def _get_assistant_and_chat(self, request, slug):
        """Получает AI-ассистента и чат с обработкой ошибок"""
        try:
            assistant = AIAssistant.objects.get(slug=slug, is_active=True)
        except AIAssistant.DoesNotExist:
            raise Http404("AI-ассистент не найден или неактивен")

        try:
            chat = Chat.get_or_create_ai_chat(
                user=request.user,
                ai_assistant=assistant,
                platform=ChatPlatform.WEB,
            )
            return assistant, chat
        except Exception as e:
            # logger.error(f"Ошибка при создании чата: {str(e)}")
            raise Http404("Не удалось создать чат с AI-ассистентом")

    def _get_ajax_response(self, user_message_text, ai_message, request):
        """Формирует AJAX-ответ для чата"""
        return JsonResponse({
            'user_message': user_message_text,
            'ai_response': {
                "id": ai_message.pk,
                "score": None,
                "request_url": reverse_lazy("chat:ai-message-score", kwargs={"message_pk": ai_message.pk}),
                "text": ai_message.content,
            },
        })

    def _process_ai_response(self, chat, user_message_text):
        """Обрабатывает запрос к AI и возвращает ответ"""
        return f"Re: {user_message_text}"
        # try:
        #     # Инициализируем оркестратор с текущим чатом
        #     from engageai_core.ai.orchestrator import Orchestrator
        #     orchestrator = Orchestrator(chat=chat)
        #
        #     # Получаем ответ от AI
        #     ai_response = orchestrator.process_message(user_message_text)
        #
        #     if not ai_response.get('success', False):
        #         # logger.error(f"Ошибка при генерации ответа AI: {ai_response.get('error', 'Неизвестная ошибка')}")
        #         return "Извините, произошла ошибка при генерации ответа. Пожалуйста, попробуйте позже."
        #
        #     return ai_response.get('response_message', "Извините, я пока не могу ответить на ваш вопрос.")
        #
        # except Exception as e:
        #     # logger.exception(f"Критическая ошибка при работе с AI-оркестратором: {str(e)}")
        #     return ("Извините, сейчас я не могу обработать ваш запрос."
        #             " Попробуйте позже или воспользуйтесь командами из меню.")

    def get(self, request, slug, *args, **kwargs):
        """Отображает интерфейс чата с историей сообщений"""
        try:
            assistant, chat = self._get_assistant_and_chat(request, slug)
        except Http404 as e:
            return render(request, "chat/assistant_not_found.html", {"error": str(e)}, status=404)

        # Получаем историю сообщений с пагинацией для производительности
        chat_history = chat.messages.filter(
            is_user_deleted=False
        ).order_by("created_at").select_related('sender')

        context = {
            'chat': chat,
            'chat_history': chat_history,
            'assistant': assistant,
        }
        return render(request, self.template_name, context)

    def post(self, request, slug, *args, **kwargs):
        """Обрабатывает отправку сообщения в чат"""
        user_message_text = request.POST.get('message', '').strip()

        # Валидация сообщения
        if not user_message_text:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({"error": "Пустое сообщение"}, status=400)
            return redirect('chat:ai-chat', slug=slug)

        # if len(user_message_text) > 2000:
        #     if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        #         return JsonResponse({"error": "Сообщение слишком длинное"}, status=400)
        #     return redirect('chat:ai-chat', slug=slug)

        # Получаем ассистента и чат
        try:
            assistant, chat = self._get_assistant_and_chat(request, slug)
        except Http404 as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({"error": str(e)}, status=404)
            return render(request, "chat/assistant_not_found.html", {"error": str(e)}, status=404)

        user_message = Message.objects.create(
            chat=chat,
            content=user_message_text,
            source_type=MessageSource.WEB,
            sender=self.request.user
        )

        # Генерируем ответ от AI
        ai_message_text = self._process_ai_response(chat, user_message_text)

        ai_message = Message.objects.create(
            chat=chat,
            reply_to=user_message,
            content=ai_message_text,
            is_ai=True,
            source_type=MessageSource.WEB,
            sender=None
        )

        # Обрабатываем AJAX-запрос
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return self._get_ajax_response(user_message_text, ai_message, request)

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
            Message.objects.filter(chat_id__in=self._chat_ids, is_ai=False)
            .select_related("sender", "chat", "reply_to")
            .order_by("-timestamp")
        )
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = self.object_list  # queryset, который использует пагинатор

        # Статистика
        total_messages = qs.count()
        ai_messages = qs.filter(is_ai=True).count()
        user_messages = total_messages - ai_messages

        # first/last message
        first_msg = qs.earliest("timestamp")  # SELECT ... ORDER BY timestamp ASC LIMIT 1
        last_msg = qs.latest("timestamp")  # SELECT ... ORDER BY timestamp DESC LIMIT 1

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
