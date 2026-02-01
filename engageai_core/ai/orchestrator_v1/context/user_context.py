from dataclasses import dataclass
from typing import List, Optional


@dataclass
class UserContext:
    """
    Пассивный контейнер данных о пользователе.

    Правила:
    - НЕ содержит методов доступа к БД
    - НЕ содержит бизнес-логики
    - ТОЛЬКО хранит данные и предоставляет методы сериализации
    """
    user_id: int
    username: str
    email: Optional[str]

    # Профиль (из модели Student)
    cefr_level: Optional[str]  # "A1", "A2", "B1"...
    profession: Optional[str]  # "backend", "qa" и т.д.
    learning_goals: List[str]  # ["career", "interview"]

    # Поведенческие сигналы (временно — заглушки)
    frustration_signals: int = 0  # Будет заполняться из аналитики ошибок
    is_critically_frustrated: bool = False
    confidence_level: int = 5  # 1-10, базовый уровень

    def to_dict(self) -> dict:
        """Сериализация для передачи в агенты"""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "cefr_level": self.cefr_level or "unknown",
            "profession": self.profession or "unknown",
            "learning_goals": self.learning_goals,
            "frustration_signals": self.frustration_signals,
            "is_critically_frustrated": self.is_critically_frustrated,
            "confidence_level": self.confidence_level
        }
