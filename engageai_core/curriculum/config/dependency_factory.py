from ai.llm.llm_factory import llm_factory
from curriculum.services.assessment.assessment_service import AssessmentService
from curriculum.services.enrollment_service import EnrollmentService
from curriculum.services.skills.skill_update_service import SkillUpdateService
from curriculum.services.decisions.decision_service import DecisionService
from curriculum.services.progression.progression_service import ProgressionService
from curriculum.services.progression.transition_recorder import TransitionRecorder
from curriculum.services.curriculum_query import CurriculumQueryService
from curriculum.services.learning_service import LearningService
from curriculum.infrastructure.adapters.auto_assessment_adapter import AutoAssessorAdapter
from curriculum.infrastructure.adapters.llm_assessment_adapter import LLMAssessmentAdapter


class CurriculumServiceFactory:
    """
    Фабрика для создания и внедрения зависимостей
    Следует паттерну Singleton для обеспечения согласованности зависимостей
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Инициализация всех сервисов и зависимостей"""

        # Speech-to-Text сервис (вместо ASR)
        # self.speech_to_text_service = SpeechToTextFactory().get_service()

        # AutoAssessorAdapter для закрытых заданий и аудио
        self.auto_adapter = AutoAssessorAdapter()

        # LLMAssessmentAdapter для открытых заданий
        self.llm_adapter = LLMAssessmentAdapter()

        # Assessment Service (с выбором адаптера в зависимости от типа задания)
        self.assessment_service = AssessmentService(
            auto_adapter=self.auto_adapter,
            llm_adapter=self.llm_adapter
        )

        # Основные сервисы учебного процесса
        self.curriculum_query = CurriculumQueryService()
        self.skill_update_service = SkillUpdateService()
        self.decision_service = DecisionService()
        self.progression_service = ProgressionService(
            curriculum_query=self.curriculum_query
        )
        self.transition_recorder = TransitionRecorder()

        # Enrollment Service для управления зачислениями
        self.enrollment_service = EnrollmentService(
            curriculum_query=self.curriculum_query
        )

    def create_learning_service(self) -> LearningService:
        """Создает LearningService со всеми зависимостями"""
        return LearningService(
            curriculum_query=self.curriculum_query,
            assessment_service=self.assessment_service,
            skill_update_service=self.skill_update_service,
            decision_service=self.decision_service,
            progression_service=self.progression_service,
            transition_recorder=self.transition_recorder,
            enrollment_service=self.enrollment_service
        )

    def create_enrollment_service(self) -> EnrollmentService:
        """Создает EnrollmentService с зависимостями"""
        return self.enrollment_service

    def get_assessment_service(self) -> AssessmentService:
        """Возвращает AssessmentService для прямого использования"""
        return self.assessment_service

    def get_llm_factory(self):
        """Возвращает глобальную фабрику LLM для специализированных операций"""
        return llm_factory

    def get_curriculum_query_service(self) -> CurriculumQueryService:
        """Возвращает CurriculumQueryService"""
        return self.curriculum_query

    @classmethod
    def reset_instance(cls):
        """Сбрасывает singleton инстанс (для тестирования)"""
        cls._instance = None