# chat/admin.py
from django.contrib import admin
from .models import Chat, Message


@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    list_display = ('title', 'type', 'created_at')
    list_filter = ('type',)
    search_fields = ('title', 'participants__username')
    filter_horizontal = ('participants',)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('chat', 'sender', 'content_preview', 'source_type', 'timestamp')
    list_filter = ('source_type', 'is_ai', 'chat__type')
    search_fields = ('content', 'sender__username', 'external_id')
    readonly_fields = ('metadata_display',)

    def content_preview(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content

    content_preview.short_description = 'Содержание'

    def metadata_display(self, obj):
        import json
        return json.dumps(obj.metadata, indent=2, ensure_ascii=False)

    metadata_display.short_description = 'Метаданные'
