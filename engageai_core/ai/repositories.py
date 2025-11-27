from datetime import datetime
from typing import Optional, Dict, Any

from engageai_core.users.models import StudyProfile


class UserRepository:
    """Репозиторий для работы с профилями пользователей"""

    def get_profile(self, user_id: str) -> Optional[StudyProfile]:
        """Получает профиль пользователя по ID"""
        try:
            return StudyProfile.objects.get(user_id=user_id)
        except StudyProfile.DoesNotExist:
            return None

    def create_profile(self, user_id: str, **kwargs) -> StudyProfile:
        """Создает новый профиль пользователя"""
        profile = StudyProfile.objects.create(
            user_id=user_id,
            **kwargs
        )
        return profile

    def update_profile(self, user_id: str, update_data: Dict[str, Any]) -> StudyProfile:
        """Обновляет профиль пользователя"""
        profile = self.get_profile(user_id)
        if not profile:
            profile = self.create_profile(user_id)

        for key, value in update_data.items():
            if hasattr(profile, key):
                setattr(profile, key, value)

        profile.save()
        return profile

    def get_or_create_profile(self, user_id: str) -> StudyProfile:
        """Получает или создает профиль пользователя"""
        profile = self.get_profile(user_id)
        if not profile:
            profile = self.create_profile(user_id)
        return profile

    def update_engagement(self, user_id: str, delta: int):
        """Обновляет уровень вовлеченности пользователя"""
        profile = self.get_or_create_profile(user_id)
        profile.update_engagement(delta)

    def save_learning_plan(self, user_id: str, learning_plan: Dict[str, Any]):
        """Сохраняет учебный план пользователя"""
        profile = self.get_or_create_profile(user_id)
        profile.learning_path = learning_plan
        profile.save()

    def update_current_lesson(self, user_id: str, lesson_index: int):
        """Обновляет текущий урок пользователя"""
        profile = self.get_or_create_profile(user_id)
        profile.current_lesson = lesson_index
        profile.save()

    def mark_lesson_completed(self, user_id: str, lesson_data: Dict[str, Any]):
        """Отмечает урок как завершенный"""
        profile = self.get_or_create_profile(user_id)
        completed = profile.completed_lessons or []
        completed.append({
            **lesson_data,
            'completed_at': datetime.now().isoformat()
        })
        profile.completed_lessons = completed

        # Увеличиваем текущий урок
        if profile.current_lesson < len(profile.learning_path.get('lessons', [])):
            profile.current_lesson += 1

        profile.save()