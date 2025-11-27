from django.contrib import admin
from django.utils.safestring import mark_safe
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Profile, TelegramProfile, StudyProfile


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = "Профиль"
    fk_name = 'user'


class TelegramProfileInline(admin.StackedInline):
    model = TelegramProfile
    can_delete = False
    verbose_name_plural = "Telegram профиль"
    fk_name = 'user'


class StudyProfileInline(admin.StackedInline):
    model = StudyProfile
    can_delete = False
    verbose_name_plural = "Учебный профиль"
    fk_name = 'user'


# === Кастомный UserAdmin ===
admin.site.unregister(User)

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [ProfileInline, TelegramProfileInline, StudyProfileInline]

    list_select_related = ('profile', 'telegram_profile', 'study_profile')

    list_display = (
        'get_avatar',
        'username',
        'email',
        'first_name',
        'last_name',
        'is_staff',
        'get_phone',
        'get_telegram',
        'get_english_level'
    )

    # ---- Аватарка ----
    def get_avatar(self, obj):
        profile = getattr(obj, "profile", None)
        if profile and profile.avatar:
            return mark_safe(f'<img src="{profile.avatar.url}" width="50" height="50" style="border-radius: 6px;">')
        return "—"

    get_avatar.short_description = "Аватар"

    def get_phone(self, obj):
        return obj.profile.phone if hasattr(obj, 'profile') else "-"
    get_phone.short_description = "Телефон"

    def get_telegram(self, obj):
        return obj.telegram_profile.telegram_id if hasattr(obj, 'telegram_profile') else "-"
    get_telegram.short_description = "Telegram ID"

    def get_english_level(self, obj):
        return obj.study_profile.english_level if hasattr(obj, 'study_profile') else "-"
    get_english_level.short_description = "CEFR"
