
from datetime import timezone
from django.utils import timezone
from curriculum.models.learning_process.lesson_event_log import LessonEventLog, LessonEventType
from curriculum.models.learning_process.learning_path import LearningPath
from curriculum.services.skills.skill_update_service import SkillUpdateService


class LessonEventService:
    """
    Сервис для создания и обработки событий урока.
    Используется в views, Celery tasks и Telegram-боте.
    """

    @staticmethod
    def create_event(student, enrollment, lesson, event_type: str, channel="WEB", metadata=None):
        """
        Создаёт событие и автоматически рассчитывает duration для COMPLETE.
        """
        metadata = metadata or {}

        event = LessonEventLog.objects.create(
            student=student,
            enrollment=enrollment,
            lesson=lesson,
            event_type=event_type,
            channel=channel,
            metadata=metadata
        )

        # Автоматический расчёт duration и обновление LearningPath
        if event_type == LessonEventType.COMPLETE:
            LessonEventService._handle_lesson_complete(enrollment, lesson, metadata)

        return event

    @staticmethod
    def _handle_lesson_complete(enrollment, lesson, metadata):
        """
        Логика после завершения урока:
        - Обновление текущего узла в LearningPath
        - Триггер расчёта SkillDelta
        - Начисление баллов в геймификации
        """
        if hasattr(enrollment, "learning_path"):
            learning_path = enrollment.learning_path
            learning_path.advance_to_next_node()  # Переход к следующему узлу

            from .decision_service import DecisionService

            SkillUpdateService.calculate_and_save_delta(enrollment, lesson)
            DecisionService.evaluate_and_adapt_path(enrollment, lesson)

            # Геймификация: базовые баллы за завершение
            # from curriculum.services.gamification_service import GamificationService
            # score = metadata.get("lesson_score", 0.8)
            # points = 50 + int(50 * score)  # 50–100 баллов
            # GamificationService.award_points(enrollment.student, points, reason=f"Завершение урока {lesson.title}")