import datetime
import os
from time import timezone
from typing import Dict, Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse

from django.utils.translation import gettext_lazy as _

User = get_user_model()


class Profile(models.Model):
    """Модель Профиль пользователя, расширяющая модель User через связь OnrToOne"""

    def create_path(self, filename):
        if self.user.first_name and self.user.last_name:
            user = '_'.join([self.user.first_name, self.user.last_name, 'avatar'])
        else:
            user = '_' + self.user.username + 'avatar'
        return os.path.sep.join(['users',
                                 f'user-id-{self.user.id}',
                                 'avatars',
                                 user + ".jpg"])

    def validate_date_in_past(value):
        today = datetime.date.today()
        if value >= today:
            raise ValidationError('Дата рождения должна быть меньше текущей даты')

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    birthdate = models.DateField(verbose_name="Дата рождения", validators=[validate_date_in_past])
    # phone_regex = RegexValidator(
    #     regex=r'^7\d{10}$',
    #     message="Телефонный номер должен быть введен в формате: '79991234567'."
    # )
    # Валидатор для международных номеров
    phone_regex = RegexValidator(
        regex=r'^\+?[1-9]\d{1,14}$',
        message="Телефонный номер должен быть в международном формате (например, +79991234567). "
                "Допустимы цифры, начинается с + и кода страны, длина 1–15 цифр после +."
    )
    phone = models.CharField(verbose_name="Телефон", validators=[phone_regex, ], max_length=17, unique=True)
    location = models.CharField(verbose_name="Город проживания", max_length=60)
    bio = models.TextField(verbose_name="О себе", max_length=1000, blank=True, null=True)
    avatar = models.ImageField(verbose_name="Аватар пользователя", upload_to=create_path, blank=True)
    is_verified = models.BooleanField(verbose_name="Пользователь верифицирован", default=False)
    created_at = models.DateTimeField(verbose_name="Дата регистрации", auto_now_add=True)

    objects = models.Manager()

    class Meta:
        permissions = (
            ("verify", "Верифицировать"),
        )

    def __str__(self):
        return f"{self.user.username}"

    def get_absolute_url(self):
        return reverse('users:profile', args=[str(self.user.id)])


class TelegramProfile(models.Model):
    """Профиль расширяющий данные по Telegram аккаунту пользователя"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="telegram_profile")
    telegram_id = models.BigIntegerField(unique=True, null=True, blank=True)  # разрешаем NULL
    username = models.CharField(max_length=255, blank=True, null=True)
    invite_code = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} ({self.telegram_id})"


class CEFRLevel(models.TextChoices):
    """Перечисление уровней CEFR."""
    A1 = "A1", "Beginner (A1)"
    A2 = "A2", "Elementary (A2)"
    B1 = "B1", "Intermediate (B1)"
    B2 = "B2", "Upper Intermediate (B2)"
    C1 = "C1", "Advanced (C1)"
    C2 = "C2", "Proficiency (C2)"

    @classmethod
    def get_next(cls, current: str) -> str:
        order = [choice.value for choice in cls]
        try:
            idx = order.index(current)
            return order[min(idx + 1, len(order) - 1)]
        except ValueError:
            return cls.A1.value


class Student(models.Model):
    """
    Профиль студента — расширение User.

    Объединяет функциональность Student из curriculum и StudyProfile.
    """
    objects = models.Manager()

    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name=_("User"))

    # Базовая информация (из StudyProfile)
    english_level = models.CharField(
        verbose_name=_("CEFR Level"),
        max_length=2,
        choices=CEFRLevel.choices,
        default=CEFRLevel.A1
    )
    learning_goals = models.JSONField(
        verbose_name=_("Learning Goals"),
        default=list,
        blank=True,
        help_text=_("e.g., ['career', 'travel', 'business']")
    )
    profession = models.CharField(
        verbose_name=_("Profession"),
        max_length=200,
        blank=True,
        help_text=_("Professional context for personalization")
    )
    available_time_per_week = models.IntegerField(
        verbose_name=_("Available Time Per Week (minutes)"),
        null=True,
        blank=True
    )

    # Метрики вовлеченности (из StudyProfile)
    engagement_level = models.IntegerField(
        verbose_name=_("Engagement Level"),
        default=5,
        help_text=_("Scale 1-10")
    )
    confidence_level = models.FloatField(
        default=5,
        help_text="Уровень уверенности студента (1-10)"
    )

    # Дополнительные поля из оригинального Student
    professional_context = models.TextField(
        verbose_name=_("Professional Context"),
        blank=True,
        help_text=_("Detailed professional context for personalization")
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Student Profile")
        verbose_name_plural = _("Student Profiles")
        indexes = [
            models.Index(fields=['english_level']),
            models.Index(fields=['engagement_level']),
            models.Index(fields=['created_at'])
        ]

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.english_level})"

    def update_engagement(self, delta):
        self.engagement_level = max(1, min(10, self.engagement_level + delta))
        self.save(update_fields=['engagement_level', 'updated_at'])

    def add_learning_goal(self, goal):
        if goal not in self.learning_goals:
            self.learning_goals.append(goal)
            self.save(update_fields=['learning_goals', 'updated_at'])


class Teacher(models.Model):
    """
    Профиль преподавателя — расширение User.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name=_("User"))

    # Профессиональная информация
    specialization = models.CharField(
        verbose_name=_("Specialization"),
        max_length=200,
        blank=True,
        help_text=_("e.g., 'Business English', 'Academic Writing'")
    )
    experience_years = models.PositiveIntegerField(
        verbose_name=_("Years of Experience"),
        null=True,
        blank=True
    )
    certification = models.TextField(
        verbose_name=_("Certification"),
        blank=True,
        help_text=_("Teaching certificates and qualifications")
    )

    # Статус и настройки
    is_active_teacher = models.BooleanField(
        verbose_name=_("Active Teacher"),
        default=False,
        help_text=_("Can accept new students")
    )
    max_students = models.PositiveIntegerField(
        verbose_name=_("Maximum Students"),
        default=50,
        help_text=_("Maximum number of active students")
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Teacher Profile")
        verbose_name_plural = _("Teacher Profiles")

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} (Teacher)"

    # @property
    # def current_student_count(self):
    #     """Возвращает количество текущих студентов преподавателя"""
    #     from curriculum.models.student.enrollment import Enrollment
    #     return Enrollment.objects.filter(
    #         course__author=self.user.teacher,
    #         is_active=True
    #     ).count()
