from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from ai_assistant.models import AIAssistant


@admin.register(AIAssistant)
class AIAssistantAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'assistant_type', 'specialization', 'is_active')
    list_filter = ('assistant_type', 'is_active')
    search_fields = ('name', 'slug', 'specialization', 'system_prompt')
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        (_('Основная информация'), {
            'fields': ('name', 'slug', 'assistant_type', 'is_active')
        }),
        (_('Специализация'), {
            'fields': ('specialization', 'target_audience', 'learning_goals', 'teaching_methods')
        }),
        (_('Параметры работы'), {
            'fields': ('system_prompt', 'temperature', 'max_tokens')
        }),
        (_('Системная информация'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('chats')
