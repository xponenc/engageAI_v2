class ConfidenceManager:
    """Управление уровнем уверенности студента"""

    def __init__(self, initial_level: int = 4):
        self.level = initial_level

    def on_success(self, streak: int = 1):
        """Рост после успешного выполнения"""
        if streak >= 3:
            self.level = min(self.level + 2, 10)  # Серия успехов
        else:
            self.level = min(self.level + 1, 10)

    def on_failure(self, consecutive_failures: int):
        """Падение после ошибок"""
        if consecutive_failures >= 3:
            self.level = max(self.level - 2, 1)  # Фрустрация
        else:
            self.level = max(self.level - 1, 1)

    def can_advance(self) -> bool:
        """Можно ли переходить к сложному контенту?"""
        return self.level >= 7