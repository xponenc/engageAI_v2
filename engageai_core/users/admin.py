from django.contrib import admin
from django.utils.safestring import mark_safe
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from users.models import Student, Teacher, Profile, TelegramProfile


class StudentInline(admin.StackedInline):
    model = Student
    can_delete = False
    verbose_name_plural = "Студент"
    fk_name = 'user'
    fields = (
        'english_level',
        'professional_context',
    )
    readonly_fields = ('created_at',)


class TeacherInline(admin.StackedInline):
    model = Teacher
    can_delete = False
    verbose_name_plural = "Учитель"
    fk_name = 'user'
    fields = ()
    readonly_fields = ('created_at',)


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


# === Кастомный UserAdmin ===
admin.site.unregister(User)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [
        ProfileInline,
        TelegramProfileInline,
        StudentInline,
        TeacherInline
    ]

    list_select_related = (
        'profile',
        'telegram_profile',
        'student',
        'teacher'
    )

    list_display = (
        'get_avatar',
        'username',
        'email',
        'first_name',
        'last_name',
        'is_staff',
        'get_phone',
        'get_telegram',
        'get_english_level',
        'get_user_type',
        'is_active'
    )

    list_filter = ('is_staff', 'is_superuser', 'is_active', 'groups')
    search_fields = ('username', 'first_name', 'last_name', 'email', 'student__professional_context')

    def get_avatar(self, obj):
        profile = getattr(obj, "profile", None)
        if profile and profile.avatar:
            return mark_safe(f'<img src="{profile.avatar.url}" width="50" height="50" style="border-radius: 6px;">')
        return "—"

    get_avatar.short_description = "Аватар"
    get_avatar.admin_order_field = 'profile__avatar'

    def get_phone(self, obj):
        return obj.profile.phone if hasattr(obj, 'profile') else "-"

    get_phone.short_description = "Телефон"
    get_phone.admin_order_field = 'profile__phone'

    def get_telegram(self, obj):
        telegram = getattr(obj, "telegram_profile", None)
        return telegram.telegram_id if telegram else "-"

    get_telegram.short_description = "Telegram ID"
    get_telegram.admin_order_field = 'telegram_profile__telegram_id'

    def get_english_level(self, obj):
        """Получаем уровень английского из Student профиля"""
        student = getattr(obj, "student", None)
        return student.english_level if student and student.english_level else "-"

    get_english_level.short_description = "CEFR"
    get_english_level.admin_order_field = 'student__english_level'

    def get_user_type(self, obj):
        has_student = hasattr(obj, 'student') and obj.student
        has_teacher = hasattr(obj, 'teacher') and obj.teacher

        if has_student and has_teacher:
            return "Студент + Учитель"
        elif has_student:
            return "Студент"
        elif has_teacher:
            return "Учитель"
        return "—"

    get_user_type.short_description = "Тип пользователя"


# === Регистрация отдельных админ-панелей ===
@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = (
    'user', 'english_level', 'professional_context', 'created_at')
    list_filter = ('english_level',)
    search_fields = ('user__username', 'user__email', 'professional_context')
    raw_id_fields = ('user',)
    readonly_fields = ('created_at',)


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ('user', 'created_at')
    search_fields = ('user__username', 'user__email')
    raw_id_fields = ('user',)
    readonly_fields = ('created_at',)
