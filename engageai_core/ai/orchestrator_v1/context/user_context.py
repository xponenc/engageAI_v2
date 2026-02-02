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

    def to_prompt(self) -> str:
        """
        Человекочитаемое представление пользовательского контекста
        для включения в LLM-промпт.

        Правила:
        - включаются только непустые поля
        - значения 0 / False считаются валидными и включаются
        - без интерпретаций и бизнес-логики
        """
        lines = ["Student context:"]

        def add(label: str, value):
            if value is None:
                return
            if isinstance(value, list) and not value:
                return
            lines.append(f"- {label}: {value}")

        # Basic user info
        # add("User ID", self.user_id)
        # add("Username", self.username)
        # add("Email", self.email)

        # Profile info
        if self.cefr_level:
            add("English level (CEFR)", self.cefr_level)
        if self.profession:
            add("Profession", self.profession)
        if self.learning_goals:
            add("Learning goals", ", ".join(self.learning_goals))

        # Behavioral signals (always include, even if 0 / False)
        add("Frustration signals", self.frustration_signals)
        add("Critically frustrated", self.is_critically_frustrated)
        add("Confidence level (1–10)", self.confidence_level)

        # --- Convert behavioral signals into LLM instructions ---
        # Emotional guidance
        if self.frustration_signals >= 7:
            lines.append("- Respond in a highly supportive and very gentle manner.")
        elif self.frustration_signals >= 3:
            lines.append("- Respond in a supportive manner, without pressure.")
        else:
            lines.append("- Respond in a neutral, professional manner.")

        # Critical state guidance
        if self.is_critically_frustrated:
            lines.append("- Avoid evaluative judgments; emphasize encouragement and small steps.")

        # Complexity guidance
        if self.confidence_level <= 4:
            lines.append("- Use maximally simple language, avoid jargon.")
        else:
            lines.append("- Use standard complexity language suitable for the user's level.")

        return "\n".join(lines)

