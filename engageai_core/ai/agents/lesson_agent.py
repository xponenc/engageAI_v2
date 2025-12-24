from typing import Dict, Any, Optional, List

from django.db import DatabaseError

from curriculum.config.dependency_factory import CurriculumServiceFactory
from curriculum.models.student.enrollment import Enrollment
from curriculum.models.content.task import Task
from curriculum.models.content.lesson import Lesson
from curriculum.services.explainability.explainability_service import ExplainabilityService
from curriculum.services.feedback.student_explanation_builder import StudentExplanationBuilder
from curriculum.services.feedback.tones.neutral import NeutralTone
from django.utils import timezone

from utils.setup_logger import setup_logger

logger = setup_logger(name=__file__, log_dir="logs/core_ai", log_file="learning_agent.log")


class LearningAgentFactory:
    """
    Фабрика для создания LearningAgent с правильным контекстом
    """

    @staticmethod
    def create_for_enrollment(enrollment_id: int) -> "LearningAgent":
        """Создает LearningAgent для конкретного зачисления"""
        enrollment = Enrollment.objects.select_related(
            'student', 'course', 'current_lesson'
        ).get(id=enrollment_id, is_active=True)
        return LearningAgent(enrollment=enrollment)

    @staticmethod
    def create_for_student_and_course(student_id: int, course_id: int) -> "LearningAgent":
        """Создает LearningAgent для студента и конкретного курса"""
        enrollment = Enrollment.objects.select_related(
            'student', 'course', 'current_lesson'
        ).get(
            student_id=student_id,
            course_id=course_id,
            is_active=True
        )
        return LearningAgent(enrollment=enrollment)

    @staticmethod
    def get_active_enrollments(student_id: int) -> List[Dict[str, Any]]:
        """Возвращает список активных зачислений студента"""
        enrollments = Enrollment.objects.filter(
            student_id=student_id,
            is_active=True
        ).select_related('course', 'current_lesson')

        return [{
            'enrollment_id': e.id,
            'course_id': e.course.id,
            'course_title': e.course.title,
            'current_lesson': e.current_lesson.title if e.current_lesson else None,
            'progress_percent': e.get_progress_percent()
        } for e in enrollments]


class LearningAgent:
    """
    LearningAgent — оркестратор учебного процесса.

    Координирует взаимодействие между:
    - LearningService (координация шагов обучения)
    - ExplainabilityService (объяснение решений)
    - Orchestrator (внешние системы: UI, чат-боты, API)

    НАЗНАЧЕНИЕ:
    - Принимает решения о ТО, КОГДА запускать учебный процесс
    - Формирует человекочитаемые объяснения для студента
    - Управляет сессией обучения (начало, продолжение, завершение)
    - Обеспечивает fault tolerance при ошибках системы

    ОТЛИЧИЯ от LearningService:
    - LearningService: "КАК" выполнять шаги обучения (бизнес-логика)
    - LearningAgent: "КОГДА" и "ДЛЯ КОГО" запускать процесс (оркестрация, объяснения)

    ИНВАРИАНТЫ:
    - Не знает деталей оценки (использует LearningService)
    - Не работает напрямую с моделями Django
    - Не содержит бизнес-правил прогрессии
    - Не хранит состояние между вызовами
    """

    def __init__(self, enrollment: Enrollment):
        """
        Инициализация LearningAgent для конкретного студента.

        Args:
             enrollment: Конкретное зачисление студента на курс
        """
        self.enrollment = enrollment
        self.student = enrollment.student
        self.service_factory = CurriculumServiceFactory()
        self.learning_service = self.service_factory.create_learning_service()
        self.explainability_service = ExplainabilityService(
            lesson_explainer=self.service_factory.lesson_explainer,
            admin_explainer=self.service_factory.admin_explainer,
            student_explainer=StudentExplanationBuilder()
        )

    def get_next_task(self) -> Optional[Task]:
        """
        Возвращает следующее задание для студента.

        Логика:
        1. Использует LearningService для получения следующего задания
        2. Возвращает None, если задания закончились или курс завершен

        Returns:
            Task: Следующее задание или None
        """
        return self.learning_service.get_next_task(self.enrollment.pk)

    def get_current_lesson(self) -> Optional[Lesson]:
        """
        Возвращает текущий урок для студента.

        Returns:
            Lesson: Текущий урок или None
        """
        return self.enrollment.current_lesson

    def get_learning_state(self) -> Dict[str, Any]:
        """
        Возвращает полное состояние обучения студента.

        Включает:
        - Текущий урок и задание
        - Текущие навыки
        - Прогресс по курсу
        - Последние решения системы

        Returns:
            Dict[str, Any]: Структурированное состояние обучения
        """
        state = self.learning_service.get_current_state(self.enrollment.pk)

        # Вычисляем прогресс по курсу
        total_lessons = self.enrollment.course.lessons.count()
        current_lesson_order = self.enrollment.current_lesson.order if self.enrollment.current_lesson else 0
        course_progress = round(current_lesson_order / total_lessons * 100, 1) if total_lessons > 0 else 0

        return {
            "enrollment_id": self.enrollment.pk,
            "student_id": self.student.id,
            "course_id": self.enrollment.course.id,
            "course_title": self.enrollment.course.title,
            "course_progress_percent": course_progress,
            "current_lesson": {
                "id": state["current_lesson"],
                "title": self.enrollment.current_lesson.title if self.enrollment.current_lesson else None
            } if state["current_lesson"] else None,
            "current_task": {
                "id": state["current_task"],
            } if state["current_task"] else None,
            "skills": state["skills"],
            "last_activity": self.enrollment.last_activity,
            "is_completed": not self.enrollment.is_active
        }

    def submit_task_response(self, task_id: int, response_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Обрабатывает ответ студента на задание с полной функциональностью.

        Алгоритм:
        1. Проверяет корректность данных
        2. Записывает время начала обработки для метрик
        3. Передает данные в LearningService
        4. Получает результат с decision и feedback
        5. Получает актуальное состояние обучения
        6. Генерирует объяснение для студента
        7. Формирует полный структурированный ответ
        8. Логирует результаты для аналитики и отладки
        9. Обрабатывает ошибки с fallback-механизмами

        Args:
            task_id: ID задания
            response_payload: Ответ студента в формате:
                - Для текста: {"text": "ответ студента"}
                - Для аудио: {"audio_file": file_object, "transcript": "текстовая транскрипция (опционально)"}

        Returns:
            Dict[str, Any]: Структурированный результат:
                {
                    "decision": "ADVANCE_TASK",
                    "next_action": "NEXT_TASK",
                    "next_task_id": 102,
                    "feedback": {
                        "score": 0.85,
                        "is_correct": true,
                        "error_tags": [],
                        "message": "Отличный ответ!"
                    },
                    "explanation": {
                        "title": "Отличная работа 🚀",
                        "message": "Хорошая работа.",
                        "explanation": "Ты уверенно справляешься с этим материалом, поэтому мы идём дальше.",
                        "expectation": "В следующем уроке будет чуть больше вызова."
                    },
                    "skills_update": {
                        "grammar": 0.75,
                        "vocabulary": 0.68,
                        "listening": 0.62
                    },
                    "processing_time_sec": 1.234,
                    "assessment_id": 456,
                    "transition_id": 789
                }

        Raises:
            ValueError: При некорректных данных
            RuntimeError: При критических ошибках в процессе обучения
        """
        try:
            # Валидация входных данных
            if not task_id or not isinstance(task_id, int):
                raise ValueError("Invalid task_id")

            if not response_payload:
                raise ValueError("Empty response payload")

            # Записываем время начала обработки для метрик
            start_time = timezone.now()

            # 1. Обрабатываем ответ через LearningService
            result = self.learning_service.submit_task_response(
                enrollment_id=self.enrollment.pk,
                task_id=task_id,
                response_payload=response_payload
            )

            # 2. Получаем текущее состояние обучения для объяснений
            current_state = self.learning_service.get_current_state(self.enrollment.pk)

            # 3. Генерируем объяснение для студента
            explanation = self._generate_student_explanation(
                decision_code=result["decision"],
                current_skills=current_state["skills"],
                feedback=result["feedback"]
            )

            # 4. Добавляем детальную информацию для аналитики
            assessment = result.get("assessment")
            transition = result.get("transition")

            # 5. Формируем полный ответ
            full_response = {
                "decision": result["decision"],
                "next_action": result["next_action"],
                "next_task_id": result["next_task_id"],
                "feedback": result["feedback"],
                "explanation": explanation,
                "skills_update": current_state["skills"],
                "assessment_id": assessment.id if assessment else None,
                "transition_id": transition.id if transition else None,
                "processing_time_sec": (timezone.now() - start_time).total_seconds(),
                "timestamp": timezone.now().isoformat()
            }

            # 6. Логирование для аналитики
            logger.info(
                f"Task response processed successfully for enrollment {self.enrollment.pk}, "
                f"task {task_id}, decision: {result['decision']}, "
                f"time: {full_response['processing_time_sec']:.3f}s"
            )

            # 7. Отправка метрик в систему мониторинга
            self._send_metrics(full_response)

            return full_response

        except Exception as e:
            # Полная обработка ошибок с сохранением контекста
            error_context = {
                "enrollment_id": self.enrollment.pk,
                "task_id": task_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "traceback": traceback.format_exc() if settings.DEBUG else None
            }

            logger.error(
                f"Error in LearningAgent.submit_task_response: {str(e)}",
                extra=error_context,
                exc_info=True
            )

            # Отправка алерта администраторам при критических ошибках
            if self._is_critical_error(e):
                self._notify_admins(error_context)

            # Создание информативного fallback-ответа
            return self._create_fallback_response(task_id, str(e), error_context)

    def _send_metrics(self, response: Dict[str, Any]):
        """Отправка метрик в систему мониторинга"""
        try:
            metrics_client = get_metrics_client()
            metrics_client.timing("learning.task_processing_time", response["processing_time_sec"])
            metrics_client.increment(f"learning.decision.{response['decision']}")
            metrics_client.increment("learning.responses.total")

            # Метрики по навыкам
            for skill, value in response["skills_update"].items():
                metrics_client.gauge(f"learning.skills.{skill}", value)
        except Exception as e:
            logger.warning(f"Failed to send metrics: {str(e)}")

    def _is_critical_error(self, error: Exception) -> bool:
        """Определяет, является ли ошибка критической"""
        critical_errors = (DatabaseError, ConnectionError, TimeoutError)
        return isinstance(error, critical_errors)

    def _notify_admins(self, context: Dict[str, Any]):
        """Отправка уведомлений администраторам о критических ошибках"""
        try:
            admin_emails = settings.ADMIN_EMAILS
            subject = f"Critical error in learning process: Enrollment {context['enrollment_id']}"
            message = f"""
    Critical error occurred during task processing:
    - Enrollment ID: {context['enrollment_id']}
    - Task ID: {context['task_id']}
    - Error type: {context['error_type']}
    - Error message: {context['error_message']}
    - Timestamp: {timezone.now().isoformat()}

    Full traceback:
    {context.get('traceback', 'Not available in production')}
            """
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, admin_emails)
        except Exception as e:
            logger.error(f"Failed to notify admins: {str(e)}")

    def _generate_student_explanation(self, decision_code: str, current_skills: Dict, feedback: Dict) -> Dict[str, str]:
        """
        Генерирует человекочитаемое объяснение для студента.

        Использует:
        - StudentExplanationBuilder для формирования объяснения
        - NeutralTone как стандартный тон общения

        Args:
            decision_code: Код принятого решения
            current_skills: Текущее состояние навыков
            feedback: Обратная связь по заданию

        Returns:
            Dict[str, str]: Объяснение в формате:
                {
                    "title": "Отличная работа 🚀",
                    "message": "Хорошая работа.",
                    "explanation": "...",
                    "expectation": "..."
                }
        """

        # Создаем временный объект Decision для совместимости
        class TempDecision:
            def __init__(self, code):
                self.code = code
                self.outcome = code.split("_")[-1].lower() if "_" in code else code.lower()

        decision = TempDecision(decision_code)

        # Используем StudentExplanationBuilder с нейтральным тоном
        return self.explainability_service.student_explainer.build(
            decision=decision,
            metrics={"top_skills": self._get_top_skills(current_skills)},
            tone_strategy=NeutralTone()
        )

    def _get_top_skills(self, skills: Dict) -> list:
        """Получает топ-2 навыка по значению"""
        sorted_skills = sorted(skills.items(), key=lambda x: x[1], reverse=True)
        return [skill for skill, value in sorted_skills[:2]]

    def get_course_completion_status(self) -> Dict[str, Any]:
        """
        Возвращает статус завершения курса.

        Returns:
            Dict[str, Any]: {
                "is_completed": bool,
                "completion_percent": float,
                "remaining_lessons": int,
                "estimated_time_minutes": int
            }
        """
        # Получаем текущее состояние
        state = self.learning_service.get_current_state(self.enrollment.id)

        # Считаем прогресс
        total_lessons = self.enrollment.course.lessons.count()
        completed_lessons = Lesson.objects.filter(
            course=self.enrollment.course,
            order__lt=self.enrollment.current_lesson.order
        ).count() if self.enrollment.current_lesson else 0

        completion_percent = round(completed_lessons / total_lessons * 100, 1) if total_lessons > 0 else 0
        remaining_lessons = total_lessons - completed_lessons

        # Оцениваем оставшееся время (простая эвристика)
        avg_lesson_duration = 15  # минут, можно уточнить из данных
        estimated_time_minutes = remaining_lessons * avg_lesson_duration

        return {
            "is_completed": not self.enrollment.is_active,
            "completion_percent": completion_percent,
            "remaining_lessons": remaining_lessons,
            "estimated_time_minutes": estimated_time_minutes
        }

    def _create_fallback_response(self, task_id: int, error: str) -> Dict[str, Any]:
        """
        Создает резервный ответ при ошибках обработки.

        Args:
            task_id: ID задания
            error: Описание ошибки

        Returns:
            Dict[str, Any]: Безопасный ответ с сообщением об ошибке
        """
        logger.warning(f"Fallback response generated for task {task_id}: {error}")

        return {
            "decision": "RETRY_TASK",
            "next_action": "RETRY_TASK",
            "next_task_id": task_id,
            "feedback": {
                "message": "Произошла временная ошибка при обработке вашего ответа.",
                "note": "Пожалуйста, попробуйте отправить ответ еще раз."
            },
            "explanation": {
                "title": "Ошибка обработки",
                "message": "Система временно недоступна",
                "explanation": "Мы обнаружили проблему при обработке вашего ответа. Пожалуйста, попробуйте еще раз.",
                "expectation": "Ваш ответ будет обработан при следующей попытке."
            },
            "skills_update": {},
            "error": error,
            "fallback_mode": True
        }

    def restart_learning_session(self) -> Dict[str, Any]:
        """
        Перезапускает учебную сессию.

        Используется для:
        - Восстановления после ошибок
        - Сброса состояния при длительном перерыве
        - Ручного вмешательства преподавателя

        Returns:
            Dict[str, Any]: Начальное состояние сессии
        """
        # Обновляем last_activity для синхронизации
        self.enrollment.last_activity = timezone.now()
        self.enrollment.save(update_fields=["last_activity"])

        # Возвращаем начальное состояние
        return self.get_learning_state()
