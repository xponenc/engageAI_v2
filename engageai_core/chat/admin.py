# chat/admin.py
from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from .models import Chat, Message, ChatType


@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    list_display = ('title', 'type', 'user_display', 'is_primary_ai_chat', 'created_at')
    list_filter = ('type', 'is_primary_ai_chat')
    search_fields = ('title', 'participants__username', 'user__username', 'user__email')
    filter_horizontal = ('participants',)
    raw_id_fields = ('user', 'notification_recipient')
    readonly_fields = ('created_at',)

    fieldsets = (
        (_('Основная информация'), {
            'fields': ('title', 'type', 'user', 'is_primary_ai_chat')
        }),
        (_('Участники и доступ'), {
            'fields': ('participants', 'is_ai_enabled', 'notification_recipient')
        }),
        (_('Синхронизация'), {
            'fields': ('telegram_chat_id',)
        }),
        (_('Дополнительные настройки'), {
            'fields': ('is_user_deleted', 'created_at')
        }),
    )

    def user_display(self, obj):
        if obj.user:
            return f"{obj.user.get_full_name()} ({obj.user.username})"
        return _("Не назначен")

    user_display.short_description = _('Владелец')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')

    class Media:
        css = {
            'all': ('admin/css/chat_admin.css',)
        }


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('chat', 'sender', 'content_preview', 'source_type', 'timestamp', 'is_ai')
    list_filter = ('source_type', 'is_ai', 'chat__type', 'chat__is_primary_ai_chat')
    search_fields = ('content', 'sender__username', 'external_id', 'chat__title')
    readonly_fields = ('metadata_display', 'timestamp')
    date_hierarchy = 'timestamp'

    def content_preview(self, obj):
        return obj.content[:70] + '...' if len(obj.content) > 70 else obj.content

    content_preview.short_description = _('Содержание')

    def metadata_display(self, obj):
        import json
        if obj.metadata:
            return json.dumps(obj.metadata, indent=2, ensure_ascii=False)
        return _("Нет метаданных")

    metadata_display.short_description = _('Метаданные')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('chat', 'sender')