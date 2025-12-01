import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.views import View

from .models import Chat, ChatType, Message, MessageSource


class ChatView(LoginRequiredMixin, View):
    """Базовый чат с AI"""
    template_name = "chat/ai_chat.html"

    def get(self, request, *args, **kwargs):
        chat_session = Chat.get_or_create_primary_ai_chat(user=request.user)
        print(chat_session)
        chat_history = chat_session.messages.order_by("created_at")
        print(chat_history)

        context = {
            'chat': chat_session,
            'chat_history': chat_history,
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        user_message_text = request.POST.get('message', '').strip()
        if not user_message_text:
            return JsonResponse({"error": "Empty message"}, status=400)

        chat_session = Chat.get_or_create_primary_ai_chat(user=request.user)

        # logger.info(f"[web:{chat_session.session_key}] [{client_ip}] Входящее чат сообщение: {user_message_text}")

        # Сохраняем сообщение пользователя
        user_message = Message.objects.create(
            chat=chat_session,
            content=user_message_text,
            source_type=MessageSource.WEB,
        )

        ai_message_text = user_message_text

        ai_message = Message.objects.create(
            chat=chat_session,
            content=user_message_text,
            is_ai=True,
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'user_message': user_message_text,
                'ai_response': {
                    "id": ai_message.pk,
                    "score": None,
                    "request_url": reverse_lazy("chat:message_score", kwargs={"message_pk": ai_message.pk}),
                    "text": ai_message_text,
                },
            })
        chat_history = chat_session.messages.filter(is_user_deleted=False).order_by("created_at")
        context = {
            'chat': chat_session,
            'chat_history': chat_history,
        }
        return render(request, self.template_name, context)


class ChatClearView(LoginRequiredMixin, View):
    """Очистить историю чата"""
    pass


class MessageScoreView(LoginRequiredMixin, View):
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
