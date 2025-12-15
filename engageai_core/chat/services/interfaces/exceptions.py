from rest_framework import status
from django.core.exceptions import ObjectDoesNotExist

"""
Примеры использования

# Пример использования в ChatService
try:
    chat = self.chat_service.get_or_create_chat(...)
except ChatCreationError as e:
    # Детальное логирование с контекстом
    logger.error(
        f"Ошибка создания чата: {str(e)}",
        extra={
            "error_context": e.context,
            "user_id": request.user.id if hasattr(request, 'user') else None
        }
    )
    # Возврат HTTP-ответа с правильным статусом
    return Response({"detail": str(e)}, status=e.status_code)

# Пример использования в API-представлении
def post(self, request):
    try:
        # ... бизнес-логика ...
    except AuthenticationError as e:
        logger.warning(
            f"Ошибка аутентификации: {str(e)}",
            extra={"security_context": e.context}
        )
        return Response(
            {"detail": str(e), "context": e.context},
            status=e.status_code
        )
    except Exception as e:
        # Обработка любых других исключений
        logger.exception(f"Непредвиденная ошибка: {str(e)}")
        return Response(
            {"detail": "Internal server error"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
"""


class ServiceError(Exception):
    """Базовое исключение для сервисного слоя"""

    def __init__(self, message, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, extra_context=None):
        super().__init__(message)
        self.status_code = status_code
        self._extra_context = extra_context or {}

    @property
    def context(self):
        """Структурированный контекст для логирования"""
        base_context = {
            "error_type": self.__class__.__name__,
            "details": str(self),
            "http_status": self.status_code
        }
        base_context.update(self._extra_context)
        return base_context


class UserNotFoundError(ServiceError):
    """Исключение для случая, когда пользователь не найден"""

    def __init__(self, message="User not found", status_code=status.HTTP_404_NOT_FOUND, user_data=None):
        self.user_data = user_data or {}
        super().__init__(message, status_code, {"user_context": self.user_data})

    @property
    def context(self):
        """Расширенный контекст для логирования поиска пользователя"""
        context = super().context
        context.update({
            "search_criteria": self.user_data,
            "recommendation": "Проверьте корректность данных пользователя или создайте новый аккаунт"
        })
        return context


class AuthenticationError(ServiceError):
    """Исключение для ошибок аутентификации"""

    def __init__(self, message="Authentication failed", status_code=status.HTTP_401_UNAUTHORIZED, auth_data=None):
        self.auth_data = auth_data or {}
        super().__init__(message, status_code, {"auth_details": self.auth_data})

    @property
    def context(self):
        """Расширенный контекст для логирования аутентификации"""
        context = super().context
        context.update({
            "security_level": "high" if self.status_code in [401, 403] else "medium",
            "auth_method": self.auth_data.get("method", "unknown"),
            "client_ip": self.auth_data.get("ip", "unknown"),
            "sensitive_data_masked": True  # Важно для безопасности
        })
        return context


class AssistantNotFoundError(ServiceError):
    """Исключение для случая, когда ассистент не найден"""

    def __init__(self, assistant_slug, status_code=status.HTTP_404_NOT_FOUND, assistant_data=None):
        self.assistant_slug = assistant_slug
        self.assistant_data = assistant_data or {}
        message = f"AI-ассистент с slug '{assistant_slug}' не найден"
        super().__init__(message, status_code, {
            "assistant_slug": assistant_slug,
            "search_params": self.assistant_data
        })

    @property
    def context(self):
        """Расширенный контекст для логирования поиска ассистента"""
        context = super().context
        context.update({
            "assistant_type": self.assistant_data.get("type", "unknown"),
            "platform": self.assistant_data.get("platform", "web"),
            "fallback_options": ["default_assistant", "fallback_agent"]
        })
        return context


class ChatException(ServiceError):
    """Базовое исключение для чатов"""
    pass


class ChatCreationError(ChatException):
    """Исключение для ошибок создания чата"""

    def __init__(self, message, chat_data=None, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                 original_exception=None):
        self.chat_data = chat_data or {}
        self.original_exception = original_exception
        super().__init__(f"Ошибка создания чата: {message}", status_code, {
            "chat_params": self.chat_data,
            "original_error": str(original_exception) if original_exception else None
        })

    @property
    def context(self):
        """Расширенный контекст для логирования создания чата"""
        context = super().context
        context.update({
            "error_type": "chat_creation",
            "chat_data": self.chat_data,
            "retry_strategy": "immediate" if self.status_code == 503 else "exponential_backoff",
            "affected_services": ["chat_service", "notification_service"]
        })
        if hasattr(self, 'original_exception') and self.original_exception:
            import traceback
            context["stack_trace"] = traceback.format_tb(self.original_exception.__traceback__)
        return context


class ChatNotFoundError(ServiceError):
    """Исключение, когда чат не найден или не может быть создан"""

    def __init__(self, assistant_slug=None, user_id=None, chat_id=None, message="Чат не найден",
                 status_code=status.HTTP_404_NOT_FOUND):
        context = {
            "assistant_slug": assistant_slug,
            "user_id": user_id,
            "chat_id": chat_id
        }
        super().__init__(message, status_code, context)

    @property
    def context(self):
        """Расширенный контекст для логирования поиска чата"""
        context = super().context
        context.update({
            "search_criteria": {
                "assistant_slug": self._context.get("assistant_slug"),
                "user_id": self._context.get("user_id"),
                "chat_id": self._context.get("chat_id")
            },
            "recommendation": "Проверьте корректность slug ассистента или создайте новый чат",
            "recovery_options": ["create_new_chat", "check_user_permissions"]
        })
        return context


class MessageException(ServiceError):
    """Базовое исключение для сообщений"""
    pass


class MessageCreationError(ServiceError):
    """Исключение при создании сообщения"""

    def __init__(self, chat_id=None, message_type=None, message="Ошибка создания сообщения",
                 status_code=status.HTTP_400_BAD_REQUEST, message_data=None):
        context = {
            "chat_id": chat_id,
            "message_type": message_type,
            "message_data": message_data or {}
        }
        super().__init__(message, status_code, context)

    @property
    def context(self):
        """Расширенный контекст для логирования создания сообщения"""
        context = super().context
        context.update({
            "message_platform": self._context["message_data"].get("platform", "unknown"),
            "message_source": self._context["message_data"].get("source", "web"),
            "retry_strategy": "immediate" if self.status_code in [503, 504] else "exponential_backoff",
            "affected_services": ["message_service", "notification_service"]
        })
        return context


class MessageNotFoundError(MessageException):
    """Исключение для случая, когда сообщение не найдено"""

    def __init__(self, message, message_id=None, status_code=status.HTTP_404_NOT_FOUND, message_data=None):
        self.message_id = message_id
        self.message_data = message_data or {}
        super().__init__(message, status_code, {
            "message_id": message_id,
            "search_context": self.message_data
        })

    @property
    def context(self):
        """Расширенный контекст для логирования поиска сообщения"""
        context = super().context
        context.update({
            "message_platform": self.message_data.get("platform", "unknown"),
            "chat_id": self.message_data.get("chat_id"),
            "time_range": self.message_data.get("time_range"),
            "recovery_options": ["check_deleted_messages", "restore_from_backup"]
        })
        return context


class TelegramServiceError(ServiceError):
    """Исключение для ошибок в Telegram сервисе"""

    def __init__(self, message, status_code=status.HTTP_400_BAD_REQUEST, telegram_data=None, api_response=None):
        self.telegram_data = telegram_data or {}
        self.api_response = api_response
        super().__init__(message, status_code, {
            "telegram_context": self.telegram_data,
            "api_response": str(api_response) if api_response else None
        })

    @property
    def context(self):
        """Расширенный контекст для логирования ошибок Telegram API"""
        context = super().context
        context.update({
            "telegram_method": self.telegram_data.get("method", "unknown"),
            "chat_type": self.telegram_data.get("chat_type", "private"),
            "bot_username": self.telegram_data.get("bot_username"),
            "rate_limit_info": self.telegram_data.get("rate_limit"),
            "retry_after": self.telegram_data.get("retry_after_seconds"),
            "telegram_error_code": self.telegram_data.get("error_code"),
            "sensitive_data_removed": True  # Важно для безопасности
        })
        return context


class MediaProcessingError(ServiceError):
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


class TelegramAPIException(ServiceError):
    """Исключение для ошибок Telegram API"""

    def __init__(self, api_method=None, error_code=None, error_message="Ошибка Telegram API",
                 status_code=status.HTTP_400_BAD_REQUEST, request_data=None):
        context = {
            "api_method": api_method,
            "error_code": error_code,
            "request_data": request_data or {}
        }
        super().__init__(error_message, status_code, context)

    @property
    def context(self):
        """Расширенный контекст для логирования ошибок Telegram API"""
        context = super().context
        context.update({
            "telegram_method": self._context.get("api_method"),
            "telegram_error_code": self._context.get("error_code"),
            "rate_limit_info": self._context["request_data"].get("rate_limit"),
            "sensitive_data_masked": True,
            "retry_after": self._context["request_data"].get("retry_after_seconds"),
            "security_recommendation": "Check API limits and implement exponential backoff"
        })
        return context