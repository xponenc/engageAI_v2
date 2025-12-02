from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import Chat, Message


@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    list_display = ('title', 'platform', 'scope', 'owner_display', 'ai_assistant_display', 'is_active', 'created_at')
    list_filter = ('platform', 'scope', 'is_active', 'ai_assistant__assistant_type')
    search_fields = ('title', 'owner__username', 'owner__email', 'ai_assistant__name', 'external_chat_id')
    filter_horizontal = ('participants',)
    raw_id_fields = ('owner',)
    readonly_fields = ('created_at', 'is_active')

    fieldsets = (
        (_('Основная информация'), {
            'fields': ('title', 'platform', 'scope', 'is_active')
        }),
        (_('Владелец и участники'), {
            'fields': ('owner', 'participants')
        }),
        (_('AI-ассистент'), {
            'fields': ('ai_assistant', 'is_ai_enabled')
        }),
        (_('Синхронизация'), {
            'fields': ('external_chat_id',)
        }),
        (_('Системная информация'), {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )

    def owner_display(self, obj):
        if obj.owner:
            return f"{obj.owner.get_full_name()} ({obj.owner.username})"
        return _("Не назначен")

    owner_display.short_description = _('Владелец')

    def ai_assistant_display(self, obj):
        if obj.ai_assistant:
            return f"{obj.ai_assistant.name} ({obj.ai_assistant.get_assistant_type_display()})"
        return _("Не назначен")

    ai_assistant_display.short_description = _('AI-ассистент')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('owner', 'ai_assistant')

    class Media:
        css = {
            'all': ('admin/css/chat_admin.css',)
        }


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('chat', 'sender', 'content_preview', 'source_type', 'timestamp', 'is_ai')
    list_filter = ('source_type', 'is_ai', 'chat__platform', 'chat__scope', 'chat__ai_assistant__assistant_type')
    search_fields = ('content', 'sender__username', 'external_id', 'chat__title')
    readonly_fields = ('metadata_display', 'timestamp', 'edited_at', 'edit_count')
    date_hierarchy = 'timestamp'

    fieldsets = (
        (_('Основная информация'), {
            'fields': ('chat', 'sender', 'content', 'timestamp')
        }),
        (_('Источник и статус'), {
            'fields': ('source_type', 'external_id', 'is_ai', 'is_read', 'is_user_deleted')
        }),
        (_('Редактирование'), {
            'fields': ('edited_at', 'edit_count'),
            'classes': ('collapse',)
        }),
        (_('Дополнительная информация'), {
            'fields': ('score', 'metadata_display')
        }),
    )

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
        return super().get_queryset(request).select_related('chat', 'sender', 'chat__ai_assistant')