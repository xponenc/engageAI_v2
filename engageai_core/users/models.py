import datetime
import os
from time import timezone
from typing import Dict, Any

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse


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
    phone_regex = RegexValidator(
        regex=r'^7\d{10}$',
        message="Телефонный номер должен быть введен в формате: '79991234567'."
    )
    phone = models.CharField(verbose_name="Телефон", validators=[phone_regex, ], max_length=12, unique=True)
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

class StudyProfile(models.Model):
    """Профиль расширяющий данные по Telegram аккаунту пользователя"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="study_profile")
    english_level = models.CharField(verbose_name="Уровень CEFR", max_length=2,
                                     choices=CEFRLevel.choices, default=CEFRLevel.A1)

    learning_goals = models.JSONField(default=list, blank=True)  # ["career", "travel", "business"]
    profession = models.CharField(max_length=200, blank=True)
    available_time_per_week = models.IntegerField(null=True, blank=True)  # минуты

    # Системные метрики
    engagement_level = models.IntegerField(default=5)  # 1-10 шкала
    trust_level = models.IntegerField(default=4)  # 1-10 шкала

    # Прогресс обучения
    learning_path = models.JSONField(default=dict, blank=True)  # текущий план обучения
    completed_lessons = models.JSONField(default=list, blank=True)

    def update_engagement(self, delta):
        self.engagement_level = max(1, min(10, self.engagement_level + delta))
        self.save()

    def add_learning_goal(self, goal):
        if goal not in self.learning_goals:
            self.learning_goals.append(goal)
            self.save()

    def to_dict(self) -> Dict[str, Any]:
        """Преобразует модель в словарь для работы с состоянием"""
        return {
            'user_id': self.user.id,
            'profile': {
                'english_level': self.english_level,
                'learning_goals': self.learning_goals or [],
                'profession': self.profession,
                'available_time_per_week': self.available_time_per_week,
                'challenges': self.challenges or []
            },
            'metrics': {
                'engagement_level': self.engagement_level
            },
            'learning_plan': self.learning_path,
            'current_lesson': self.current_lesson,
            'last_interaction': self.last_interaction.isoformat()
        }