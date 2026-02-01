from typing import Dict


class ConfidenceManager:
    """
    Управление уровнем уверенности студента (адаптировано из модуля TRUST_LOGIC).
    Соответствует ТЗ: защита от выгорания и адаптивная маршрутизация.
    """

    def __init__(self, initial_level: int = 4):
        self.level = initial_level  # Стартовый уровень = 4 (как в продажнике)
        self.frustration_signals = 0  # Счётчик ошибок подряд

    def on_success(self, streak: int = 1):
        """Рост уверенности после успеха"""
        if streak >= 3:
            self.level = min(self.level + 2, 10)  # Серия успехов → +2
            self.frustration_signals = 0
        else:
            self.level = min(self.level + 1, 10)
            self.frustration_signals = max(0, self.frustration_signals - 1)

    def on_failure(self):
        """Падение уверенности после ошибки"""
        self.frustration_signals += 1

        if self.frustration_signals >= 3:
            self.level = max(self.level - 2, 1)  # Фрустрация → -2
        else:
            self.level = max(self.level - 1, 1)

    def can_advance(self) -> bool:
        """
        Можно ли переходить к сложному контенту?
        Условие из продажника: доверие ≥7 для перехода к продаже → здесь: уверенность ≥7 для продвижения
        """
        return self.level >= 7

    def needs_support(self) -> bool:
        """Требуется эмоциональная поддержка?"""
        return self.level <= 4 and self.frustration_signals >= 3

    def to_dict(self) -> Dict:
        return {
            "level": self.level,
            "frustration_signals": self.frustration_signals,
            "can_advance": self.can_advance(),
            "needs_support": self.needs_support()
        }