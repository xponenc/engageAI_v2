from datetime import datetime
from typing import Optional, Dict, Any

from users.models import Student


class UserRepository:
    """Репозиторий для работы с профилями пользователей"""

    def get_profile(self, user_id: str) -> Optional[Student]:
        """Получает профиль пользователя по ID"""
        try:
            return Student.objects.get(user_id=user_id)
        except Student.DoesNotExist:
            return None

    def create_profile(self, user_id: str, **kwargs) -> Student:
        """Создает новый профиль пользователя"""
        profile = Student.objects.create(
            user_id=user_id,
            **kwargs
        )
        return profile

    def update_profile(self, user_id: str, update_data: Dict[str, Any]) -> Student:
        """Обновляет профиль пользователя"""
        profile = self.get_profile(user_id)
        if not profile:
            profile = self.create_profile(user_id)

        for key, value in update_data.items():
            if hasattr(profile, key):
                setattr(profile, key, value)

        profile.save()
        return profile

    def get_or_create_profile(self, user_id: str) -> Student:
        """Получает или создает профиль пользователя"""
        profile = self.get_profile(user_id)
        if not profile:
            profile = self.create_profile(user_id)
        return profile

    def update_engagement(self, user_id: str, delta: int):
        """Обновляет уровень вовлеченности пользователя"""
        profile = self.get_or_create_profile(user_id)
        profile.update_engagement(delta)
