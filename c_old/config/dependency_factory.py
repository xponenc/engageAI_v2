from curriculum.services.assessment.assessment_service import AssessmentService
from curriculum.services.assessment.lesson_assessment_service import LessonAssessmentService
from curriculum.services.learning_service import LearningService
from curriculum.services.skills.skill_update_service import SkillUpdateService
from curriculum.services.decisions.decision_service import DecisionService
from curriculum.services.progression.progression_service import ProgressionService
from curriculum.services.progression.transition_recorder import TransitionRecorder
from curriculum.infrastructure.adapters.auto_assessment_adapter import AutoAssessorAdapter
from curriculum.infrastructure.adapters.llm_assessment_adapter import LLMAssessmentAdapter


class CurriculumServiceFactory:
    """
    Фабрика для создания сервисов с правильными зависимостями.

    Режимы работы:
    1. INTERACTIVE_MODE (create_learning_service):
       - Для веб-интерфейса
       - Пошаговая обработка заданий
       - Быстрые ответы

    2. BATCH_MODE (create_lesson_assessment_service):
       - Для фоновых задач
       - Batch-обработка целых уроков
       - Отказоустойчивость
    """

    @classmethod
    def create_learning_service(cls):
        """
        Создает сервисы для интерактивного режима.
        """
        # Инициализация адаптеров
        auto_adapter = AutoAssessorAdapter()
        llm_adapter = LLMAssessmentAdapter()

        # Сервисы для интерактивного режима
        assessment_service = AssessmentService(
            auto_adapter=auto_adapter,
            llm_adapter=llm_adapter
        )

        skill_update_service = SkillUpdateService()
        decision_service = DecisionService()
        progression_service = ProgressionService()
        transition_recorder = TransitionRecorder()

        return LearningService(
            assessment_service=assessment_service,
            skill_update_service=skill_update_service,
            decision_service=decision_service,
            progression_service=progression_service,
            transition_recorder=transition_recorder
        )

    @classmethod
    def create_lesson_assessment_service(cls):
        """
        Создает сервисы для batch-обработки уроков.
        """
        # Инициализация адаптеров
        auto_adapter = AutoAssessorAdapter()
        llm_adapter = LLMAssessmentAdapter()

        # Сервисы для batch-обработки
        assessment_service = AssessmentService(
            auto_adapter=auto_adapter,
            llm_adapter=llm_adapter
        )

        skill_update_service = SkillUpdateService()
        decision_service = DecisionService()
        progression_service = ProgressionService()
        transition_recorder = TransitionRecorder()

        return LessonAssessmentService(
            assessment_service=assessment_service,
            skill_update_service=skill_update_service,
            decision_service=decision_service,
            progression_service=progression_service,
            transition_recorder=transition_recorder
        )