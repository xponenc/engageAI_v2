import abc
import logging
from typing import List

from ai.llm_service.dtos import GenerationResult
from ai.llm_service.factory import llm_factory
from ai.orchestrator_v1.context.agent_context import AgentContext
from llm_logger.models import LLMRequestType

logger = logging.getLogger(__name__)


class BaseAgent(abc.ABC):
    """
    Абстрактный базовый класс для всех агентов чат-оркестратора.
    
    === ПОЛЯ КЛАССА (должны быть переопределены в наследниках) ===
    
    1. name: str
       Уникальное имя агента для идентификации в системе.
       
       Требования:
       - Должно быть уникальным в рамках всей системы
       - Рекомендуется использовать формат: "ContentAgent", "WritingAgent"
       - Используется для автоматической регистрации в реестре
       
       Пример:
           name = "ContentAgent"
    
    2. description: str
       Краткое описание назначения агента (1-2 предложения).
       
       Требования:
       - Должно быть понятным для человека
       - Используется в промптах для выбора агентов через LLM
       - Максимальная длина: 100 символов
       
       Пример:
           description = "Объяснение грамматики и лексики английского языка"
    
    3. supported_intents: List[str]
       Список намерений пользователя, которые агент может обрабатывать.
       
       Требования:
       - Строка в формате: "EXPLAIN_GRAMMAR", "CHECK_WRITING"
       - Используется для первичной фильтрации агентов
       - Может быть пустым списком (агент обрабатывает все намерения)
       
       Пример:
           supported_intents = ["EXPLAIN_GRAMMAR", "ANALYZE_ERROR", "WHY_WRONG"]
    
    4. capabilities: List[str] (опционально)
       Список возможностей агента для композиции с другими агентами.
       
       Требования:
       - Описывает, что агент умеет делать
       - Используется для выбора вспомогательных агентов
       - Может быть пустым списком
       
       Пример:
           capabilities = ["grammar_explanation", "vocabulary_teaching", "error_analysis"]
    
    5. version: str (опционально)
       Версия агента для отслеживания изменений.
       
       Требования:
       - Формат: "1.0", "2.1", "3.0-beta"
       - По умолчанию: "1.0"
       
       Пример:
           version = "2.1"

    """
    
    # === ПОЛЯ КЛАССА (должны быть переопределены в наследниках) ===
    
    name: str = "BaseAgent"
    description: str = "Abstract base agent"
    supported_intents: List[str] = []
    capabilities: List[str] = []
    version: str = "1.0"
    response_max_length: int = 300 # ограничение по числу слов в ответе через system_prompt
    fallback_agent: bool = False # использовать в списке фоллбэк, если сломался алгоритм выбора
    
    def __init__(self):
        """Инициализация агента"""
        self.llm = llm_factory
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    @abc.abstractmethod
    async def handle(self, context: AgentContext, request_type: LLMRequestType, response_max_length: int = None) -> GenerationResult:
        """
        Основной метод обработки запроса студента.
        
        ВАЖНО: Агент ВСЕГДА отвечает по содержанию вопроса студента.
        Адаптация под эмоциональное состояние происходит НА УРОВНЕ ОРКЕСТРАТОРА,
        а не через замену содержания ответа.
        
        Аргументы:
            context: Полный контекст запроса (см. AgentContext)
            
        Возвращает:
            AgentResponse с текстом ответа и метаданными
            
        Исключения:
            Любая ошибка обрабатывается оркестратором через фолбэк-агента.
            Агент НЕ должен прерывать учебный процесс из-за внутренних ошибок.
        """
        pass
    
    def _build_system_prompt(self, context: AgentContext) -> str:
        """
        Формирование системного промпта для LLM с учётом контекста.
        
        Базовая реализация — должна быть переопределена в наследниках.
        """
        return f"Вы — {self.description}. Отвечайте на вопросы студента."
