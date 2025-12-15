class ServiceError(Exception):
    """Базовый класс для исключений сервисного слоя"""
    pass


class AssistantNotFoundError(ServiceError):
    """Исключение для случая, когда ассистент не найден"""

    def __init__(self, assistant_slug):
        self.assistant_slug = assistant_slug
        super().__init__(f"AI-ассистент с slug '{assistant_slug}' не найден")


class ChatCreationError(ServiceError):
    """Исключение для ошибок создания чата"""
    pass
