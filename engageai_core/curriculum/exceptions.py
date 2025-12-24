"""
Модуль кастомных исключений для учебного процесса.
Обеспечивает типизированную обработку ошибок с контекстом для:
- оценки ответов
- обновления навыков
- принятия решений
- работы с учебным контентом

ПРИНЦИПЫ:
1. Семантические имена (AssessmentError, not GenericError)
2. Возможность добавления контекста (enrollment_id, task_id)
3. Человекочитаемые сообщения + технические детали
4. Группировка по типам (validation, processing, system)
"""

from typing import Any, Dict, Optional
import json


class CurriculumBaseError(Exception):
    """
    Базовое исключение для всех ошибок учебного процесса.
    Добавляет сериализацию в JSON и контекст для логирования.
    """

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.context = context or {}
        self.timestamp = None  # Будет заполнено в middleware/logger

    def to_dict(self) -> dict:
        """
        Сериализует исключение в словарь для логирования и API.
        """
        return {
            "error_type": self.__class__.__name__,
            "message": str(self),
            "context": self.context,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None
        }

    def to_json(self) -> str:
        """Сериализует исключение в JSON"""
        return json.dumps(self.to_dict(), ensure_ascii=False)


class ValidationError(CurriculumBaseError):
    """Ошибка валидации данных"""
    pass


class ProcessingError(CurriculumBaseError):
    """Ошибка обработки бизнес-логики"""
    pass


class SystemError(CurriculumBaseError):
    """Критическая системная ошибка"""
    pass


# Assessment-исключения

class AssessmentError(Exception):
    """
    Базовое исключение для всех ошибок в процессе оценки ответов студентов.

    Используется в:
    - AssessmentService
    - AutoAssessorAdapter
    - LLMAssessmentAdapter

    Примеры использования:
    raise AssessmentError("Invalid assessment score: 1.5", task_id=123, response_id=456)
    """

    def __init__(self, message: str, task_id: int = None, response_id: int = None):
        super().__init__(message)
        self.task_id = task_id
        self.response_id = response_id
        self.context = {
            "task_id": task_id,
            "response_id": response_id
        }


class AssessmentValidationError(ValidationError):
    """
    Ошибка валидации результатов оценки.
    Возникает, когда AssessmentNormalizer обнаруживает некорректные данные.

    Примеры:
    - score за пределами [0.0, 1.0]
    - отсутствуют обязательные поля feedback
    - несовместимые типы данных
    """

    def __init__(self, message: str, assessment_id: Optional[int] = None, invalid_fields: list = None):
        context = {
            "assessment_id": assessment_id,
            "invalid_fields": invalid_fields or []
        }
        super().__init__(message, context)


class AssessmentProcessingError(ProcessingError):
    """
    Ошибка при обработке оценки студента.
    Возникает в AssessmentService при сбое оценки.

    Примеры:
    - сбой LLM-провайдера
    - таймаут обработки
    - недоступность внешних сервисов
    """

    def __init__(self, message: str, task_id: int, response_id: Optional[int] = None):
        context = {
            "task_id": task_id,
            "response_id": response_id
        }
        super().__init__(message, context)


class InvalidResponseError(ValidationError):
    """
    Некорректный формат ответа студента.
    Используется в LearningService при валидации входных данных.

    Примеры:
    - пустой текстовый ответ
    - отсутствует аудиофайл для speaking-задания
    - превышена длина ответа
    """

    def __init__(self, message: str, task_type: str, max_length: Optional[int] = None):
        context = {
            "task_type": task_type,
            "max_length": max_length
        }
        super().__init__(message, context)


# Skills-исключения

class SkillUpdateError(ProcessingError):
    """
    Ошибка обновления навыков студента.
    Возникает в SkillUpdateService при сбое расчета навыков.

    Примеры:
    - недостаточно данных для расчета тренда
    - сбой при обновлении SkillTrajectory
    - некорректные delta-значения
    """

    def __init__(self, message: str, student_id: int):
        context = {
            "student_id": student_id
        }
        super().__init__(message, context)


# Learning Process-исключения

class LearningProcessError(ProcessingError):
    """
    Общая ошибка в учебном процессе.
    Базовое исключение для ошибок в LearningService.
    """

    def __init__(self, message: str, enrollment_id: int):
        context = {
            "enrollment_id": enrollment_id
        }
        super().__init__(message, context)


class InvalidTaskError(ValidationError):
    """
    Задание не принадлежит текущему уроку или курсу.
    Проверяется в LearningService при обработке ответа.
    """

    def __init__(self, message: str, task_id: int, lesson_id: int, enrollment_id: int):
        context = {
            "task_id": task_id,
            "lesson_id": lesson_id,
            "enrollment_id": enrollment_id
        }
        super().__init__(message, context)


class EnrollmentError(SystemError):
    """
    Критическая ошибка с зачислением студента.
    Возникает, когда невозможно определить состояние обучения.

    Примеры:
    - несколько активных зачислений
    - отсутствует current_lesson
    - неконсистентные данные в Enrollment
    """

    def __init__(self, message: str, student_id: int, course_id: Optional[int] = None):
        context = {
            "student_id": student_id,
            "course_id": course_id
        }
        super().__init__(message, context)


# Decision-исключения

class DecisionError(ProcessingError):
    """
    Ошибка принятия решения в DecisionService.
    Используется для проблем с логикой adaptivity.
    """

    def __init__(self, message: str, decision_context: dict):
        super().__init__(message, decision_context)


class TeacherOverrideError(SystemError):
    """
    Ошибка при применении переопределения преподавателя.
    Возникает при некорректных данных в TeacherOverride.
    """

    def __init__(self, message: str, override_id: int):
        context = {
            "override_id": override_id
        }
        super().__init__(message, context)


# External Services-исключения

class LLMServiceError(SystemError):
    """
    Ошибка интеграции с LLM-провайдером.
    Используется в LLMAssessmentAdapter и LLMGateway.
    """

    def __init__(self, message: str, provider: str, model: str, status_code: Optional[int] = None):
        context = {
            "provider": provider,
            "model": model,
            "status_code": status_code
        }
        super().__init__(message, context)


class STTServiceError(SystemError):
    """
    Ошибка интеграции с Speech-to-Text сервисом.
    Используется в AutoAssessorAdapter при обработке аудио.
    """

    def __init__(self, message: str, file_size: Optional[int] = None, file_type: Optional[str] = None):
        context = {
            "file_size": file_size,
            "file_type": file_type
        }
        super().__init__(message, context)
