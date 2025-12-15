class ServiceError(Exception):
    """Базовый класс для исключений сервисного слоя"""
    pass


class AssistantNotFoundError(ServiceError):
    """Исключение для случая, когда ассистент не найден"""

    def __init__(self, assistant_slug):
        self.assistant_slug = assistant_slug
        super().__init__(f"AI-ассистент с slug '{assistant_slug}' не найден")


class ChatServiceError(Exception):
    """Базовое исключение для сервиса чатов"""
    pass


class ChatCreationError(ChatServiceError):
    """Исключение для ошибок создания чата"""

    def __init__(self, message, chat_data=None):
        self.chat_data = chat_data or {}
        super().__init__(f"Ошибка создания чата: {message}")

    @property
    def context(self):
        """Контекст ошибки для логирования"""
        return {
            "error_type": "chat_creation",
            "details": str(self),
            "chat_data": self.chat_data
        }


class MediaProcessingError(ChatServiceError):
    """Исключение для ошибок обработки медиа"""

    def __init__(self, message, media_info=None, original_exception=None):
        self.media_info = media_info or {}
        self.original_exception = original_exception
        super().__init__(f"Ошибка обработки медиа: {message}")

    @property
    def context(self):
        """Контекст ошибки для логирования"""
        context = {
            "error_type": "media_processing",
            "details": str(self),
            "media_info": self.media_info
        }
        if self.original_exception:
            context["original_error"] = str(self.original_exception)
        return context
